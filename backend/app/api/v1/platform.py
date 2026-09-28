from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, EmailStr
from sqlalchemy.ext.asyncio import AsyncSession

from app.adapters.db.rls import apply_rls
from app.adapters.db.session import session_factory
from app.api.deps import get_settings, require_super_admin
from app.application.identity import IdentityService
from app.application.tenant_ai import catalog_llm_entries
from app.config.models import PlatformSettings
from app.core.context import RequestContext


class PlatformTenantIn(BaseModel):
    name: str
    slug: str
    admin_name: str
    admin_email: EmailStr
    status: str | None = None


class PlatformTenantPatch(BaseModel):
    name: str | None = None
    status: str | None = None


router = APIRouter(prefix="/api/v1/platform", tags=["platform"])


async def _db(ctx: RequestContext = Depends(require_super_admin)) -> AsyncSession:
    factory = session_factory()
    async with factory() as session:
        async with session.begin():
            await apply_rls(session, ctx)
            yield session


@router.get("/tenants")
async def list_tenants(
    ctx: RequestContext = Depends(require_super_admin),
    settings: PlatformSettings = Depends(get_settings),
    session: AsyncSession = Depends(_db),
    limit: int = Query(100, ge=1, le=100),
    offset: int = Query(0, ge=0),
):
    return await IdentityService(session, settings).list_platform_tenants(ctx, limit=limit, offset=offset)


@router.post("/tenants")
async def create_tenant(
    body: PlatformTenantIn,
    ctx: RequestContext = Depends(require_super_admin),
    settings: PlatformSettings = Depends(get_settings),
    session: AsyncSession = Depends(_db),
):
    return await IdentityService(session, settings).create_platform_tenant(
        ctx,
        name=body.name,
        slug=body.slug,
        admin_name=body.admin_name,
        admin_email=str(body.admin_email),
        status=body.status,
    )


@router.patch("/tenants/{tenant_id}")
async def patch_tenant(
    tenant_id: UUID,
    body: PlatformTenantPatch,
    ctx: RequestContext = Depends(require_super_admin),
    settings: PlatformSettings = Depends(get_settings),
    session: AsyncSession = Depends(_db),
):
    return await IdentityService(session, settings).patch_platform_tenant(
        ctx, tenant_id, name=body.name, status=body.status
    )


@router.get("/ai-catalog")
async def ai_catalog(
    ctx: RequestContext = Depends(require_super_admin),
    settings: PlatformSettings = Depends(get_settings),
):
    return {"llm": catalog_llm_entries(settings)}


@router.get("/audit-logs")
async def platform_audit_logs(
    ctx: RequestContext = Depends(require_super_admin),
    settings: PlatformSettings = Depends(get_settings),
    session: AsyncSession = Depends(_db),
    limit: int = Query(100, ge=1, le=200),
    offset: int = Query(0, ge=0),
):
    return await IdentityService(session, settings).list_platform_audit_logs(
        ctx, limit=limit, offset=offset
    )
