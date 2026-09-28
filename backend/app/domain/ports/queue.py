from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any
from uuid import UUID

from app.core.context import RequestContext
from app.domain.types import JobHandle


class JobQueue(ABC):
    def __init__(self, ctx: RequestContext):
        self.ctx = ctx

    @abstractmethod
    async def enqueue(
        self,
        job_type: str,
        payload: dict[str, Any],
        *,
        job_id: UUID,
        idempotency_key: str,
    ) -> JobHandle:
        raise NotImplementedError

    @abstractmethod
    async def cancel(self, job_id: UUID) -> None:
        raise NotImplementedError
