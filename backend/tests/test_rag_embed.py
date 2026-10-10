"""Tests that load the real embedding model (downloads ~100 MB on first use)."""

import math

import pytest

from incident_agent.config import REPO_ROOT
from incident_agent.rag import EMBEDDING_DIM, FastEmbedEmbedder
from incident_agent.rag.chunker import chunk_runbook, load_runbooks

pytestmark = pytest.mark.embed


@pytest.fixture(scope="module")
def embedder() -> FastEmbedEmbedder:
    return FastEmbedEmbedder()


def _cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b, strict=True))
    return dot / (math.sqrt(sum(x * x for x in a)) * math.sqrt(sum(x * x for x in b)))


def test_model_gives_384_dimensional_vectors(embedder: FastEmbedEmbedder) -> None:
    docs = embedder.embed_documents(["first passage", "second passage"])
    query = embedder.embed_query("a question")
    assert len(docs) == 2 and all(len(v) == EMBEDDING_DIM for v in docs)
    assert len(query) == EMBEDDING_DIM
    assert embedder.embed_documents(["first passage"])[0] == pytest.approx(docs[0], abs=1e-4)


def test_paraphrase_query_ranks_the_right_runbook_first(embedder: FastEmbedEmbedder) -> None:
    chunks = [
        c for rb in load_runbooks(REPO_ROOT / "runbooks", REPO_ROOT) for c in chunk_runbook(rb)
    ]
    vectors = embedder.embed_documents([c.embed_text for c in chunks])
    query = embedder.embed_query("site went down two hours after a mains alarm")
    ranked = sorted(zip(chunks, vectors, strict=True), key=lambda cv: -_cosine(query, cv[1]))
    assert "RB-POWER-FAILURE" in {c.doc_id for c, _ in ranked[:3]}
