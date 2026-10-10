"""Runbook search: vector, keyword or hybrid. Read-only, so it works as the `agent_ro` role."""

import re
from dataclasses import dataclass
from typing import Any, Literal

from sqlalchemy import Engine, Row, text

from incident_agent.db.session import get_engine
from incident_agent.rag.embedder import Embedder, get_embedder
from incident_agent.rag.ingest import vector_literal

SearchMode = Literal["hybrid", "vector", "keyword"]
DEFAULT_MODE: SearchMode = "hybrid"

CANDIDATES = 20  # how deep each ranking goes before fusion
RRF_K = 60  # the usual damping constant of reciprocal rank fusion

_TERM = re.compile(r"[A-Za-z0-9]+")
_COLUMNS = "chunk_id, doc_id, section_id, heading_path, content"


@dataclass(frozen=True)
class RunbookHit:
    chunk_id: str
    doc_id: str
    section_id: str
    heading_path: str
    content: str
    score: float


def rrf_fuse(rankings: list[list[str]], k: int = RRF_K) -> list[tuple[str, float]]:
    """Reciprocal rank fusion: score(id) = sum over rankings of 1 / (k + rank), rank from 1."""
    scores: dict[str, float] = {}
    for ranking in rankings:
        for rank, item in enumerate(ranking, start=1):
            scores[item] = scores.get(item, 0.0) + 1.0 / (k + rank)
    return sorted(scores.items(), key=lambda kv: (-kv[1], kv[0]))


def or_query(query: str) -> str | None:
    """Turn free text into a tsquery that ORs its terms. A plain AND finds nothing for long text."""
    terms = list(dict.fromkeys(t.lower() for t in _TERM.findall(query)))
    return " | ".join(terms) or None


def _hit(row: Row[Any], score: float) -> RunbookHit:
    return RunbookHit(
        chunk_id=row.chunk_id,
        doc_id=row.doc_id,
        section_id=row.section_id,
        heading_path=row.heading_path,
        content=row.content,
        score=score,
    )


def _vector_hits(engine: Engine, embedder: Embedder, query: str, n: int) -> list[RunbookHit]:
    vec = vector_literal(embedder.embed_query(query))
    sql = text(
        f"SELECT {_COLUMNS}, 1 - (embedding <=> CAST(:v AS vector)) AS score "
        "FROM runbook_chunks ORDER BY embedding <=> CAST(:v AS vector), chunk_id LIMIT :n"
    )
    with engine.connect() as conn:
        return [_hit(row, float(row.score)) for row in conn.execute(sql, {"v": vec, "n": n})]


def _keyword_hits(engine: Engine, query: str, n: int) -> list[RunbookHit]:
    tsq = or_query(query)
    if tsq is None:
        return []
    sql = text(
        f"SELECT {_COLUMNS}, ts_rank_cd(tsv, q, 1) AS score "
        "FROM runbook_chunks, to_tsquery('english', :q) AS q WHERE tsv @@ q "
        "ORDER BY score DESC, chunk_id LIMIT :n"
    )
    with engine.connect() as conn:
        return [_hit(row, float(row.score)) for row in conn.execute(sql, {"q": tsq, "n": n})]


def search_runbooks(
    query: str,
    k: int = 5,
    mode: SearchMode = DEFAULT_MODE,
    *,
    engine: Engine | None = None,
    embedder: Embedder | None = None,
) -> list[RunbookHit]:
    """Return the `k` best runbook chunks for a free-text query."""
    engine = engine or get_engine()
    if mode == "keyword":
        return _keyword_hits(engine, query, k)
    embedder = embedder or get_embedder()
    if mode == "vector":
        return _vector_hits(engine, embedder, query, k)
    if mode != "hybrid":
        raise ValueError(f"unknown search mode: {mode!r}")
    vector = _vector_hits(engine, embedder, query, CANDIDATES)
    keyword = _keyword_hits(engine, query, CANDIDATES)
    by_id = {h.chunk_id: h for h in [*keyword, *vector]}
    fused = rrf_fuse([[h.chunk_id for h in vector], [h.chunk_id for h in keyword]])
    return [
        RunbookHit(
            chunk_id=cid,
            doc_id=by_id[cid].doc_id,
            section_id=by_id[cid].section_id,
            heading_path=by_id[cid].heading_path,
            content=by_id[cid].content,
            score=score,
        )
        for cid, score in fused[:k]
    ]
