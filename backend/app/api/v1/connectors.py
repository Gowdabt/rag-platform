from __future__ import annotations

from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.adapters.db.rls import apply_rls
from app.adapters.db.session import session_factory
from app.api.deps import get_context, get_tenant_settings, require_permission
from app.application.connectors import ConnectorService, list_connector_catalog
from app.config.models import PlatformSettings
from app.core.context import RequestContext

router = APIRouter(prefix="/api/v1", tags=["connectors"])


class OauthAppIn(BaseModel):
    client_id: str = ""
    client_secret: str = ""


class OauthClientsIn(BaseModel):
    google: OauthAppIn | None = None
    microsoft: OauthAppIn | None = None
    dropbox: OauthAppIn | None = None


class OAuthStartIn(BaseModel):
    connector_type: str
    workspace_id: UUID | None = None
    source_id: UUID | None = None
    redirect_uri: str = "http://127.0.0.1:5173/sources"


class OAuthCallbackIn(BaseModel):
    code: str
    state: str


class CreateConnectorIn(BaseModel):
    connector_type: str
    workspace_id: UUID | None = None
    name: str | None = None
    connector_config: dict | None = None


class ResolveLocationIn(BaseModel):
    url: str


class SubscribeIn(BaseModel):
    location_id: str
    location_name: str
    include_subfolders: bool = True
    file_filters: list[str] | None = None
    schedule: str = "manual"


class PatchSubscriptionIn(BaseModel):
    status: str | None = None
    schedule: str | None = None
    include_subfolders: bool | None = None
    file_filters: list[str] | None = None
    allowed_users: list[UUID] | None = None
    emails: list[str] | None = None
    allowed_roles: list[str] | None = None
    allowed_groups: list[str] | None = None
    denied_users: list[UUID] | None = None
    denied_emails: list[str] | None = None
    denied_roles: list[str] | None = None
    denied_groups: list[str] | None = None
    visibility: Literal["private", "tenant"] | None = None


async def _db(ctx: RequestContext = Depends(get_context)) -> AsyncSession:
    factory = session_factory()
    async with factory() as session:
        async with session.begin():
            await apply_rls(session, ctx)
            yield session


@router.get("/connectors/catalog")
async def catalog(
    ctx: RequestContext = Depends(require_permission("document:read")),
    settings: PlatformSettings = Depends(get_tenant_settings),
    session: AsyncSession = Depends(_db),
):
    clients = await ConnectorService(session, settings, ctx).oauth_clients()
    return list_connector_catalog(clients)


@router.get("/connectors/oauth/clients")
async def get_oauth_clients(
    ctx: RequestContext = Depends(require_permission("source:manage")),
    settings: PlatformSettings = Depends(get_tenant_settings),
    session: AsyncSession = Depends(_db),
):
    return await ConnectorService(session, settings, ctx).oauth_status()


@router.put("/connectors/oauth/clients")
async def put_oauth_clients(
    body: OauthClientsIn,
    ctx: RequestContext = Depends(get_context),
    settings: PlatformSettings = Depends(get_tenant_settings),
    session: AsyncSession = Depends(_db),
):
    return await ConnectorService(session, settings, ctx).save_oauth_clients(
        body.model_dump(exclude_none=True)
    )


@router.get("/connectors/local-fs/browse")
async def browse_local_fs(
    path: str | None = None,
    ctx: RequestContext = Depends(require_permission("source:manage")),
    settings: PlatformSettings = Depends(get_tenant_settings),
    session: AsyncSession = Depends(_db),
):
    return await ConnectorService(session, settings, ctx).browse_local_host(path)


@router.get("/connectors")
async def list_connectors(
    ctx: RequestContext = Depends(get_context),
    settings: PlatformSettings = Depends(get_tenant_settings),
    session: AsyncSession = Depends(_db),
    limit: int = Query(100, ge=1, le=100),
    offset: int = Query(0, ge=0),
):
    return await ConnectorService(session, settings, ctx).list_sources(limit=limit, offset=offset)


@router.post("/connectors")
async def create_connector(
    body: CreateConnectorIn,
    ctx: RequestContext = Depends(require_permission("source:manage")),
    settings: PlatformSettings = Depends(get_tenant_settings),
    session: AsyncSession = Depends(_db),
):
    return await ConnectorService(session, settings, ctx).create_unauthenticated(
        connector_type=body.connector_type,
        workspace_id=body.workspace_id,
        name=body.name,
        connector_config=body.connector_config,
    )


@router.post("/connectors/oauth/start")
async def oauth_start(
    body: OAuthStartIn,
    ctx: RequestContext = Depends(require_permission("source:manage")),
    settings: PlatformSettings = Depends(get_tenant_settings),
    session: AsyncSession = Depends(_db),
):
    return await ConnectorService(session, settings, ctx).start_oauth(
        connector_type=body.connector_type,
        workspace_id=body.workspace_id,
        source_id=body.source_id,
        redirect_uri=body.redirect_uri,
    )


