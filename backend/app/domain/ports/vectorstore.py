from __future__ import annotations

from abc import ABC, abstractmethod
from uuid import UUID

from app.config.models import VectorStoreConfig
from app.core.context import RequestContext
from app.domain.types import VectorFilter, VectorHit, VectorRecord


class VectorStore(ABC):
    def __init__(self, config: VectorStoreConfig, ctx: RequestContext):
        self.config = config
        self.ctx = ctx

    @abstractmethod
    async def create_collection(self, *, dimensions: int) -> None:
        raise NotImplementedError

    @abstractmethod
    async def upsert(self, records: list[VectorRecord]) -> None:
        raise NotImplementedError

    @abstractmethod
    async def search(
        self,
        embedding: list[float],
        *,
        top_k: int,
        filters: VectorFilter,
    ) -> list[VectorHit]:
        """Fail closed if filters.tenant_id is missing (types require it)."""
        raise NotImplementedError

    @abstractmethod
    async def delete(self, chunk_ids: list[UUID], *, filters: VectorFilter) -> None:
        raise NotImplementedError

    @abstractmethod
    async def delete_document(self, document_id: UUID, *, filters: VectorFilter) -> None:
        raise NotImplementedError

    @abstractmethod
    async def health_check(self) -> bool:
        raise NotImplementedError
