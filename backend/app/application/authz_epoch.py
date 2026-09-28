from __future__ import annotations

from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.adapters.db.models import Tenant, User
from app.core.cache import cache


async def load_authz_epoch(
    session: AsyncSession,
    tenant_id: UUID | str | None,
    user_id: UUID | str | None = None,
) -> int:
    """Authorization version from PostgreSQL — visible to every process."""
    tenant_epoch = 0
    user_epoch = 0
    if tenant_id:
        tenant_epoch = int(
            await session.scalar(select(Tenant.authz_epoch).where(Tenant.id == tenant_id)) or 0
        )
    if user_id:
        user_epoch = int(await session.scalar(select(User.authz_epoch).where(User.id == user_id)) or 0)
    return tenant_epoch + user_epoch


async def persist_authz_bump(
    session: AsyncSession,
    tenant_id: UUID | str,
    user_id: UUID | str | None = None,
) -> int:
    """Bump the DB epoch then drop this process's matching cache entries."""
    if user_id:
        await session.execute(update(User).where(User.id == user_id).values(authz_epoch=User.authz_epoch + 1))
    else:
        await session.execute(
            update(Tenant).where(Tenant.id == tenant_id).values(authz_epoch=Tenant.authz_epoch + 1)
        )
    cache.bump(tenant_id, user_id)
    return await load_authz_epoch(session, tenant_id, user_id)
