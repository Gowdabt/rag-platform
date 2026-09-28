from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.adapters.db.session import session_factory
from app.api.deps import get_context, get_settings
from app.application.identity import IdentityService
from app.config.models import PlatformSettings
from app.core.context import RequestContext
from app.core.errors import ForbiddenError
from app.core.flags import allow_public_signup


class SignupIn(BaseModel):
    email: EmailStr
    password: str = Field(min_length=10)
    tenant_name: str


class LoginIn(BaseModel):
    email: EmailStr
    password: str
    tenant_id: UUID | None = None
    tenant_slug: str | None = None


class RefreshIn(BaseModel):
    refresh_token: str


class SwitchIn(BaseModel):
    tenant_id: UUID


class AcceptInviteIn(BaseModel):
    token: str
    password: str = Field(min_length=10)


class ForgotPasswordIn(BaseModel):
    email: EmailStr
    tenant_slug: str


class ResetPasswordIn(BaseModel):
    token: str
    password: str = Field(min_length=10)


router = APIRouter(prefix="/api/v1/auth", tags=["auth"])


async def _raw_session() -> AsyncSession:
    factory = session_factory()
    async with factory() as session:
        async with session.begin():
            yield session


@router.get("/features")
async def features():
    return {"public_signup": allow_public_signup()}


@router.post("/signup")
async def signup(body: SignupIn, settings: PlatformSettings = Depends(get_settings), session: AsyncSession = Depends(_raw_session)):
    if not allow_public_signup():
        raise ForbiddenError("Public signup is disabled")
    return await IdentityService(session, settings).signup(
        email=str(body.email), password=body.password, tenant_name=body.tenant_name
    )


@router.post("/login")
async def login(
    body: LoginIn,
    request: Request,
    settings: PlatformSettings = Depends(get_settings),
    session: AsyncSession = Depends(_raw_session),
):
    return await IdentityService(session, settings).login(
        email=str(body.email),
        password=body.password,
        tenant_id=body.tenant_id,
        tenant_slug=body.tenant_slug,
        request_id=getattr(request.state, "request_id", None),
    )


@router.post("/refresh")
async def refresh(body: RefreshIn, settings: PlatformSettings = Depends(get_settings), session: AsyncSession = Depends(_raw_session)):
    return await IdentityService(session, settings).refresh(body.refresh_token)


@router.post("/logout")
async def logout(body: RefreshIn, settings: PlatformSettings = Depends(get_settings), session: AsyncSession = Depends(_raw_session)):
    await IdentityService(session, settings).logout(body.refresh_token)
    return {"ok": True}


@router.post("/switch-tenant")
async def switch_tenant(
    body: SwitchIn,
    ctx: RequestContext = Depends(get_context),
    settings: PlatformSettings = Depends(get_settings),
    session: AsyncSession = Depends(_raw_session),
):
    return await IdentityService(session, settings).switch_tenant(ctx, body.tenant_id)


@router.post("/accept-invite")
async def accept_invite(
    body: AcceptInviteIn,
    settings: PlatformSettings = Depends(get_settings),
    session: AsyncSession = Depends(_raw_session),
):
    return await IdentityService(session, settings).accept_invite(token=body.token, password=body.password)


@router.post("/forgot-password")
async def forgot_password(
    body: ForgotPasswordIn,
    settings: PlatformSettings = Depends(get_settings),
    session: AsyncSession = Depends(_raw_session),
):
    return await IdentityService(session, settings).forgot_password(
        email=str(body.email), tenant_slug=body.tenant_slug
    )


@router.post("/reset-password")
async def reset_password(
    body: ResetPasswordIn,
    settings: PlatformSettings = Depends(get_settings),
    session: AsyncSession = Depends(_raw_session),
):
    return await IdentityService(session, settings).reset_password(token=body.token, password=body.password)


@router.get("/me")
async def me(ctx: RequestContext = Depends(get_context), settings: PlatformSettings = Depends(get_settings)):
    factory = session_factory()
    async with factory() as session:
        async with session.begin():
            from app.adapters.db.rls import apply_rls

            await apply_rls(session, ctx)
            return await IdentityService(session, settings).me(ctx)
