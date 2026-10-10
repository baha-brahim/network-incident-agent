"""Text embedders: the real local model, and a deterministic hashing stand-in for tests."""

import hashlib
import math
import re
import time
from functools import lru_cache
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

from incident_agent.config import get_settings

EMBEDDING_MODEL = "BAAI/bge-small-en-v1.5"
# Must match the vector(384) column in migration 0003.
EMBEDDING_DIM = 384


@runtime_checkable
class Embedder(Protocol):
    name: str

    def embed_documents(self, texts: list[str]) -> list[list[float]]: ...

    def embed_query(self, text: str) -> list[float]: ...


class FastEmbedEmbedder:
    """bge-small via fastembed (ONNX, CPU). The model loads on first use."""

    def __init__(self, cache_dir: Path | None = None, model_name: str = EMBEDDING_MODEL) -> None:
        self._cache_dir = cache_dir
        self._model_name = model_name
        self._model: Any = None
        self.load_seconds: float | None = None
        self.name = f"fastembed:{model_name}"

    def _load(self) -> Any:
        if self._model is None:
            from fastembed import TextEmbedding

            cache = self._cache_dir or get_settings().embedding_cache_dir
            cache.mkdir(parents=True, exist_ok=True)
            start = time.perf_counter()
            self._model = TextEmbedding(model_name=self._model_name, cache_dir=str(cache))
            self.load_seconds = time.perf_counter() - start
        return self._model

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        model = self._load()
        return [[float(x) for x in vec] for vec in model.passage_embed(texts)]

    def embed_query(self, text: str) -> list[float]:
        model = self._load()
        vec = next(iter(model.query_embed(text)))
        return [float(x) for x in vec]


_WORD = re.compile(r"[a-z0-9]+")


class HashEmbedder:
    """Bag-of-words hashing embedder: same text, same vector, on every machine.

    Not semantic. It only knows shared words, which is enough to test the plumbing.
    """

    def __init__(self, dim: int = EMBEDDING_DIM) -> None:
        self._dim = dim
        self.name = f"hash:{dim}"

    def _vector(self, text: str) -> list[float]:
        vec = [0.0] * self._dim
        for word in _WORD.findall(text.lower()):
            digest = hashlib.blake2b(word.encode(), digest_size=8).digest()
            value = int.from_bytes(digest, "big")
            vec[value % self._dim] += 1.0 if (value >> 40) & 1 else -1.0
        norm = math.sqrt(sum(x * x for x in vec))
        if norm == 0.0:
            vec[0] = 1.0
            return vec
        return [x / norm for x in vec]

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [self._vector(t) for t in texts]

    def embed_query(self, text: str) -> list[float]:
        return self._vector(text)


@lru_cache
def get_embedder() -> FastEmbedEmbedder:
    """The shared real embedder, so the model is loaded once per process."""
    return FastEmbedEmbedder()
