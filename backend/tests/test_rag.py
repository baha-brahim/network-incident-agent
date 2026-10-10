"""Unit tests for the runbook knowledge base: no database, no embedding model."""

import re
from pathlib import Path

import pytest

from incident_agent.config import REPO_ROOT
from incident_agent.rag import EMBEDDING_DIM, HashEmbedder
from incident_agent.rag.chunker import (
    Runbook,
    chunk_runbook,
    count_tokens,
    load_runbooks,
    parse_runbook,
    section_ids,
    slugify,
)
from incident_agent.rag.evaluate import QUERIES_PATH, load_queries
from incident_agent.rag.metrics import (
    dedupe_sections,
    hit_at_k,
    ndcg_at_k,
    paired_bootstrap,
    query_metrics,
    recall_at_k,
    reciprocal_rank,
)
from incident_agent.rag.search import or_query, rrf_fuse

RUNBOOKS_DIR = REPO_ROOT / "runbooks"

# Root-cause categories used by the simulator.
CATEGORIES = {
    "transport_failure",
    "power_failure",
    "bad_change",
    "core_degradation",
    "capacity",
    "transport_degradation",
    "planned_maintenance",
    "expected_event",
    "no_impact",
}

FRONT = "---\nid: RB-TEST-DOC\ntitle: Test doc\ntags: [a, b]\ncategories: [capacity]\n---\n"


def make(body: str) -> str:
    return FRONT + body


def words(n: int) -> str:
    return " ".join(f"word{i}" for i in range(n))


# --- front matter -------------------------------------------------------------------------------


def test_parse_front_matter() -> None:
    rb = parse_runbook(make("# T\n\n## One\n\ntext\n"), "runbooks/x.md")
    assert (rb.doc_id, rb.title) == ("RB-TEST-DOC", "Test doc")
    assert rb.tags == ["a", "b"] and rb.categories == ["capacity"]


@pytest.mark.parametrize(
    "text",
    [
        "# no front matter\n",
        "---\nid: bad-id\ntitle: T\ntags: []\ncategories: []\n---\nbody",
        "---\nid: RB-X\ntitle: T\ntags: nope\ncategories: []\n---\nbody",
        "---\nid: RB-X\ntags: []\ncategories: []\n---\nbody",
    ],
)
def test_parse_rejects_bad_front_matter(text: str) -> None:
    with pytest.raises(ValueError):
        parse_runbook(text, "x.md")


# --- chunker --------------------------------------------------------------------------------------


def test_slugify() -> None:
    assert slugify("Differential diagnosis") == "differential-diagnosis"
    assert slugify("Step 1: define the symptom!") == "step-1-define-the-symptom"


def test_one_chunk_per_section_with_stable_ids() -> None:
    body = f"# T\n\n## First part\n\n{words(40)}\n\n## Second part\n\n{words(40)}\n"
    chunks = chunk_runbook(parse_runbook(make(body), "x.md"))
    assert [c.chunk_id for c in chunks] == ["RB-TEST-DOC#01", "RB-TEST-DOC#02"]
    assert [c.section_id for c in chunks] == [
        "RB-TEST-DOC/first-part",
        "RB-TEST-DOC/second-part",
    ]
    assert chunks[0].heading_path == "Test doc > First part"
    again = chunk_runbook(parse_runbook(make(body), "x.md"))
    assert chunks == again


def test_long_section_splits_at_subheadings_and_keeps_section_id() -> None:
    body = (
        f"## Differential\n\n### Versus A\n\n{words(120)}\n\n"
        f"### Versus B\n\n{words(120)}\n\n### Versus C\n\n{words(120)}\n"
    )
    chunks = chunk_runbook(parse_runbook(make(body), "x.md"), max_tokens=300, min_tokens=25)
    assert len(chunks) == 2
    assert {c.section_id for c in chunks} == {"RB-TEST-DOC/differential"}
    # Pieces holding several subsections are named after the section; a lone one after itself.
    assert chunks[0].heading_path == "Test doc > Differential"
    assert chunks[1].heading_path == "Test doc > Differential > Versus C"
    assert "### Versus C" in chunks[1].content


def test_long_paragraph_run_splits_at_blank_lines() -> None:
    paras = "\n\n".join(words(100) for _ in range(6))
    chunks = chunk_runbook(parse_runbook(make(f"## Big\n\n{paras}\n"), "x.md"), max_tokens=250)
    assert len(chunks) >= 3
    assert all(c.n_tokens < 400 for c in chunks)
    assert {c.section_id for c in chunks} == {"RB-TEST-DOC/big"}


