from __future__ import annotations

from collections.abc import Callable
from uuid import UUID, uuid4

from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.adapters.db.rls import apply_rls
from app.adapters.db.session import session_factory
from app.config.models import PlatformSettings
from app.core.context import RequestContext
from app.core.errors import ForbiddenError, UnauthenticatedError
from app.core.security import decode_jwt, resolve_jwt_secret


async def _audit_authz_denied(ctx: RequestContext, permission: str) -> None:
    try:
        from app.adapters.db.rls import apply_rls
        from app.application.audit import write_audit

        factory = session_factory()
        async with factory() as session:
            async with session.begin():
                await apply_rls(session, ctx)
                await write_audit(
                    session,
                    tenant_id=ctx.tenant_id,
                    actor_user_id=ctx.user_id,
                    action="authz.denied",
                    resource_type="permission",
                    metadata={"permission": permission},
                    request_id=ctx.request_id,
                )
    except Exception:
        return

_bearer = HTTPBearer(auto_error=False)


def get_settings(request: Request) -> PlatformSettings:
    return request.app.state.settings


def get_request_id(request: Request) -> str:
    return getattr(request.state, "request_id", str(uuid4()))


async def get_claims(
    creds: HTTPAuthorizationCredentials | None = Depends(_bearer),
    settings: PlatformSettings = Depends(get_settings),
) -> dict:
    if creds is None or creds.scheme.lower() != "bearer":
        raise UnauthenticatedError("Missing bearer token")
    secret = resolve_jwt_secret(settings.auth.jwt_secret)
    return decode_jwt(creds.credentials, secret, expected_type="access")


async def get_db(claims: dict = Depends(get_claims)) -> AsyncSession:
    factory = session_factory()
    tid = claims.get("tid")
    ctx = RequestContext(
        request_id="db",
        tenant_id=UUID(tid) if tid else None,
        user_id=UUID(claims["sub"]),
        is_super_admin=bool(claims.get("sa")),
    )
    async with factory() as session:
        async with session.begin():
            await apply_rls(session, ctx)
            yield session


async def get_db_optional_auth() -> AsyncSession:
    factory = session_factory()
    async with factory() as session:
        async with session.begin():
            yield session


def require_permission(*permissions: str) -> Callable:
    async def _dep(ctx: RequestContext = Depends(get_context)) -> RequestContext:
        for perm in permissions:
            if not ctx.has(perm):
                await _audit_authz_denied(ctx, perm)
                raise ForbiddenError(f"Missing permission {perm}")
        return ctx

    return _dep


def require_any_permission(*permissions: str) -> Callable:
    async def _dep(ctx: RequestContext = Depends(get_context)) -> RequestContext:
        if any(ctx.has(perm) for perm in permissions):
            return ctx
        await _audit_authz_denied(ctx, permissions[0] if permissions else "unknown")
        raise ForbiddenError(f"Missing permission {permissions[0]}")

    return _dep


async def get_context(
    request: Request,
    claims: dict = Depends(get_claims),
    settings: PlatformSettings = Depends(get_settings),
) -> RequestContext:
    from app.application.identity import IdentityService

    factory = session_factory()
    is_sa = bool(claims.get("sa"))
    tid = claims.get("tid")
    if not is_sa and not tid:
        raise UnauthenticatedError("Tenant is required")
    ctx = RequestContext(
        request_id=get_request_id(request),
        tenant_id=UUID(tid) if tid else None,
        user_id=UUID(claims["sub"]),
        workspace_id=UUID(claims["wid"]) if claims.get("wid") else None,
        is_super_admin=is_sa,
    )
    async with factory() as session:
        async with session.begin():
            await apply_rls(session, ctx)
            service = IdentityService(session, settings)
            if is_sa:
                return await service.hydrate_super_admin(ctx)
            return await service.hydrate_context(ctx)


async def require_super_admin(ctx: RequestContext = Depends(get_context)) -> RequestContext:
    if not ctx.is_super_admin:
        raise ForbiddenError("Super admin required")
    return ctx


async def get_tenant_settings(
    ctx: RequestContext = Depends(get_context),
    settings: PlatformSettings = Depends(get_settings),
) -> PlatformSettings:
    """YAML defaults plus this tenant's runtime overlay. Secrets stay encrypted until use."""
    from sqlalchemy import select

    from app.adapters.db.models import ConfigOverlay
    from app.config.load import parse_settings
    from app.config.merge import deep_merge

    factory = session_factory()
    async with factory() as session:
        async with session.begin():
            await apply_rls(session, ctx)
            if ctx.tenant_id is None:
                return settings
            overlay = await session.scalar(
                select(ConfigOverlay).where(
                    ConfigOverlay.tenant_id == ctx.tenant_id,
                    ConfigOverlay.scope_type == "tenant",
                )
            )
            if overlay is None or not overlay.payload:
                return settings
            try:
                return parse_settings(deep_merge(settings.model_dump(), overlay.payload))
            except Exception:
                return settings
