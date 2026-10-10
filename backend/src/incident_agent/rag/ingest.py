"""Load runbooks into `runbook_docs` and `runbook_chunks`.

Idempotent: a document whose hash is unchanged is neither re-chunked in the database nor
re-embedded. The hash covers the file text, the chunker version and the embedder name, so a new
chunking or a different embedding model refreshes the stored vectors.
"""

import hashlib
import time
from dataclasses import dataclass, field
from pathlib import Path

from sqlalchemy import Connection, Engine, text

from incident_agent.config import REPO_ROOT
from incident_agent.db.session import get_engine
from incident_agent.rag.chunker import CHUNKER_VERSION, Chunk, Runbook, chunk_runbook, load_runbooks
from incident_agent.rag.embedder import EMBEDDING_DIM, Embedder, get_embedder

RUNBOOKS_DIR = REPO_ROOT / "runbooks"


@dataclass
class IngestReport:
    n_docs: int = 0
    n_chunks: int = 0
    ingested: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)
    removed: list[str] = field(default_factory=list)
    token_counts: list[int] = field(default_factory=list)  # of the chunks written this run
    embed_seconds: float = 0.0
    total_seconds: float = 0.0


def content_hash(runbook: Runbook, embedder: Embedder) -> str:
    payload = f"{CHUNKER_VERSION}\n{embedder.name}\n{runbook.text}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def vector_literal(vec: list[float]) -> str:
    if len(vec) != EMBEDDING_DIM:
        raise ValueError(f"expected a {EMBEDDING_DIM}-dim vector, got {len(vec)}")
    return "[" + ",".join(f"{x:.7g}" for x in vec) + "]"


_INSERT_DOC = text(
    "INSERT INTO runbook_docs (doc_id, title, path, tags, categories, content_hash) "
    "VALUES (:doc_id, :title, :path, CAST(:tags AS text[]), CAST(:categories AS text[]), :hash)"
)
_INSERT_CHUNK = text(
    "INSERT INTO runbook_chunks "
    "(chunk_id, doc_id, ordinal, section_id, heading_path, content, n_tokens, embedding) "
    "VALUES (:chunk_id, :doc_id, :ordinal, :section_id, :heading_path, :content, :n_tokens, "
    "CAST(:embedding AS vector))"
)


def _write_doc(
    conn: Connection, runbook: Runbook, chunks: list[Chunk], vectors: list[list[float]], h: str
) -> None:
    conn.execute(text("DELETE FROM runbook_docs WHERE doc_id = :d"), {"d": runbook.doc_id})
    conn.execute(
        _INSERT_DOC,
        {
            "doc_id": runbook.doc_id,
            "title": runbook.title,
            "path": runbook.path,
            "tags": runbook.tags,
            "categories": runbook.categories,
            "hash": h,
        },
    )
    conn.execute(
        _INSERT_CHUNK,
        [
            {
                "chunk_id": c.chunk_id,
                "doc_id": c.doc_id,
                "ordinal": c.ordinal,
                "section_id": c.section_id,
                "heading_path": c.heading_path,
                "content": c.content,
                "n_tokens": c.n_tokens,
                "embedding": vector_literal(v),
            }
            for c, v in zip(chunks, vectors, strict=True)
        ],
    )


def ingest(
    engine: Engine | None = None,
    embedder: Embedder | None = None,
    runbooks_dir: Path | None = None,
) -> IngestReport:
    """Bring the database in line with the runbook files, in one transaction."""
    started = time.perf_counter()
    engine = engine or get_engine()
    embedder = embedder or get_embedder()
    runbooks = load_runbooks(runbooks_dir or RUNBOOKS_DIR, REPO_ROOT)
    report = IngestReport(n_docs=len(runbooks))

    with engine.begin() as conn:
        stored = {
            row.doc_id: row.content_hash
            for row in conn.execute(text("SELECT doc_id, content_hash FROM runbook_docs"))
        }
        current = {r.doc_id for r in runbooks}
        for gone in sorted(set(stored) - current):
            conn.execute(text("DELETE FROM runbook_docs WHERE doc_id = :d"), {"d": gone})
            report.removed.append(gone)

        for runbook in runbooks:
            h = content_hash(runbook, embedder)
            chunks = chunk_runbook(runbook)
            report.n_chunks += len(chunks)
            if stored.get(runbook.doc_id) == h:
                report.skipped.append(runbook.doc_id)
                continue
            t0 = time.perf_counter()
            vectors = embedder.embed_documents([c.embed_text for c in chunks])
            report.embed_seconds += time.perf_counter() - t0
            _write_doc(conn, runbook, chunks, vectors, h)
            report.ingested.append(runbook.doc_id)
            report.token_counts.extend(c.n_tokens for c in chunks)

    report.total_seconds = time.perf_counter() - started
    return report
