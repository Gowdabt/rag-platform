from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import func
from sqlalchemy import select as sel
from sqlalchemy.ext.asyncio import AsyncSession

from app.adapters.db.models import AuditLog, ConfigOverlay, DataSource, Document, IngestionJob, UsageEvent
from app.adapters.db.rls import apply_rls
from app.adapters.db.session import session_factory
from app.api.deps import get_context, get_settings, get_tenant_settings, require_permission
from app.application.authz import can_manage_source, can_read_document
from app.config.merge import assert_overlay_allowed, deep_merge
from app.config.models import PlatformSettings
from app.config.secrets import is_secret_ref
from app.core.context import RequestContext
from app.core.errors import ForbiddenError, NotFoundError

router = APIRouter(prefix="/api/v1", tags=["admin"])


class ConfigIn(BaseModel):
    payload: dict


async def _db(ctx: RequestContext = Depends(get_context)) -> AsyncSession:
    factory = session_factory()
    async with factory() as session:
        async with session.begin():
            await apply_rls(session, ctx)
            yield session


def _is_sensitive_key(key: str) -> bool:
    low = key.lower()
    return any(x in low for x in ("secret", "password", "api_key")) or low.endswith("token") or low.endswith("_token")


def _redact(value):
    if is_secret_ref(value):
        return "***"
    if isinstance(value, dict):
        return {k: "***" if _is_sensitive_key(k) else _redact(v) for k, v in value.items()}
    return value


@router.get("/config")
async def get_config(
    ctx: RequestContext = Depends(require_permission("config:read")),
    settings: PlatformSettings = Depends(get_settings),
    session: AsyncSession = Depends(_db),
):
    overlay = await session.scalar(
        sel(ConfigOverlay).where(
            ConfigOverlay.tenant_id == ctx.tenant_id, ConfigOverlay.scope_type == "tenant"
        )
    )
    data = settings.model_dump()
    if overlay:
        from app.config.load import parse_settings

        data = parse_settings(deep_merge(data, overlay.payload)).model_dump()
    return _redact(data)


@router.put("/config")
async def put_config(
    body: ConfigIn,
    ctx: RequestContext = Depends(require_permission("config:write")),
    session: AsyncSession = Depends(_db),
):
    assert_overlay_allowed(body.payload, "tenant")
    overlay = await session.scalar(
        sel(ConfigOverlay).where(
            ConfigOverlay.tenant_id == ctx.tenant_id, ConfigOverlay.scope_type == "tenant"
        )
    )
    if overlay is None:
        overlay = ConfigOverlay(
            tenant_id=ctx.tenant_id,
            scope_type="tenant",
            scope_id=ctx.tenant_id,
            payload=body.payload,
            version=1,
        )
        session.add(overlay)
    else:
        overlay.payload = deep_merge(overlay.payload or {}, body.payload)
        overlay.version += 1
        from sqlalchemy.orm.attributes import flag_modified

        flag_modified(overlay, "payload")
    await session.flush()
    return {"ok": True, "version": overlay.version}


@router.get("/jobs")
async def jobs(
    ctx: RequestContext = Depends(require_permission("job:read")),
    session: AsyncSession = Depends(_db),
    limit: int = Query(100, ge=1, le=100),
    offset: int = Query(0, ge=0),
):
    rows = (
        await session.scalars(
            sel(IngestionJob)
            .where(IngestionJob.tenant_id == ctx.tenant_id)
            .order_by(IngestionJob.created_at.desc(), IngestionJob.id)
            .offset(offset)
            .limit(limit)
        )
    ).all()
    visible = []
    privileged = ctx.has("document:read_all") or ctx.has("source:admin")
    for job in rows:
        if privileged:
            visible.append(job)
            continue
        if job.document_id:
            document = await session.get(Document, job.document_id)
            if document and can_read_document(document.acl or {}, ctx):
                visible.append(job)
        elif job.source_id:
            source = await session.get(DataSource, job.source_id)
            if source and can_manage_source(source, ctx):
                visible.append(job)
    return [
        {
            "id": str(j.id),
            "status": j.status,
            "job_type": j.job_type,
            "error": j.error,
            "document_id": str(j.document_id) if j.document_id else None,
        }
        for j in visible
    ]


