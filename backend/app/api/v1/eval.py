from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.adapters.db.rls import apply_rls
from app.adapters.db.session import session_factory
from app.api.deps import get_context, get_tenant_settings, require_permission
from app.application.eval import EvalService
from app.config.models import PlatformSettings
from app.core.context import RequestContext

router = APIRouter(prefix="/api/v1/eval", tags=["eval"])


class DatasetIn(BaseModel):
    name: str
    description: str | None = None


class ItemIn(BaseModel):
    question: str
    expected_answer: str | None = None
    expected_sources: list[str] | dict | None = None


class RunIn(BaseModel):
    workspace_id: UUID | None = None


async def _db(ctx: RequestContext = Depends(get_context)) -> AsyncSession:
    factory = session_factory()
    async with factory() as session:
        async with session.begin():
            await apply_rls(session, ctx)
            yield session


@router.post("/datasets")
async def create_dataset(
    body: DatasetIn,
    ctx: RequestContext = Depends(require_permission("config:write")),
    settings: PlatformSettings = Depends(get_tenant_settings),
    session: AsyncSession = Depends(_db),
):
    return await EvalService(session, settings, ctx).create_dataset(
        name=body.name, description=body.description
    )


@router.get("/datasets")
async def list_datasets(
    ctx: RequestContext = Depends(require_permission("config:read")),
    settings: PlatformSettings = Depends(get_tenant_settings),
    session: AsyncSession = Depends(_db),
    limit: int = Query(100, ge=1, le=100),
    offset: int = Query(0, ge=0),
):
    return await EvalService(session, settings, ctx).list_datasets(limit=limit, offset=offset)


@router.post("/datasets/{dataset_id}/items")
async def add_item(
    dataset_id: UUID,
    body: ItemIn,
    ctx: RequestContext = Depends(require_permission("config:write")),
    settings: PlatformSettings = Depends(get_tenant_settings),
    session: AsyncSession = Depends(_db),
):
    return await EvalService(session, settings, ctx).add_item(
        dataset_id,
        question=body.question,
        expected_answer=body.expected_answer,
        expected_sources=body.expected_sources,
    )


@router.get("/datasets/{dataset_id}/items")
async def list_items(
    dataset_id: UUID,
    ctx: RequestContext = Depends(require_permission("config:read")),
    settings: PlatformSettings = Depends(get_tenant_settings),
    session: AsyncSession = Depends(_db),
):
    return await EvalService(session, settings, ctx).list_items(dataset_id)


@router.post("/datasets/{dataset_id}/runs")
async def run_dataset(
    dataset_id: UUID,
    body: RunIn | None = None,
    ctx: RequestContext = Depends(require_permission("config:write")),
    settings: PlatformSettings = Depends(get_tenant_settings),
    session: AsyncSession = Depends(_db),
):
    return await EvalService(session, settings, ctx).run_dataset(
        dataset_id, workspace_id=body.workspace_id if body else None
    )


@router.get("/runs/{run_id}")
async def get_run(
    run_id: UUID,
    ctx: RequestContext = Depends(require_permission("config:read")),
    settings: PlatformSettings = Depends(get_tenant_settings),
    session: AsyncSession = Depends(_db),
):
    return await EvalService(session, settings, ctx).get_run(run_id)