def test_tiny_section_is_folded_into_previous_chunk() -> None:
    body = f"## Real\n\n{words(80)}\n\n## Tiny\n\nshort note\n"
    chunks = chunk_runbook(parse_runbook(make(body), "x.md"), min_tokens=25)
    assert len(chunks) == 1
    assert "short note" in chunks[0].content


def test_headings_inside_code_fences_are_not_headings() -> None:
    body = f"## Query\n\n{words(60)}\n\n```sql\n# not a heading\nSELECT 1;\n```\n"
    chunks = chunk_runbook(parse_runbook(make(body), "x.md"))
    assert len(chunks) == 1 and "# not a heading" in chunks[0].content


def test_duplicate_section_headings_are_rejected() -> None:
    body = f"## Same\n\n{words(50)}\n\n## Same\n\n{words(50)}\n"
    with pytest.raises(ValueError, match="duplicate section"):
        chunk_runbook(parse_runbook(make(body), "x.md"))


def test_embed_text_starts_with_heading_path() -> None:
    chunk = chunk_runbook(parse_runbook(make(f"## Part\n\n{words(50)}\n"), "x.md"))[0]
    assert chunk.embed_text.startswith("Test doc > Part\n")


def test_count_tokens_counts_words_and_punctuation() -> None:
    assert count_tokens("LINK_LOS on link, now.") == 6


# --- the real runbooks ----------------------------------------------------------------------------


@pytest.fixture(scope="module")
def runbooks() -> list[Runbook]:
    return load_runbooks(RUNBOOKS_DIR, REPO_ROOT)


def test_every_runbook_parses_with_required_front_matter(runbooks: list[Runbook]) -> None:
    assert len(runbooks) >= 20
    for rb in runbooks:
        assert rb.doc_id == Path(rb.path).stem
        assert rb.tags, rb.doc_id
        assert set(rb.categories) <= CATEGORIES, rb.doc_id


def test_every_category_has_a_runbook(runbooks: list[Runbook]) -> None:
    covered = {c for rb in runbooks for c in rb.categories}
    assert covered >= CATEGORIES


def test_runbook_length_is_in_range(runbooks: list[Runbook]) -> None:
    for rb in runbooks:
        n = len(rb.body.split())
        assert 400 <= n <= 800, f"{rb.doc_id} has {n} words"


def test_runbooks_do_not_name_dataset_scenarios_or_nodes(runbooks: list[Runbook]) -> None:
    forbidden = re.compile(
        r"\bSCN-\d+|\bALM-\d+|\bCHG-\d|\bMW-\d|\bEVT-\d|\bS-[A-Z]{3}-\d{3}\b|"
        r"\bLNK-[A-Z]{3}-\d\d-[ABC]\b|\bAGG-[A-Z]{3}-\d\d\b|\b2026-\d\d-\d\d\b"
    )
    for rb in runbooks:
        assert not forbidden.search(rb.text), rb.doc_id


def test_no_section_is_lost_or_oversized(runbooks: list[Runbook]) -> None:
    for rb in runbooks:
        chunks = chunk_runbook(rb)
        h2 = [slugify(m) for m in re.findall(r"^## (.+)$", rb.body, flags=re.MULTILINE)]
        assert list(dict.fromkeys(c.section_id.split("/", 1)[1] for c in chunks)) == h2, rb.doc_id
        assert max(c.n_tokens for c in chunks) < 450, rb.doc_id


# --- evaluation queries ---------------------------------------------------------------------------


def test_queries_reference_existing_sections(runbooks: list[Runbook]) -> None:
    known = section_ids(runbooks)
    queries = load_queries(QUERIES_PATH)
    assert len(queries) >= 45
    for q in queries:
        assert q.relevant <= known, (q.id, sorted(q.relevant - known))


def test_queries_cover_all_types() -> None:
    types = {q.type for q in load_queries(QUERIES_PATH)}
    assert types == {"alarm_code", "paraphrase", "differential", "procedure", "distractor"}


def test_queries_do_not_quote_document_headings(runbooks: list[Runbook]) -> None:
    headings = {
        h.strip().lower()
        for rb in runbooks
        for h in re.findall(r"^#{2,3} (.+)$", rb.body, flags=re.MULTILINE)
    }
    headings.update(rb.title.lower() for rb in runbooks)
    for q in load_queries(QUERIES_PATH):
        text = q.query.lower()
        hit = [h for h in headings if len(h.split()) >= 2 and h in text]
        assert not hit, (q.id, hit)


# --- search helpers -------------------------------------------------------------------------------


