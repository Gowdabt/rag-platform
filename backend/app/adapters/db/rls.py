from __future__ import annotations

from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.context import RequestContext


async def apply_rls(session: AsyncSession, ctx: RequestContext | None = None) -> None:
    tenant = str(ctx.tenant_id) if ctx and ctx.tenant_id else ""
    user = str(ctx.user_id) if ctx and ctx.user_id else ""
    await session.execute(text("SELECT set_config('app.tenant_id', :tid, true)"), {"tid": tenant})
    await session.execute(text("SELECT set_config('app.user_id', :uid, true)"), {"uid": user})


async def apply_rls_ids(
    session: AsyncSession, *, tenant_id: UUID | None = None, user_id: UUID | None = None
) -> None:
    await session.execute(
        text("SELECT set_config('app.tenant_id', :tid, true)"),
        {"tid": str(tenant_id) if tenant_id else ""},
    )
    await session.execute(
        text("SELECT set_config('app.user_id', :uid, true)"),
        {"uid": str(user_id) if user_id else ""},
    )
