from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.adapters.db.models import UserMemory as UserMemoryRow
from app.core.context import RequestContext
from app.domain.ports.memory import MemoryStore
from app.domain.registry import register
from app.domain.types import MemoryRecord


@register("memory", "postgres")
class PostgresMemoryStore(MemoryStore):
    def __init__(self, ctx: RequestContext, session: AsyncSession | None = None):
        super().__init__(ctx)
        self.session = session

    async def store(self, record: MemoryRecord) -> MemoryRecord:
        assert self.session is not None
        row = UserMemoryRow(
            tenant_id=record.tenant_id,
            user_id=record.user_id,
            content=record.content,
            extra_metadata=record.metadata,
        )
        self.session.add(row)
        await self.session.flush()
        record.memory_id = row.id
        return record

    async def retrieve(self, user_id: UUID, *, limit: int = 20) -> list[MemoryRecord]:
        assert self.session is not None
        if self.ctx.tenant_id is None:
            return []
        rows = (
            await self.session.scalars(
                select(UserMemoryRow)
                .where(
                    UserMemoryRow.user_id == user_id,
                    UserMemoryRow.tenant_id == self.ctx.tenant_id,
                )
                .order_by(UserMemoryRow.created_at.desc())
                .limit(limit)
            )
        ).all()
        return [
            MemoryRecord(
                memory_id=r.id,
                user_id=r.user_id,
                tenant_id=r.tenant_id,
                content=r.content,
                metadata=r.extra_metadata or {},
            )
            for r in rows
        ]

    async def delete(self, memory_id: UUID) -> None:
        assert self.session is not None
        row = await self.session.get(UserMemoryRow, memory_id)
        if row is None:
            return
        if row.tenant_id != self.ctx.tenant_id:
            return
        if self.ctx.user_id is not None and row.user_id != self.ctx.user_id:
            return
        await self.session.delete(row)