def test_rrf_rewards_agreement_between_rankings() -> None:
    fused = rrf_fuse([["a", "b"], ["c", "b"]])
    ids = [i for i, _ in fused]
    assert ids[0] == "b"  # second in both beats first in one
    assert set(ids) == {"a", "b", "c"}


def test_rrf_scores_follow_the_formula() -> None:
    fused = dict(rrf_fuse([["a"], ["a"]], k=60))
    assert fused["a"] == pytest.approx(2 / 61)


def test_or_query_splits_on_punctuation_and_dedupes() -> None:
    assert or_query("LINK_LOS on link-7, LINK_LOS!") == "link | los | on | 7"
    assert or_query("  ?! ") is None
    assert "'" not in (or_query("it's; DROP TABLE x") or "")


# --- metrics --------------------------------------------------------------------------------------


def test_recall_counts_found_share_of_relevant() -> None:
    ranked = ["x", "a", "y", "b"]
    assert recall_at_k(ranked, {"a", "b"}, 1) == 0.0
    assert recall_at_k(ranked, {"a", "b"}, 2) == 0.5
    assert recall_at_k(ranked, {"a", "b"}, 5) == 1.0


def test_hit_at_k_is_one_when_any_relevant_section_is_in_the_top_k() -> None:
    ranked = ["x", "a", "y", "b"]
    assert hit_at_k(ranked, {"a", "b"}, 1) == 0.0
    assert hit_at_k(ranked, {"a", "b"}, 2) == 1.0
    assert hit_at_k(ranked, {"b"}, 3) == 0.0
    assert hit_at_k(ranked, {"b"}, 4) == 1.0
    assert hit_at_k([], {"a"}, 5) == 0.0


def test_reciprocal_rank() -> None:
    assert reciprocal_rank(["x", "y", "a"], {"a"}) == pytest.approx(1 / 3)
    assert reciprocal_rank(["x", "y"], {"a"}) == 0.0
    assert reciprocal_rank(["x"] * 10 + ["a"], {"a"}, k=10) == 0.0


def test_ndcg_perfect_and_imperfect() -> None:
    assert ndcg_at_k(["a", "b", "x"], {"a", "b"}, 5) == pytest.approx(1.0)
    worse = ndcg_at_k(["x", "a", "b"], {"a", "b"}, 5)
    assert 0.0 < worse < 1.0
    assert ndcg_at_k(["x", "y"], {"a"}, 5) == 0.0


def test_ndcg_single_relevant_at_rank_two() -> None:
    assert ndcg_at_k(["x", "a"], {"a"}, 5) == pytest.approx(1 / 1.5849625, rel=1e-4)


def test_dedupe_sections_keeps_first_occurrence() -> None:
    assert dedupe_sections(["a", "b", "a", "c", "b"]) == ["a", "b", "c"]


def test_paired_bootstrap_interval_brackets_the_mean_and_is_repeatable() -> None:
    diffs = [0.0, 1.0, 0.0, 1.0, 1.0, 0.0, 1.0, 1.0]
    mean, lo, hi = paired_bootstrap(diffs)
    assert mean == pytest.approx(0.625)
    assert lo < mean < hi
    assert paired_bootstrap(diffs) == (mean, lo, hi)
    assert paired_bootstrap([0.5] * 10) == (0.5, 0.5, 0.5)


def test_query_metrics_has_all_keys() -> None:
    m = query_metrics(["a"], {"a"})
    assert set(m) == {
        "hit@1",
        "hit@3",
        "hit@5",
        "recall@1",
        "recall@3",
        "recall@5",
        "mrr@10",
        "ndcg@5",
    }
    assert all(v == 1.0 for v in m.values())


# --- hash embedder --------------------------------------------------------------------------------


def test_hash_embedder_is_deterministic_and_normalised() -> None:
    e = HashEmbedder()
    v1, v2 = e.embed_query("fiber cut on link"), e.embed_query("fiber cut on link")
    assert v1 == v2 and len(v1) == EMBEDDING_DIM
    assert sum(x * x for x in v1) == pytest.approx(1.0)
    assert e.embed_documents(["fiber cut on link"])[0] == v1


def test_hash_embedder_prefers_shared_words() -> None:
    e = HashEmbedder()
    q = e.embed_query("transport link failure")
    close = e.embed_query("failure of a transport link")
    far = e.embed_query("battery inspection schedule")
    dot = lambda a, b: sum(x * y for x, y in zip(a, b, strict=True))  # noqa: E731
    assert dot(q, close) > dot(q, far)


def test_hash_embedder_handles_empty_text() -> None:
    assert len(HashEmbedder().embed_query("")) == EMBEDDING_DIM
