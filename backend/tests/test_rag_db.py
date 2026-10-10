"""Database tests for ingestion and search. They use the hashing embedder, so no model download."""

import shutil
from pathlib import Path

import pytest
from sqlalchemy import Engine, text

from incident_agent.config import REPO_ROOT
from incident_agent.rag import HashEmbedder, search_runbooks
from incident_agent.rag.chunker import chunk_runbook, load_runbooks
from incident_agent.rag.evaluate import (
    BEGIN,
    END,
    evaluate,
    load_queries,
    write_results,
)
from incident_agent.rag.ingest import RUNBOOKS_DIR, ingest

pytestmark = pytest.mark.db

EMB = HashEmbedder()


@pytest.fixture
def loaded(db_engine: Engine) -> Engine:
    """The real runbooks ingested into the test database."""
    ingest(engine=db_engine, embedder=EMB)
    return db_engine


def _count(engine: Engine, table: str) -> int:
    with engine.connect() as conn:
        return int(conn.execute(text(f"SELECT count(*) FROM {table}")).scalar_one())


def test_ingest_stores_every_doc_and_chunk(loaded: Engine) -> None:
    runbooks = load_runbooks(RUNBOOKS_DIR, REPO_ROOT)
    expected_chunks = sum(len(chunk_runbook(r)) for r in runbooks)
    assert _count(loaded, "runbook_docs") == len(runbooks)
    assert _count(loaded, "runbook_chunks") == expected_chunks
    with loaded.connect() as conn:
        row = conn.execute(
            text("SELECT categories, tags FROM runbook_docs WHERE doc_id = 'RB-FIBER-CUT'")
        ).one()
        assert row.categories == ["transport_failure"] and "fiber" in row.tags
        dim = conn.execute(text("SELECT vector_dims(embedding) FROM runbook_chunks LIMIT 1"))
        assert dim.scalar_one() == 384


def test_reingest_is_idempotent_and_skips_unchanged(loaded: Engine) -> None:
    before = _count(loaded, "runbook_chunks")
    report = ingest(engine=loaded, embedder=EMB)
    assert report.ingested == [] and len(report.skipped) == report.n_docs
    assert _count(loaded, "runbook_chunks") == before
    assert report.embed_seconds == 0.0


def test_changed_doc_is_replaced_and_removed_doc_is_deleted(loaded: Engine, tmp_path: Path) -> None:
    work = tmp_path / "runbooks"
    shutil.copytree(RUNBOOKS_DIR, work)
    (work / "RB-SYNC-LOSS.md").unlink()
    edited = work / "RB-SLEEPING-CELL.md"
    edited.write_text(
        edited.read_text(encoding="utf-8") + "\n\n## Extra notes\n\n" + "A brand new section. " * 8,
        encoding="utf-8",
    )
    try:
        report = ingest(engine=loaded, embedder=EMB, runbooks_dir=work)
        assert report.ingested == ["RB-SLEEPING-CELL"]
        assert report.removed == ["RB-SYNC-LOSS"]
        with loaded.connect() as conn:
            ids = conn.execute(
                text("SELECT DISTINCT doc_id FROM runbook_chunks WHERE doc_id = 'RB-SYNC-LOSS'")
            ).all()
        assert ids == []
    finally:
        restored = ingest(engine=loaded, embedder=EMB)
    assert sorted(restored.ingested) == ["RB-SLEEPING-CELL", "RB-SYNC-LOSS"]


def test_embedder_change_forces_reembedding(loaded: Engine) -> None:
    class Other(HashEmbedder):
        def __init__(self) -> None:
            super().__init__()
            self.name = "hash:other"

    report = ingest(engine=loaded, embedder=Other())
    assert report.skipped == []
    ingest(engine=loaded, embedder=EMB)


@pytest.mark.parametrize("mode", ["hybrid", "vector", "keyword"])
def test_all_modes_return_ranked_hits(loaded: Engine, mode: str) -> None:
    hits = search_runbooks(
        "loss of signal on the transport link took down the sites",
        k=5,
        mode=mode,  # type: ignore[arg-type]
        engine=loaded,
        embedder=EMB,
    )
    assert 0 < len(hits) <= 5
    assert hits[0].chunk_id.startswith("RB-")
    assert all(h.section_id.startswith(h.doc_id + "/") for h in hits)
    scores = [h.score for h in hits]
    assert scores == sorted(scores, reverse=True)


def test_keyword_search_finds_exact_alarm_code(loaded: Engine) -> None:
    hits = search_runbooks("MAINS_FAILURE BATTERY_LOW", k=3, mode="keyword", engine=loaded)
    assert hits and hits[0].doc_id in {"RB-POWER-FAILURE", "RB-ALARM-REFERENCE"}


def test_keyword_search_with_only_punctuation_returns_nothing(loaded: Engine) -> None:
    assert search_runbooks("?! ...", mode="keyword", engine=loaded) == []


def test_hybrid_contains_hits_from_both_rankings(loaded: Engine) -> None:
    query = "DNS_TIMEOUT_RATE alarm"
    vector = {h.chunk_id for h in search_runbooks(query, 20, "vector", engine=loaded, embedder=EMB)}
    keyword = {h.chunk_id for h in search_runbooks(query, 20, "keyword", engine=loaded)}
    hybrid = {h.chunk_id for h in search_runbooks(query, 10, "hybrid", engine=loaded, embedder=EMB)}
    assert hybrid <= vector | keyword
    assert hybrid & keyword


def test_unknown_mode_is_rejected(loaded: Engine) -> None:
    with pytest.raises(ValueError, match="unknown search mode"):
        search_runbooks("x", mode="fuzzy", engine=loaded, embedder=EMB)  # type: ignore[arg-type]


@pytest.mark.parametrize("mode", ["hybrid", "vector", "keyword"])
def test_agent_ro_can_search(loaded: Engine, agent_ro_engine: Engine, mode: str) -> None:
    with agent_ro_engine.connect() as conn:
        assert conn.execute(text("SHOW default_transaction_read_only")).scalar_one() == "on"
    hits = search_runbooks(
        "site went down two hours after a mains alarm",
        k=3,
        mode=mode,  # type: ignore[arg-type]
        engine=agent_ro_engine,
        embedder=EMB,
    )
    assert hits


def test_agent_ro_cannot_write_runbooks(loaded: Engine, agent_ro_engine: Engine) -> None:
    from sqlalchemy.exc import DBAPIError

    with pytest.raises(DBAPIError), agent_ro_engine.begin() as conn:
        conn.execute(text("DELETE FROM runbook_docs"))


def test_evaluate_runs_and_keeps_hand_written_prose(loaded: Engine, tmp_path: Path) -> None:
    queries = load_queries()
    results = evaluate(queries, engine=loaded, embedder=EMB)
    assert set(results["modes"]) == {"hybrid", "vector", "keyword"}
    for data in results["modes"].values():
        assert set(data["by_type"]) == {q.type for q in queries}
        assert all(0.0 <= v <= 1.0 for v in data["overall"].values())

    write_results(results, queries, tmp_path)
    md = tmp_path / "retrieval.md"
    md.write_text("INTRO\n" + md.read_text(encoding="utf-8") + "\nOUTRO\n", encoding="utf-8")
    write_results(results, queries, tmp_path)
    text_after = md.read_text(encoding="utf-8")
    assert text_after.startswith("INTRO\n") and text_after.rstrip().endswith("OUTRO")
    assert text_after.count(BEGIN) == 1 and text_after.count(END) == 1
    assert (tmp_path / "retrieval.json").exists()