@router.post("/connectors/oauth/callback")
async def oauth_callback(
    body: OAuthCallbackIn,
    ctx: RequestContext = Depends(require_permission("source:manage")),
    settings: PlatformSettings = Depends(get_tenant_settings),
    session: AsyncSession = Depends(_db),
):
    return await ConnectorService(session, settings, ctx).complete_oauth(code=body.code, state=body.state)


@router.get("/connectors/{source_id}/health")
async def connector_health(
    source_id: UUID,
    ctx: RequestContext = Depends(require_permission("source:manage")),
    settings: PlatformSettings = Depends(get_tenant_settings),
    session: AsyncSession = Depends(_db),
):
    return await ConnectorService(session, settings, ctx).health(source_id)


@router.delete("/connectors/{source_id}")
async def disconnect(
    source_id: UUID,
    ctx: RequestContext = Depends(require_permission("source:manage")),
    settings: PlatformSettings = Depends(get_tenant_settings),
    session: AsyncSession = Depends(_db),
):
    return await ConnectorService(session, settings, ctx).disconnect(source_id)


@router.get("/connectors/{source_id}/locations")
async def locations(
    source_id: UUID,
    parent_id: str | None = None,
    ctx: RequestContext = Depends(require_permission("source:manage")),
    settings: PlatformSettings = Depends(get_tenant_settings),
    session: AsyncSession = Depends(_db),
):
    return await ConnectorService(session, settings, ctx).locations(source_id, parent_id)


@router.get("/connectors/{source_id}/locations/{location_id}/children")
async def children(
    source_id: UUID,
    location_id: str,
    ctx: RequestContext = Depends(require_permission("source:manage")),
    settings: PlatformSettings = Depends(get_tenant_settings),
    session: AsyncSession = Depends(_db),
):
    return await ConnectorService(session, settings, ctx).browse(source_id, location_id)


@router.post("/connectors/{source_id}/resolve-location")
async def resolve_location(
    source_id: UUID,
    body: ResolveLocationIn,
    ctx: RequestContext = Depends(require_permission("source:manage")),
    settings: PlatformSettings = Depends(get_tenant_settings),
    session: AsyncSession = Depends(_db),
):
    return await ConnectorService(session, settings, ctx).resolve_location(source_id, body.url)


@router.post("/connectors/{source_id}/subscriptions")
async def subscribe(
    source_id: UUID,
    body: SubscribeIn,
    ctx: RequestContext = Depends(require_permission("source:manage")),
    settings: PlatformSettings = Depends(get_tenant_settings),
    session: AsyncSession = Depends(_db),
):
    service = ConnectorService(session, settings, ctx)
    sub = await service.subscribe(
        source_id,
        location_id=body.location_id,
        location_name=body.location_name,
        include_subfolders=body.include_subfolders,
        file_filters=body.file_filters,
        schedule=body.schedule,
    )
    run = await service.sync(UUID(sub["id"]), trigger="initial")
    return {"subscription": sub, "sync": run}


@router.get("/subscriptions")
async def list_subscriptions(
    ctx: RequestContext = Depends(get_context),
    settings: PlatformSettings = Depends(get_tenant_settings),
    session: AsyncSession = Depends(_db),
    limit: int = Query(100, ge=1, le=100),
    offset: int = Query(0, ge=0),
):
    return await ConnectorService(session, settings, ctx).list_subscriptions(limit=limit, offset=offset)


@router.patch("/subscriptions/{subscription_id}")
async def patch_subscription(
    subscription_id: UUID,
    body: PatchSubscriptionIn,
    ctx: RequestContext = Depends(require_permission("source:manage")),
    settings: PlatformSettings = Depends(get_tenant_settings),
    session: AsyncSession = Depends(_db),
):
    return await ConnectorService(session, settings, ctx).patch_subscription(
        subscription_id, **body.model_dump(exclude_unset=True)
    )


@router.delete("/subscriptions/{subscription_id}")
async def delete_subscription(
    subscription_id: UUID,
    ctx: RequestContext = Depends(require_permission("source:manage")),
    settings: PlatformSettings = Depends(get_tenant_settings),
    session: AsyncSession = Depends(_db),
):
    await ConnectorService(session, settings, ctx).delete_subscription(subscription_id)
    return {"status": "disconnected"}


@router.post("/subscriptions/{subscription_id}/sync")
async def sync_now(
    subscription_id: UUID,
    ctx: RequestContext = Depends(require_permission("source:manage")),
    settings: PlatformSettings = Depends(get_tenant_settings),
    session: AsyncSession = Depends(_db),
):
    return await ConnectorService(session, settings, ctx).sync(subscription_id, trigger="manual")


@router.get("/subscriptions/{subscription_id}/sync-history")
async def sync_history(
    subscription_id: UUID,
    ctx: RequestContext = Depends(require_permission("source:manage")),
    settings: PlatformSettings = Depends(get_tenant_settings),
    session: AsyncSession = Depends(_db),
):
    return await ConnectorService(session, settings, ctx).sync_history(subscription_id)
