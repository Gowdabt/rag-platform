from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, Query
from pydantic import AliasChoices, BaseModel, ConfigDict, EmailStr, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.adapters.db.rls import apply_rls
from app.adapters.db.session import session_factory
from app.api.deps import get_context, get_settings, require_any_permission, require_permission
from app.application.identity import IdentityService
from app.config.models import PlatformSettings
from app.core.context import RequestContext


class InviteIn(BaseModel):
    email: EmailStr
    password: str = Field(min_length=10)
    role: str = "Member"


class InvitationIn(BaseModel):
    email: EmailStr
    name: str | None = None
    role_ids: list[UUID] | None = None
    role_names: list[str] | None = None


class UserPatchIn(BaseModel):
    status: str | None = None
    role_ids: list[UUID] | None = None


class RoleIn(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    name: str
    description: str | None = None
    permission_codes: list[str] = Field(
        default_factory=list,
        validation_alias=AliasChoices("permission_codes", "permissions"),
    )


class RolePatchIn(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    name: str | None = None
    description: str | None = None
    permission_codes: list[str] | None = Field(
        default=None,
        validation_alias=AliasChoices("permission_codes", "permissions"),
    )


class WorkspaceIn(BaseModel):
    name: str


class TeamIn(BaseModel):
    name: str
    workspace_id: UUID | None = None


class TeamMemberIn(BaseModel):
    user_id: UUID


router = APIRouter(prefix="/api/v1", tags=["identity"])


async def _db(ctx: RequestContext = Depends(get_context)) -> AsyncSession:
    factory = session_factory()
    async with factory() as session:
        async with session.begin():
            await apply_rls(session, ctx)
            yield session


@router.get("/tenants")
async def list_tenants(
    ctx: RequestContext = Depends(get_context),
    settings: PlatformSettings = Depends(get_settings),
    session: AsyncSession = Depends(_db),
    limit: int = Query(100, ge=1, le=100),
    offset: int = Query(0, ge=0),
):
    return await IdentityService(session, settings).list_tenants(ctx, limit=limit, offset=offset)


@router.get("/users")
async def list_users(
    ctx: RequestContext = Depends(require_any_permission("user:manage", "users.view")),
    settings: PlatformSettings = Depends(get_settings),
    session: AsyncSession = Depends(_db),
    limit: int = Query(100, ge=1, le=100),
    offset: int = Query(0, ge=0),
):
    return await IdentityService(session, settings).list_users(ctx, limit=limit, offset=offset)


@router.post("/users")
async def invite(body: InviteIn, ctx: RequestContext = Depends(require_permission("user:manage")), settings: PlatformSettings = Depends(get_settings), session: AsyncSession = Depends(_db)):
    return await IdentityService(session, settings).invite_user(
        ctx, email=str(body.email), password=body.password, role_name=body.role
    )


@router.post("/users/invitations")
async def create_invitation(
    body: InvitationIn,
    ctx: RequestContext = Depends(require_any_permission("users.create", "user:manage")),
    settings: PlatformSettings = Depends(get_settings),
    session: AsyncSession = Depends(_db),
):
    return await IdentityService(session, settings).create_invitation(
        ctx,
        email=str(body.email),
        name=body.name,
        role_ids=body.role_ids,
        role_names=body.role_names,
    )


@router.patch("/users/{user_id}")
async def patch_user(
    user_id: UUID,
    body: UserPatchIn,
    ctx: RequestContext = Depends(require_any_permission("users.update", "users.disable", "roles.assign", "user:manage")),
    settings: PlatformSettings = Depends(get_settings),
    session: AsyncSession = Depends(_db),
):
    return await IdentityService(session, settings).update_user(
        ctx, user_id, status=body.status, role_ids=body.role_ids
    )


@router.post("/users/{user_id}/revoke-sessions")
async def revoke_sessions(
    user_id: UUID,
    ctx: RequestContext = Depends(require_any_permission("users.update", "users.disable", "user:manage")),
    settings: PlatformSettings = Depends(get_settings),
    session: AsyncSession = Depends(_db),
):
    return await IdentityService(session, settings).revoke_sessions(ctx, user_id)


@router.get("/permissions")
async def list_permissions(
    ctx: RequestContext = Depends(require_any_permission("roles.view", "user:manage")),
    settings: PlatformSettings = Depends(get_settings),
    session: AsyncSession = Depends(_db),
):
    return await IdentityService(session, settings).list_permissions(ctx)


@router.get("/workspaces")
async def list_workspaces(
    ctx: RequestContext = Depends(get_context),
    settings: PlatformSettings = Depends(get_settings),
    session: AsyncSession = Depends(_db),
    limit: int = Query(100, ge=1, le=100),
    offset: int = Query(0, ge=0),
):
    return await IdentityService(session, settings).list_workspaces(ctx, limit=limit, offset=offset)


@router.post("/workspaces")
async def create_workspace(body: WorkspaceIn, ctx: RequestContext = Depends(require_permission("workspace:manage")), settings: PlatformSettings = Depends(get_settings), session: AsyncSession = Depends(_db)):
    return await IdentityService(session, settings).create_workspace(ctx, name=body.name)


@router.get("/roles")
async def list_roles(
    ctx: RequestContext = Depends(get_context),
    settings: PlatformSettings = Depends(get_settings),
    session: AsyncSession = Depends(_db),
    limit: int = Query(100, ge=1, le=100),
    offset: int = Query(0, ge=0),
):
    return await IdentityService(session, settings).list_roles(ctx, limit=limit, offset=offset)


@router.post("/roles")
async def create_role(
    body: RoleIn,
    ctx: RequestContext = Depends(require_any_permission("roles.create", "user:manage")),
    settings: PlatformSettings = Depends(get_settings),
    session: AsyncSession = Depends(_db),
):
    return await IdentityService(session, settings).create_role(
        ctx, name=body.name, description=body.description, permission_codes=body.permission_codes
    )


@router.put("/roles/{role_id}")
@router.patch("/roles/{role_id}")
async def patch_role(
    role_id: UUID,
    body: RolePatchIn,
    ctx: RequestContext = Depends(require_any_permission("roles.update", "user:manage")),
    settings: PlatformSettings = Depends(get_settings),
    session: AsyncSession = Depends(_db),
):
    return await IdentityService(session, settings).update_role(
        ctx,
        role_id,
        name=body.name,
        description=body.description,
        permission_codes=body.permission_codes,
    )


@router.delete("/roles/{role_id}")
async def delete_role(
    role_id: UUID,
    ctx: RequestContext = Depends(require_any_permission("roles.delete", "user:manage")),
    settings: PlatformSettings = Depends(get_settings),
    session: AsyncSession = Depends(_db),
):
    return await IdentityService(session, settings).delete_role(ctx, role_id)


@router.get("/teams")
async def list_teams(
    ctx: RequestContext = Depends(get_context),
    settings: PlatformSettings = Depends(get_settings),
    session: AsyncSession = Depends(_db),
    limit: int = Query(100, ge=1, le=100),
    offset: int = Query(0, ge=0),
):
    return await IdentityService(session, settings).list_teams(ctx, limit=limit, offset=offset)


@router.post("/teams")
async def create_team(body: TeamIn, ctx: RequestContext = Depends(require_permission("team:manage")), settings: PlatformSettings = Depends(get_settings), session: AsyncSession = Depends(_db)):
    return await IdentityService(session, settings).create_team(ctx, name=body.name, workspace_id=body.workspace_id)


@router.post("/teams/{team_id}/members")
async def add_member(team_id: UUID, body: TeamMemberIn, ctx: RequestContext = Depends(require_permission("team:manage")), settings: PlatformSettings = Depends(get_settings), session: AsyncSession = Depends(_db)):
    return await IdentityService(session, settings).add_team_member(ctx, team_id=team_id, user_id=body.user_id)