@router.post("/jobs/{job_id}/retry")
async def retry_job(
    job_id: UUID,
    ctx: RequestContext = Depends(get_context),
    settings: PlatformSettings = Depends(get_tenant_settings),
    session: AsyncSession = Depends(_db),
):
    from app.application.jobs import run_ingestion_job

    job = await session.get(IngestionJob, job_id)
    if job is None or job.tenant_id != ctx.tenant_id:
        raise NotFoundError("Job not found")
    privileged = ctx.has("document:read_all") or ctx.has("source:admin")
    if not privileged:
        if not ctx.has("document:write"):
            raise ForbiddenError("Missing permission to retry job")
        if job.document_id:
            document = await session.get(Document, job.document_id)
            if document is None or not can_read_document(document.acl or {}, ctx):
                raise NotFoundError("Job not found")
        elif job.source_id:
            source = await session.get(DataSource, job.source_id)
            if source is None or not can_manage_source(source, ctx):
                raise NotFoundError("Job not found")
        else:
            raise ForbiddenError("Missing permission to retry job")
    await run_ingestion_job(job_id, settings, ctx)
    return {"ok": True, "job_id": str(job_id)}


@router.get("/audit-logs")
async def audit_logs(
    ctx: RequestContext = Depends(require_permission("audit:read")),
    session: AsyncSession = Depends(_db),
    limit: int = Query(100, ge=1, le=200),
    offset: int = Query(0, ge=0),
):
    rows = (
        await session.scalars(
            sel(AuditLog)
            .where(AuditLog.tenant_id == ctx.tenant_id)
            .order_by(AuditLog.created_at.desc())
            .offset(offset)
            .limit(limit)
        )
    ).all()
    return [
        {
            "id": str(a.id),
            "action": a.action,
            "resource_type": a.resource_type,
            "resource_id": str(a.resource_id) if a.resource_id else None,
            "created_at": a.created_at.isoformat() if a.created_at else None,
        }
        for a in rows
    ]


@router.get("/usage")
async def usage(
    ctx: RequestContext = Depends(require_permission("audit:read")),
    session: AsyncSession = Depends(_db),
):
    rows = (await session.scalars(sel(UsageEvent).where(UsageEvent.tenant_id == ctx.tenant_id))).all()
    return {
        "events": len(rows),
        "input_tokens": sum(r.input_tokens for r in rows),
        "output_tokens": sum(r.output_tokens for r in rows),
        "estimated_cost_usd": sum(r.estimated_cost_usd or 0 for r in rows),
    }


@router.get("/admin/stats")
async def stats(
    ctx: RequestContext = Depends(require_permission("audit:read")),
    session: AsyncSession = Depends(_db),
):
    from app.application.connectors import _include_mocks

    docs_q = sel(func.count()).select_from(Document).where(
        Document.tenant_id == ctx.tenant_id,
        Document.external_status == "active",
    )
    if not _include_mocks():
        docs_q = docs_q.join(DataSource, DataSource.id == Document.source_id).where(
            ~DataSource.connector_type.startswith("mock_")
        )
    docs = await session.scalar(docs_q)
    jobs = await session.scalar(sel(func.count()).select_from(IngestionJob).where(IngestionJob.tenant_id == ctx.tenant_id))
    failed = await session.scalar(
        sel(func.count()).select_from(IngestionJob).where(
            IngestionJob.tenant_id == ctx.tenant_id, IngestionJob.status.in_(["failed", "dead_letter"])
        )
    )
    return {"documents": docs or 0, "jobs": jobs or 0, "failed_jobs": failed or 0}


@router.post("/admin/reindex")
async def reindex(
    ctx: RequestContext = Depends(require_permission("document:write")),
    settings: PlatformSettings = Depends(get_tenant_settings),
    session: AsyncSession = Depends(_db),
):
    from app.application.ingestion import IngestionService

    return await IngestionService(session, settings, ctx).reembed_active()
