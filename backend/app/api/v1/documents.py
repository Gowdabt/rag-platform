from __future__ import annotations

import json
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, Query, UploadFile
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.adapters.db.models import IngestionJob
from app.adapters.db.rls import apply_rls
from app.adapters.db.session import session_factory
from app.api.deps import get_context, get_tenant_settings, require_permission
from app.application.ingestion import IngestionService
from app.config.models import PlatformSettings
from app.core.context import RequestContext
from app.core.errors import ValidationFailedError

router = APIRouter(prefix="/api/v1", tags=["documents"])


class DocumentAclIn(BaseModel):
    allowed_users: list[UUID] | None = None
    emails: list[str] | None = None
    allowed_roles: list[str] | None = None
    allowed_groups: list[str] | None = None
    denied_users: list[UUID] | None = None
    denied_emails: list[str] | None = None
    denied_roles: list[str] | None = None
    denied_groups: list[str] | None = None
    visibility: Literal["private", "tenant"] | None = None


def _parse_allowed_roles_form(raw: str | None) -> list[str] | None:
    if raw is None:
        return None
    text = raw.strip()
    if not text:
        return []
    if text.startswith("["):
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError as exc:
            raise ValidationFailedError("allowed_roles must be a JSON array or comma-separated roles") from exc
        if not isinstance(parsed, list):
            raise ValidationFailedError("allowed_roles must be a JSON array or comma-separated roles")
        return [str(item) for item in parsed]
    return [part.strip() for part in text.split(",") if part.strip()]


async def _db(ctx: RequestContext = Depends(get_context)) -> AsyncSession:
    factory = session_factory()
    async with factory() as session:
        async with session.begin():
            await apply_rls(session, ctx)
            yield session


@router.post("/documents")
async def upload_document(
    background: BackgroundTasks,
    file: UploadFile = File(...),
    workspace_id: UUID | None = Form(default=None),
    visibility: Literal["private", "tenant"] | None = Form(default=None),
    allowed_roles: str | None = Form(default=None),
    ctx: RequestContext = Depends(require_permission("document:write")),
    settings: PlatformSettings = Depends(get_tenant_settings),
    session: AsyncSession = Depends(_db),
):
    content = await file.read()
    service = IngestionService(session, settings, ctx)
    result = await service.upload(
        filename=file.filename or "upload.bin",
        content=content,
        mime_type=file.content_type or "application/octet-stream",
        workspace_id=workspace_id,
        visibility=visibility,
        allowed_roles=_parse_allowed_roles_form(allowed_roles),
    )
    # BackgroundTasks ran before this request's transaction committed, so the worker
    # never saw the job. Process in-process queues in the same session.
    if result.get("job_id") and result.get("status") == "queued":
        job_id = UUID(result["job_id"])
        if settings.queue.provider in {"asyncio", "taskiq_redis"}:
            await service.process_job(job_id)
            job = await session.get(IngestionJob, job_id)
            if job:
                result["status"] = job.status
                if job.error:
                    result["error"] = job.error
        else:
            from app.application.jobs import run_ingestion_job

            background.add_task(run_ingestion_job, job_id, settings, ctx)
    return result


@router.get("/documents")
async def list_documents(
    ctx: RequestContext = Depends(require_permission("document:read")),
    settings: PlatformSettings = Depends(get_tenant_settings),
    session: AsyncSession = Depends(_db),
    limit: int = Query(100, ge=1, le=100),
    offset: int = Query(0, ge=0),
):
    return await IngestionService(session, settings, ctx).list_documents(limit=limit, offset=offset)


@router.get("/documents/{document_id}/versions")
async def document_versions(
    document_id: UUID,
    ctx: RequestContext = Depends(require_permission("document:read")),
    settings: PlatformSettings = Depends(get_tenant_settings),
    session: AsyncSession = Depends(_db),
):
    return await IngestionService(session, settings, ctx).list_versions(document_id)


@router.post("/documents/{document_id}/acl")
async def update_document_acl(
    document_id: UUID,
    body: DocumentAclIn,
    ctx: RequestContext = Depends(require_permission("document:read")),
    settings: PlatformSettings = Depends(get_tenant_settings),
    session: AsyncSession = Depends(_db),
):
    return await IngestionService(session, settings, ctx).update_document_acl(
        document_id, body.model_dump(exclude_unset=True)
    )
