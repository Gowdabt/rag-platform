from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from uuid import uuid4

import structlog
from sqlalchemy import select

from app.adapters.db.models import DataSource, SourceSubscription, Tenant, TenantMembership, User
from app.adapters.db.rls import apply_rls
from app.adapters.db.session import session_factory
from app.application.connectors import ConnectorService
from app.application.identity import IdentityService
from app.config.models import PlatformSettings
from app.core.context import RequestContext
from app.core.errors import ForbiddenError, UnauthenticatedError

log = structlog.get_logger(__name__)


async def run_due_syncs(settings: PlatformSettings) -> int:
    factory = session_factory()
    ran = 0
    async with factory() as session:
        async with session.begin():
            tenant_ids = list(await session.scalars(select(Tenant.id)))
    for tenant_id in tenant_ids:
        async with factory() as session:
            async with session.begin():
                bootstrap = RequestContext(request_id=str(uuid4()), tenant_id=tenant_id)
                await apply_rls(session, bootstrap)
                tenant = await session.get(Tenant, tenant_id)
                if tenant is None or tenant.status != "active":
                    continue
                due = (
                    await session.scalars(
                        select(SourceSubscription).where(
                            SourceSubscription.tenant_id == tenant_id,
                            SourceSubscription.status == "active",
                            SourceSubscription.next_sync_at.is_not(None),
                            SourceSubscription.next_sync_at <= datetime.now(UTC),
                        )
                    )
                ).all()
                for sub in due:
                    if sub.tenant_id != tenant_id:
                        log.warning("scheduled_sync_skipped_tenant_mismatch", subscription_id=str(sub.id))
                        continue
                    source = await session.get(DataSource, sub.source_id)
                    if source is None or source.owner_user_id is None or source.tenant_id != tenant_id:
                        log.warning("scheduled_sync_skipped_no_owner", subscription_id=str(sub.id))
                        continue
                    owner = await session.get(User, source.owner_user_id)
                    if owner is None or owner.status != "active":
                        log.warning("scheduled_sync_skipped_owner_disabled", subscription_id=str(sub.id))
                        continue
                    membership = await session.scalar(
                        select(TenantMembership).where(
                            TenantMembership.tenant_id == tenant_id,
                            TenantMembership.user_id == source.owner_user_id,
                        )
                    )
                    if membership is None:
                        log.warning("scheduled_sync_skipped_no_membership", subscription_id=str(sub.id))
                        continue
                    bootstrap = RequestContext(
                        request_id=str(uuid4()),
                        tenant_id=tenant_id,
                        user_id=source.owner_user_id,
                        workspace_id=membership.default_workspace_id or source.workspace_id,
                    )
                    try:
                        ctx = await IdentityService(session, settings).hydrate_context(bootstrap)
                    except (UnauthenticatedError, ForbiddenError):
                        log.warning("scheduled_sync_skipped_authz", subscription_id=str(sub.id))
                        continue
                    await apply_rls(session, ctx)
                    service = ConnectorService(session, settings, ctx)
                    try:
                        await service.sync(sub.id, trigger="scheduled")
                        ran += 1
                    except Exception:
                        log.exception("scheduled_sync_failed", subscription_id=str(sub.id))
    return ran


async def scheduler_loop(settings: PlatformSettings, stop: asyncio.Event) -> None:
    while not stop.is_set():
        try:
            session_factory()
        except RuntimeError:
            pass
        else:
            try:
                await run_due_syncs(settings)
            except Exception:
                log.exception("scheduler_tick_failed")
        try:
            await asyncio.wait_for(stop.wait(), timeout=60)
        except TimeoutError:
            continue
