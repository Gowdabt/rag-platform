from __future__ import annotations

from abc import ABC, abstractmethod
from uuid import UUID

from app.core.context import RequestContext
from app.domain.types import SparseDocument, VectorFilter, VectorHit


class SparseIndex(ABC):
    def __init__(self, ctx: RequestContext):
        self.ctx = ctx

    @abstractmethod
    async def upsert(self, documents: list[SparseDocument]) -> None:
        raise NotImplementedError

    @abstractmethod
    async def search(
        self,
        query: str,
        *,
        top_k: int,
        filters: VectorFilter,
    ) -> list[VectorHit]:
        raise NotImplementedError

    @abstractmethod
    async def delete(self, chunk_ids: list[UUID], *, filters: VectorFilter) -> None:
        raise NotImplementedError
