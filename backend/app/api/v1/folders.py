from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, Query
from pydantic import AliasChoices, BaseModel, ConfigDict, Field, model_validator
from sqlalchemy.ext.asyncio import AsyncSession

from app.adapters.db.rls import apply_rls
from app.adapters.db.session import session_factory
from app.api.deps import get_context
from app.application.folders import FolderService
from app.core.context import RequestContext


class FolderIn(BaseModel):
    name: str
    parent_id: UUID | None = None
    workspace_id: UUID | None = None


class FolderPatchIn(BaseModel):
    name: str | None = None
    parent_id: UUID | None = None


class FolderShareIn(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    subject_type: str = Field(validation_alias=AliasChoices("subject_type", "type"))
    email: str | None = None
    user_id: UUID | None = None
    role_id: UUID | None = None
    role_name: str | None = None
    actions: list[str] = Field(default_factory=list)
    deny: bool = False
    permissions: dict[str, bool] | list[str] | None = None

    @model_validator(mode="after")
    def actions_from_permissions(self) -> FolderShareIn:
        if self.actions:
            return self
        perms = self.permissions
        if isinstance(perms, list):
            object.__setattr__(self, "actions", [str(item) for item in perms])
        elif isinstance(perms, dict):
            object.__setattr__(self, "actions", [key for key, enabled in perms.items() if enabled])
        return self


router = APIRouter(prefix="/api/v1", tags=["folders"])


async def _db(ctx: RequestContext = Depends(get_context)) -> AsyncSession:
    factory = session_factory()
    async with factory() as session:
        async with session.begin():
            await apply_rls(session, ctx)
            yield session


@router.get("/folders")
async def list_folders(
    ctx: RequestContext = Depends(get_context),
    session: AsyncSession = Depends(_db),
    limit: int = Query(100, ge=1, le=100),
    offset: int = Query(0, ge=0),
):
    return await FolderService(session, ctx).list_folders(limit=limit, offset=offset)


@router.post("/folders")
async def create_folder(
    body: FolderIn, ctx: RequestContext = Depends(get_context), session: AsyncSession = Depends(_db)
):
    return await FolderService(session, ctx).create_folder(
        name=body.name, parent_id=body.parent_id, workspace_id=body.workspace_id
    )


@router.get("/folders/{folder_id}")
async def get_folder(
    folder_id: UUID, ctx: RequestContext = Depends(get_context), session: AsyncSession = Depends(_db)
):
    return await FolderService(session, ctx).get_folder(folder_id)


@router.patch("/folders/{folder_id}")
async def patch_folder(
    folder_id: UUID,
    body: FolderPatchIn,
    ctx: RequestContext = Depends(get_context),
    session: AsyncSession = Depends(_db),
):
    return await FolderService(session, ctx).update_folder(
        folder_id, name=body.name, parent_id=body.parent_id
    )


@router.delete("/folders/{folder_id}")
async def delete_folder(
    folder_id: UUID, ctx: RequestContext = Depends(get_context), session: AsyncSession = Depends(_db)
):
    return await FolderService(session, ctx).delete_folder(folder_id)


@router.get("/folders/{folder_id}/share")
async def list_shares(
    folder_id: UUID, ctx: RequestContext = Depends(get_context), session: AsyncSession = Depends(_db)
):
    return await FolderService(session, ctx).list_shares(folder_id)


@router.post("/folders/{folder_id}/share")
async def share_folder(
    folder_id: UUID,
    body: FolderShareIn,
    ctx: RequestContext = Depends(get_context),
    session: AsyncSession = Depends(_db),
):
    return await FolderService(session, ctx).share_folder(
        folder_id,
        subject_type=body.subject_type,
        actions=body.actions,
        deny=body.deny,
        email=body.email,
        user_id=body.user_id,
        role_id=body.role_id,
        role_name=body.role_name,
    )


@router.delete("/folders/{folder_id}/grants/{grant_id}")
@router.delete("/folders/{folder_id}/share/{grant_id}")
async def delete_grant(
    folder_id: UUID,
    grant_id: UUID,
    ctx: RequestContext = Depends(get_context),
    session: AsyncSession = Depends(_db),
):
    return await FolderService(session, ctx).delete_grant(folder_id, grant_id)
