from __future__ import annotations

from uuid import UUID

import structlog

from app.adapters.db.models import DataSource, IngestionJob, Tenant, User
from app.adapters.db.rls import apply_rls
from app.adapters.db.session import session_factory
from app.application.ingestion import IngestionService
from app.config.models import PlatformSettings
from app.core.context import RequestContext
from app.core.errors import ForbiddenError, UnauthenticatedError

log = structlog.get_logger(__name__)


async def run_ingestion_job(job_id: UUID, settings: PlatformSettings, ctx: RequestContext) -> None:
    """Re-hydrate live tenant/user/source state. Never trust a stale captured permission set."""
    factory = session_factory()
    async with factory() as session:
        async with session.begin():
            await apply_rls(session, ctx)
            job = await session.get(IngestionJob, job_id)
            if job is None:
                return
            if ctx.tenant_id is None or job.tenant_id != ctx.tenant_id:
                if job.tenant_id:
                    job.status = "failed"
                    job.error = "Job tenant mismatch"
                return
            tenant = await session.get(Tenant, job.tenant_id)
            if tenant is None or tenant.status != "active":
                job.status = "failed"
                job.error = "Tenant is not active"
                return
            if ctx.user_id is None:
                job.status = "failed"
                job.error = "Job owner is required"
                return
            user = await session.get(User, ctx.user_id)
            if user is None or user.status != "active":
                job.status = "failed"
                job.error = "Owning user is not active"
                return
            if job.source_id:
                source = await session.get(DataSource, job.source_id)
                if source is None or source.tenant_id != job.tenant_id:
                    job.status = "failed"
                    job.error = "Source missing"
                    return
            from app.application.identity import IdentityService

            try:
                live_ctx = await IdentityService(session, settings).hydrate_context(
                    RequestContext(
                        request_id=ctx.request_id,
                        tenant_id=job.tenant_id,
                        user_id=ctx.user_id,
                        workspace_id=ctx.workspace_id,
                    )
                )
            except (UnauthenticatedError, ForbiddenError):
                job.status = "failed"
                job.error = "Job authorization failed"
                return
            await apply_rls(session, live_ctx)
            try:
                await IngestionService(session, settings, live_ctx).process_job(job_id)
            except Exception:
                log.exception("ingestion_job_failed", job_id=str(job_id))
                return
