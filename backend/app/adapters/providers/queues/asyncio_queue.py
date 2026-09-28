from __future__ import annotations

from typing import Any
from uuid import UUID

from app.core.context import RequestContext
from app.domain.ports.queue import JobQueue
from app.domain.registry import register
from app.domain.types import JobHandle

_handler = None


def set_job_handler(handler) -> None:
    global _handler
    _handler = handler


@register("queue", "asyncio")
@register("queue", "taskiq_redis")
class AsyncioJobQueue(JobQueue):
    """In-process asyncio jobs. Redis/Taskiq can replace this later without API changes."""

    def __init__(self, ctx: RequestContext):
        super().__init__(ctx)

    async def enqueue(
        self,
        job_type: str,
        payload: dict[str, Any],
        *,
        job_id: UUID,
        idempotency_key: str,
    ) -> JobHandle:
        return JobHandle(job_id=job_id, queue_message_id=str(job_id))

    async def cancel(self, job_id: UUID) -> None:
        return None
