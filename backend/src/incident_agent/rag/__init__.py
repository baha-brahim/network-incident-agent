"""Runbook knowledge base: chunking, embedding, ingestion and search."""

from incident_agent.rag.embedder import EMBEDDING_DIM, Embedder, FastEmbedEmbedder, HashEmbedder
from incident_agent.rag.search import RunbookHit, search_runbooks

__all__ = [
    "EMBEDDING_DIM",
    "Embedder",
    "FastEmbedEmbedder",
    "HashEmbedder",
    "RunbookHit",
    "search_runbooks",
]
