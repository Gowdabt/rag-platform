from __future__ import annotations

from abc import ABC, abstractmethod
from uuid import UUID

from app.core.context import RequestContext
from app.domain.types import MemoryRecord


class MemoryStore(ABC):
    def __init__(self, ctx: RequestContext):
        self.ctx = ctx

    @abstractmethod
    async def store(self, record: MemoryRecord) -> MemoryRecord:
        raise NotImplementedError

    @abstractmethod
    async def retrieve(self, user_id: UUID, *, limit: int = 20) -> list[MemoryRecord]:
        raise NotImplementedError

    @abstractmethod
    async def delete(self, memory_id: UUID) -> None:
        raise NotImplementedError
