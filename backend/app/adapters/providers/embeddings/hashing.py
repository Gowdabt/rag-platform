from __future__ import annotations

import hashlib
import math

from app.config.models import EmbeddingConfig
from app.core.context import RequestContext
from app.domain.ports.embeddings import EmbeddingProvider
from app.domain.registry import register
from app.domain.types import EmbeddingResult


@register("embedding", "hashing")
class HashingEmbedding(EmbeddingProvider):
    """Deterministic hashing embeddings for local tests and CI. Not a semantic model."""

    def __init__(self, config: EmbeddingConfig, ctx: RequestContext):
        super().__init__(config, ctx)

    @property
    def dimensions(self) -> int:
        return self.config.dimensions or 256

    async def embed_documents(self, texts: list[str]) -> EmbeddingResult:
        dim = self.dimensions
        vectors = [_hash_vector(t, dim) for t in texts]
        return EmbeddingResult(
            vectors=vectors, model="hashing", provider="hashing", dimensions=dim, version="1"
        )

    async def embed_query(self, text: str) -> EmbeddingResult:
        return await self.embed_documents([text])


def _hash_vector(text: str, dim: int) -> list[float]:
    raw = b""
    seed = text.encode("utf-8")
    i = 0
    while len(raw) < dim * 4:
        raw += hashlib.sha256(seed + i.to_bytes(4, "big")).digest()
        i += 1
    vals = []
    for idx in range(dim):
        n = int.from_bytes(raw[idx * 4 : idx * 4 + 4], "big")
        vals.append((n / 2**32) * 2 - 1)
    norm = math.sqrt(sum(v * v for v in vals)) or 1.0
    return [v / norm for v in vals]
