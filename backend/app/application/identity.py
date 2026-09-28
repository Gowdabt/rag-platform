from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import structlog
from sqlalchemy import and_, delete, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.adapters.db.models import (
    AuditLog,
    Invitation,
    Organization,
    Permission,
    RefreshToken,
    Role,
    RolePermission,
    Team,
    TeamMember,
    Tenant,
    TenantMembership,
    User,
    UserRole,
    Workspace,
)
from app.adapters.db.rls import apply_rls_ids
from app.application.audit import write_audit
from app.application.authz_epoch import persist_authz_bump
from app.application.rbac import SEED_ROLES, SYSTEM_ROLES
from app.config.models import PlatformSettings
from app.core.context import RequestContext
from app.core.errors import (
    ConflictError,
    ForbiddenError,
    NotFoundError,
    UnauthenticatedError,
    ValidationFailedError,
)
from app.core.flags import expose_dev_tokens
from app.core.permissions import TENANT_ADMIN_ROLE, is_tenant_admin, is_tenant_admin_name
from app.core.security import (
    hash_password,
    hash_token,
    issue_jwt,
    new_refresh_token,
    resolve_jwt_secret,
    verify_password,
)
from app.core.text import slugify

log = structlog.get_logger("identity")
_PLATFORM_AUDIT_ACTIONS = frozenset({"tenant.create", "tenant.suspend", "tenant.update"})

INVITE_TTL = timedelta(days=7)
RESET_TTL = timedelta(hours=24)


class IdentityService:
    def __init__(self, session: AsyncSession, settings: PlatformSettings):
        self.session = session
        self.settings = settings

    def _secret(self) -> str:
        return resolve_jwt_secret(self.settings.auth.jwt_secret)

    async def signup(self, *, email: str, password: str, tenant_name: str) -> dict:
        email = email.strip().lower()
        if len(password) < 10:
            raise ValidationFailedError("Password must be at least 10 characters")
        existing = await self.session.scalar(select(User).where(User.email == email))
        if existing:
            raise ConflictError("An account with that email already exists")
        user = User(
            email=email,
            password_hash=hash_password(password),
            status="active",
            is_super_admin=False,
            display_name=email.split("@", 1)[0],
        )
        self.session.add(user)
        await self.session.flush()
        tenant = await self._create_tenant_graph(name=tenant_name, slug=slugify(tenant_name), admin_user=user)
        return await self._issue_session(user, tenant)

    async def login(
        self,
        *,
        email: str,
        password: str,
        tenant_id: UUID | None = None,
        tenant_slug: str | None = None,
        request_id: str | None = None,
    ) -> dict:
        email = email.strip().lower()
        user = await self.session.scalar(select(User).where(User.email == email))
        tenant = await self._resolve_login_tenant(tenant_id, tenant_slug)

        async def _fail(message: str = "Invalid email or password", *, error=UnauthenticatedError):
            if tenant is not None:
                await apply_rls_ids(self.session, tenant_id=tenant.id, user_id=user.id if user else None)
                await write_audit(
                    self.session,
                    tenant_id=tenant.id,
                    actor_user_id=user.id if user else None,
                    action="auth.login.fail",
                    resource_type="user",
                    resource_id=user.id if user else None,
                    metadata={"email": email},
                    request_id=request_id,
                )
            elif user and user.is_super_admin:
                await apply_rls_ids(self.session, tenant_id=None, user_id=user.id)
                await write_audit(
                    self.session,
                    tenant_id=None,
                    actor_user_id=user.id,
                    action="auth.login.fail",
                    resource_type="user",
                    resource_id=user.id,
                    metadata={"email": email},
                    request_id=request_id,
                )
            raise error(message)

        if user is None or user.status != "active" or not verify_password(password, user.password_hash):
            await _fail()

        if user.is_super_admin:
            await apply_rls_ids(self.session, tenant_id=None, user_id=user.id)
            user.last_login_at = datetime.now(UTC)
            await write_audit(
                self.session,
                tenant_id=None,
                actor_user_id=user.id,
                action="auth.login.success",
                resource_type="user",
                resource_id=user.id,
                request_id=request_id,
            )
            return await self._issue_session(user, tenant=None)

        if tenant_id is None and not (tenant_slug or "").strip():
            raise ValidationFailedError("tenant_slug or tenant_id is required")
        if tenant is None:
            await _fail()
        if tenant.status != "active":
            await _fail()
        await apply_rls_ids(self.session, tenant_id=tenant.id, user_id=user.id)
        membership = await self.session.scalar(
            select(TenantMembership).where(
                TenantMembership.user_id == user.id, TenantMembership.tenant_id == tenant.id
            )
        )
        if membership is None:
            await _fail()
        user.last_login_at = datetime.now(UTC)
        await write_audit(
            self.session,
            tenant_id=tenant.id,
            actor_user_id=user.id,
            action="auth.login.success",
            resource_type="user",
            resource_id=user.id,
            request_id=request_id,
        )
        return await self._issue_session(user, tenant, workspace_id=membership.default_workspace_id)

    async def _resolve_login_tenant(self, tenant_id: UUID | None, tenant_slug: str | None) -> Tenant | None:
        if tenant_id:
            return await self.session.get(Tenant, tenant_id)
        slug = (tenant_slug or "").strip().lower()
        if not slug:
            return None
        return await self.session.scalar(select(Tenant).where(Tenant.slug == slug))

    async def refresh(self, refresh_token: str) -> dict:
        token_hash = hash_token(refresh_token)
        row = await self.session.scalar(
            select(RefreshToken).where(
                RefreshToken.token_hash == token_hash, RefreshToken.revoked_at.is_(None)
            )
        )
        if row is None or row.expires_at < datetime.now(UTC):
            raise UnauthenticatedError("Invalid refresh token")
        user = await self.session.get(User, row.user_id)
        if user is None or user.status != "active":
            raise UnauthenticatedError("Invalid refresh token")
        tenant = await self.session.get(Tenant, row.tenant_id) if row.tenant_id else None
        if row.tenant_id and (tenant is None or tenant.status != "active"):
            raise ForbiddenError("Tenant is not active")
        row.revoked_at = datetime.now(UTC)
        workspace_id = None
        if tenant is not None:
            membership = await self.session.scalar(
                select(TenantMembership).where(
                    TenantMembership.user_id == user.id, TenantMembership.tenant_id == tenant.id
                )
            )
            workspace_id = membership.default_workspace_id if membership else None
        return await self._issue_session(user, tenant, workspace_id=workspace_id)

    async def logout(self, refresh_token: str) -> None:
        token_hash = hash_token(refresh_token)
        row = await self.session.scalar(select(RefreshToken).where(RefreshToken.token_hash == token_hash))
        if row:
            row.revoked_at = datetime.now(UTC)

    async def switch_tenant(self, ctx: RequestContext, tenant_id: UUID) -> dict:
        if ctx.is_super_admin:
            raise ForbiddenError("Super admin does not join customer tenants")
        user = await self.session.get(User, ctx.user_id)
        await apply_rls_ids(self.session, user_id=ctx.user_id)
        membership = await self.session.scalar(
            select(TenantMembership).where(
                TenantMembership.user_id == user.id, TenantMembership.tenant_id == tenant_id
            )
        )
        if membership is None:
            raise ForbiddenError("Not a member of that tenant")
        tenant = await self.session.get(Tenant, tenant_id)
        if tenant is None or tenant.status != "active":
            raise ForbiddenError("Tenant is not active")
        return await self._issue_session(user, tenant, workspace_id=membership.default_workspace_id)

    async def hydrate_super_admin(self, ctx: RequestContext) -> RequestContext:
        user = await self.session.get(User, ctx.user_id)
        if user is None or user.status != "active" or not user.is_super_admin:
            raise UnauthenticatedError("User is not active")
        return RequestContext(
            request_id=ctx.request_id,
            tenant_id=None,
            user_id=user.id,
            email=user.email,
            display_name=user.display_name,
            is_super_admin=True,
            last_login_at=user.last_login_at,
            permissions=frozenset(),
        )

    async def hydrate_context(self, ctx: RequestContext) -> RequestContext:
        user = await self.session.get(User, ctx.user_id)
        if user is None or user.status != "active":
            raise UnauthenticatedError("User is not active")
        membership = await self.session.scalar(
            select(TenantMembership).where(
                TenantMembership.user_id == user.id, TenantMembership.tenant_id == ctx.tenant_id
            )
        )
        if membership is None:
            raise ForbiddenError("Not a member of this tenant")
        tenant = await self.session.get(Tenant, ctx.tenant_id)
        if tenant is None or tenant.status != "active":
            raise ForbiddenError("Tenant is not active")
        roles = (
            await self.session.scalars(
                select(UserRole).where(UserRole.user_id == user.id, UserRole.tenant_id == ctx.tenant_id)
            )
        ).all()
        role_ids = [r.role_id for r in roles]
        role_rows = (
            (
                await self.session.scalars(
                    select(Role).where(Role.id.in_(role_ids), Role.tenant_id == ctx.tenant_id)
                )
            ).all()
            if role_ids
            else []
        )
        perm_ids = []
        if role_ids:
            perm_ids = [
                rp.permission_id
                for rp in (
                    await self.session.scalars(
                        select(RolePermission).where(
                            RolePermission.role_id.in_(role_ids),
                            RolePermission.tenant_id == ctx.tenant_id,
                        )
                    )
                ).all()
            ]
        permissions = set()
        if perm_ids:
            for p in (await self.session.scalars(select(Permission).where(Permission.id.in_(perm_ids)))).all():
                permissions.add(p.code)
        team_ids = [
            tm.team_id
            for tm in (
                await self.session.scalars(
                    select(TeamMember).where(TeamMember.user_id == user.id, TeamMember.tenant_id == ctx.tenant_id)
                )
            ).all()
        ]
        teams = (
            (
                await self.session.scalars(
                    select(Team).where(Team.id.in_(team_ids), Team.tenant_id == ctx.tenant_id)
                )
            ).all()
            if team_ids
            else []
        )
        team_names = tuple(t.name for t in teams)
        principals = (f"user:{user.id}",) + tuple(f"team:{n}" for n in team_names)
        workspace_id = ctx.workspace_id or membership.default_workspace_id
        return RequestContext(
            request_id=ctx.request_id,
            tenant_id=ctx.tenant_id,
            user_id=user.id,
            workspace_id=workspace_id or workspace_id,
            email=user.email,
            display_name=user.display_name,
            principal_ids=principals,
            team_names=team_names,
            permissions=frozenset(permissions),
            role_names=tuple(r.name for r in role_rows),
            is_super_admin=False,
            last_login_at=user.last_login_at,
        )

    async def me(self, ctx: RequestContext) -> dict:
        user = await self.session.get(User, ctx.user_id) if ctx.user_id else None
        tenant = await self.session.get(Tenant, ctx.tenant_id) if ctx.tenant_id else None
        name = ctx.display_name or (user.display_name if user else None)
        last_login = user.last_login_at if user else ctx.last_login_at
        return {
            "user_id": str(ctx.user_id) if ctx.user_id else None,
            "email": ctx.email,
            "name": name,
            "tenant_id": str(ctx.tenant_id) if ctx.tenant_id else None,
            "tenant_name": tenant.name if tenant else None,
            "tenant_slug": tenant.slug if tenant else None,
            "workspace_id": str(ctx.workspace_id) if ctx.workspace_id else None,
            "roles": list(ctx.role_names),
            "permissions": sorted(ctx.permissions),
            "teams": list(ctx.team_names),
            "is_super_admin": ctx.is_super_admin,
            "last_login_at": last_login.isoformat() if last_login else None,
        }

    async def list_tenants(self, ctx: RequestContext, *, limit: int = 100, offset: int = 0) -> list[dict]:
        from app.api.pagination import clip_limit, clip_offset

        await apply_rls_ids(self.session, user_id=ctx.user_id)
        rows = (
            await self.session.scalars(
                select(Tenant)
                .join(TenantMembership, TenantMembership.tenant_id == Tenant.id)
                .where(TenantMembership.user_id == ctx.user_id)
                .order_by(Tenant.name, Tenant.id)
                .offset(clip_offset(offset))
                .limit(clip_limit(limit))
            )
        ).all()
        return [{"id": str(t.id), "name": t.name, "slug": t.slug, "status": t.status} for t in rows]

    async def invite_user(self, ctx: RequestContext, *, email: str, password: str, role_name: str = "Member") -> dict:
        if not ctx.has("user:manage"):
            raise ForbiddenError("Missing permission user:manage")
        email = email.strip().lower()
        if is_tenant_admin_name(role_name) and not is_tenant_admin(ctx.role_names):
            raise ForbiddenError("Only tenant admins can assign Tenant Admin")
        user = await self.session.scalar(select(User).where(User.email == email))
        if user is None:
            if len(password) < 10:
                raise ValidationFailedError("Password must be at least 10 characters")
            user = User(
                email=email,
                password_hash=hash_password(password),
                status="active",
                is_super_admin=False,
                display_name=email.split("@", 1)[0],
            )
            self.session.add(user)
            await self.session.flush()
        if user.is_super_admin:
            raise ForbiddenError("Cannot add a platform super admin to a tenant")
        existing = await self.session.scalar(
            select(TenantMembership).where(
                TenantMembership.tenant_id == ctx.tenant_id, TenantMembership.user_id == user.id
            )
        )
        if existing:
            raise ConflictError("User is already a member of this tenant")
        membership = TenantMembership(
            tenant_id=ctx.tenant_id, user_id=user.id, default_workspace_id=ctx.workspace_id
        )
        self.session.add(membership)
        role = await self._role_by_name(ctx.require_tenant(), role_name)
        if role is None:
            raise NotFoundError(f"Role {role_name} not found")
        self.session.add(UserRole(tenant_id=ctx.tenant_id, user_id=user.id, role_id=role.id))
        await self.session.flush()
        await write_audit(
            self.session,
            tenant_id=ctx.tenant_id,
            actor_user_id=ctx.user_id,
            action="user.invite",
            resource_type="user",
            resource_id=user.id,
            metadata={"email": email, "role": role.name},
            request_id=ctx.request_id,
        )
        return {"user_id": str(user.id), "email": user.email, "role": role.name}

    async def create_invitation(
        self,
        ctx: RequestContext,
        *,
        email: str,
        name: str | None = None,
        role_ids: list[UUID] | None = None,
        role_names: list[str] | None = None,
    ) -> dict:
        if not ctx.has("users.create"):
            raise ForbiddenError("Missing permission users.create")
        email = email.strip().lower()
        roles = await self._resolve_roles(ctx, role_ids=role_ids, role_names=role_names, default_member=True)
        user = await self.session.scalar(select(User).where(User.email == email))
        if user and user.is_super_admin:
            raise ForbiddenError("Cannot add a platform super admin to a tenant")
        if user is None:
            user = User(
                email=email,
                password_hash=None,
                status="invited",
                is_super_admin=False,
                display_name=name or email.split("@", 1)[0],
            )
            self.session.add(user)
            await self.session.flush()
        elif name:
            user.display_name = user.display_name or name
        existing = await self.session.scalar(
            select(TenantMembership).where(
                TenantMembership.tenant_id == ctx.tenant_id, TenantMembership.user_id == user.id
            )
        )
        if existing and user.status == "active" and user.password_hash:
            raise ConflictError("User is already a member of this tenant")
        if existing is None:
            self.session.add(
                TenantMembership(
                    tenant_id=ctx.tenant_id, user_id=user.id, default_workspace_id=ctx.workspace_id
                )
            )
        existing_roles = {
            ur.role_id
            for ur in (
                await self.session.scalars(
                    select(UserRole).where(UserRole.tenant_id == ctx.tenant_id, UserRole.user_id == user.id)
                )
            ).all()
        }
        for role in roles:
            if role.id not in existing_roles:
                self.session.add(UserRole(tenant_id=ctx.tenant_id, user_id=user.id, role_id=role.id))
        token = new_refresh_token()
        invitation = Invitation(
            tenant_id=ctx.require_tenant(),
            email=email,
            name=name or user.display_name,
            token_hash=hash_token(token),
            purpose="invite",
            expires_at=datetime.now(UTC) + INVITE_TTL,
            invited_by=ctx.user_id,
            role_ids=[str(r.id) for r in roles],
            invited_user_id=user.id,
        )
        self.session.add(invitation)
        await self.session.flush()
        await write_audit(
            self.session,
            tenant_id=ctx.tenant_id,
            actor_user_id=ctx.user_id,
            action="user.invite",
            resource_type="user",
            resource_id=user.id,
            metadata={"email": email},
            request_id=ctx.request_id,
        )
        log.info("invitation_created", email=email, tenant_id=str(ctx.tenant_id))
        payload = {
            "user_id": str(user.id),
            "email": email,
            "message": "Invitation created. Email sending is not configured; use invitation_token.",
        }
        if expose_dev_tokens(self.settings.platform.environment):
            payload["invitation_token"] = token
        return payload

    async def accept_invite(self, *, token: str, password: str) -> dict:
        if len(password) < 10:
            raise ValidationFailedError("Password must be at least 10 characters")
        row = await self.session.scalar(
            select(Invitation).where(Invitation.token_hash == hash_token(token), Invitation.purpose == "invite")
        )
        if row is None or row.accepted_at is not None:
            raise ValidationFailedError("Invitation is invalid or already used")
        if row.expires_at < datetime.now(UTC):
            raise ValidationFailedError("Invitation has expired")
        user = await self.session.get(User, row.invited_user_id) if row.invited_user_id else None
        if user is None:
            user = await self.session.scalar(select(User).where(User.email == row.email))
        if user is None:
            raise NotFoundError("Invited user not found")
        tenant = await self.session.get(Tenant, row.tenant_id)
        if tenant is None or tenant.status != "active":
            raise ForbiddenError("Tenant is not active")
        await apply_rls_ids(self.session, tenant_id=tenant.id, user_id=user.id)
        user.password_hash = hash_password(password)
        user.status = "active"
        if row.name:
            user.display_name = row.name
        row.accepted_at = datetime.now(UTC)
        membership = await self.session.scalar(
            select(TenantMembership).where(
                TenantMembership.tenant_id == tenant.id, TenantMembership.user_id == user.id
            )
        )
        if membership is None:
            ws = await self.session.scalar(select(Workspace).where(Workspace.tenant_id == tenant.id))
            membership = TenantMembership(
                tenant_id=tenant.id,
                user_id=user.id,
                default_workspace_id=ws.id if ws else None,
            )
            self.session.add(membership)
        for raw_id in row.role_ids or []:
            try:
                role_id = UUID(str(raw_id))
            except ValueError:
                continue
            role = await self.session.get(Role, role_id)
            if role is None or role.tenant_id != tenant.id:
                continue
            already = await self.session.scalar(
                select(UserRole).where(
                    UserRole.tenant_id == tenant.id,
                    UserRole.user_id == user.id,
                    UserRole.role_id == role.id,
                )
            )
            if already is None:
                self.session.add(UserRole(tenant_id=tenant.id, user_id=user.id, role_id=role.id))
        await self.session.flush()
        return await self._issue_session(user, tenant, workspace_id=membership.default_workspace_id)

    async def forgot_password(self, *, email: str, tenant_slug: str) -> dict:
        email = email.strip().lower()
        slug = tenant_slug.strip().lower()
        tenant = await self.session.scalar(select(Tenant).where(Tenant.slug == slug))
        user = await self.session.scalar(select(User).where(User.email == email))
        payload = {"ok": True}
        if tenant is None or user is None:
            return payload
        membership = await self.session.scalar(
            select(TenantMembership).where(
                TenantMembership.tenant_id == tenant.id, TenantMembership.user_id == user.id
            )
        )
        if membership is None:
            return payload
        token = new_refresh_token()
        self.session.add(
            Invitation(
                tenant_id=tenant.id,
                email=email,
                name=user.display_name,
                token_hash=hash_token(token),
                purpose="reset",
                expires_at=datetime.now(UTC) + RESET_TTL,
                invited_by=None,
                role_ids=[],
                invited_user_id=user.id,
            )
        )
        await self.session.flush()
        if expose_dev_tokens(self.settings.platform.environment):
            payload["reset_token"] = token
        return payload

    async def reset_password(self, *, token: str, password: str) -> dict:
        if len(password) < 10:
            raise ValidationFailedError("Password must be at least 10 characters")
        row = await self.session.scalar(
            select(Invitation).where(Invitation.token_hash == hash_token(token), Invitation.purpose == "reset")
        )
        if row is None or row.accepted_at is not None:
            raise ValidationFailedError("Reset token is invalid or already used")
        if row.expires_at < datetime.now(UTC):
            raise ValidationFailedError("Reset token has expired")
        user = await self.session.get(User, row.invited_user_id) if row.invited_user_id else None
        if user is None:
            raise NotFoundError("User not found")
        user.password_hash = hash_password(password)
        if user.status == "invited":
            user.status = "active"
        row.accepted_at = datetime.now(UTC)
        tokens = (
            await self.session.scalars(
                select(RefreshToken).where(
                    RefreshToken.user_id == user.id,
                    RefreshToken.revoked_at.is_(None),
                    RefreshToken.tenant_id == row.tenant_id,
                )
            )
        ).all()
        now = datetime.now(UTC)
        for item in tokens:
            item.revoked_at = now
        await self.session.flush()
        return {"ok": True}

    async def list_users(self, ctx: RequestContext, *, limit: int = 100, offset: int = 0) -> list[dict]:
        from app.api.pagination import clip_limit, clip_offset

        memberships = (
            await self.session.scalars(
                select(TenantMembership)
                .where(TenantMembership.tenant_id == ctx.tenant_id)
                .order_by(TenantMembership.created_at.desc(), TenantMembership.id)
                .offset(clip_offset(offset))
                .limit(clip_limit(limit))
            )
        ).all()
        out = []
        for m in memberships:
            user = await self.session.get(User, m.user_id)
            if not user:
                continue
            role_names = await self._user_role_names(ctx.require_tenant(), user.id)
            out.append(
                {
                    "id": str(user.id),
                    "name": user.display_name,
                    "email": user.email,
                    "status": user.status,
                    "roles": role_names,
                    "last_login_at": user.last_login_at.isoformat() if user.last_login_at else None,
                }
            )
        return out

    async def update_user(
        self,
        ctx: RequestContext,
        user_id: UUID,
        *,
        status: str | None = None,
        role_ids: list[UUID] | None = None,
    ) -> dict:
        membership = await self.session.scalar(
            select(TenantMembership).where(
                TenantMembership.tenant_id == ctx.tenant_id, TenantMembership.user_id == user_id
            )
        )
        user = await self.session.get(User, user_id)
        if membership is None or user is None:
            raise NotFoundError("User not found")
        if status is not None:
            if not ctx.has("users.disable") and not ctx.has("users.update"):
                raise ForbiddenError("Missing permission users.disable")
            if status not in {"active", "disabled"}:
                raise ValidationFailedError("status must be active or disabled")
            user.status = status
            if status == "disabled":
                await self._revoke_user_sessions(user_id, tenant_id=ctx.tenant_id)
                await persist_authz_bump(self.session, ctx.require_tenant(), user_id)
            else:
                await persist_authz_bump(self.session, ctx.require_tenant(), user_id)
        if role_ids is not None:
            if not ctx.has("roles.assign"):
                raise ForbiddenError("Missing permission roles.assign")
            roles = await self._resolve_roles(ctx, role_ids=role_ids, role_names=None, default_member=False)
            await self.session.execute(
                delete(UserRole).where(UserRole.tenant_id == ctx.tenant_id, UserRole.user_id == user_id)
            )
            for role in roles:
                self.session.add(UserRole(tenant_id=ctx.tenant_id, user_id=user_id, role_id=role.id))
            await write_audit(
                self.session,
                tenant_id=ctx.tenant_id,
                actor_user_id=ctx.user_id,
                action="user.role_change",
                resource_type="user",
                resource_id=user_id,
                metadata={"role_ids": [str(r.id) for r in roles]},
                request_id=ctx.request_id,
            )
            await persist_authz_bump(self.session, ctx.require_tenant(), user_id)
        await self.session.flush()
        return {
            "id": str(user.id),
            "name": user.display_name,
            "email": user.email,
            "status": user.status,
            "roles": await self._user_role_names(ctx.require_tenant(), user.id),
            "last_login_at": user.last_login_at.isoformat() if user.last_login_at else None,
        }

    async def revoke_sessions(self, ctx: RequestContext, user_id: UUID) -> dict:
        if not ctx.has("users.update") and not ctx.has("users.disable"):
            raise ForbiddenError("Missing permission users.update")
        membership = await self.session.scalar(
            select(TenantMembership).where(
                TenantMembership.tenant_id == ctx.tenant_id, TenantMembership.user_id == user_id
            )
        )
        if membership is None:
            raise NotFoundError("User not found")
        count = await self._revoke_user_sessions(user_id, tenant_id=ctx.tenant_id)
        return {"ok": True, "revoked": count}

    async def list_permissions(self, ctx: RequestContext) -> list[dict]:
        if not ctx.has("roles.view") and not ctx.has("user:manage"):
            raise ForbiddenError("Missing permission roles.view")
        rows = (await self.session.scalars(select(Permission).order_by(Permission.code))).all()
        return [{"code": p.code, "description": p.description} for p in rows]

    async def list_roles(self, ctx: RequestContext, *, limit: int = 100, offset: int = 0) -> list[dict]:
        from app.api.pagination import clip_limit, clip_offset

        rows = (
            await self.session.scalars(
                select(Role)
                .where(Role.tenant_id == ctx.tenant_id)
                .order_by(Role.name, Role.id)
                .offset(clip_offset(offset))
                .limit(clip_limit(limit))
            )
        ).all()
        out = []
        for role in rows:
            out.append(
                {
                    "id": str(role.id),
                    "name": role.name,
                    "description": role.description,
                    "is_system": role.is_system,
                    "permission_codes": await self._role_permission_codes(ctx.require_tenant(), role.id),
                }
            )
        return out

    async def create_role(
        self, ctx: RequestContext, *, name: str, description: str | None = None, permission_codes: list[str]
    ) -> dict:
        if not ctx.has("roles.create"):
            raise ForbiddenError("Missing permission roles.create")
        name = name.strip()
        if not name:
            raise ValidationFailedError("name is required")
        if is_tenant_admin_name(name):
            raise ForbiddenError("Cannot create a system role")
        existing = await self.session.scalar(
            select(Role).where(Role.tenant_id == ctx.tenant_id, Role.name == name)
        )
        if existing:
            raise ConflictError("A role with that name already exists")
        role = Role(
            tenant_id=ctx.require_tenant(),
            name=name,
            description=description or "",
            is_system=False,
        )
        self.session.add(role)
        await self.session.flush()
        await self._set_role_permissions(ctx, role, permission_codes)
        await write_audit(
            self.session,
            tenant_id=ctx.tenant_id,
            actor_user_id=ctx.user_id,
            action="role.create",
            resource_type="role",
            resource_id=role.id,
            metadata={"name": name},
            request_id=ctx.request_id,
        )
        await persist_authz_bump(self.session, ctx.require_tenant())
        return {
            "id": str(role.id),
            "name": role.name,
            "description": role.description,
            "is_system": role.is_system,
            "permission_codes": await self._role_permission_codes(ctx.require_tenant(), role.id),
        }

    async def update_role(
        self,
        ctx: RequestContext,
        role_id: UUID,
        *,
        name: str | None = None,
        description: str | None = None,
        permission_codes: list[str] | None = None,
    ) -> dict:
        if not ctx.has("roles.update"):
            raise ForbiddenError("Missing permission roles.update")
        role = await self.session.get(Role, role_id)
        if role is None or role.tenant_id != ctx.tenant_id:
            raise NotFoundError("Role not found")
        if name is not None and name != role.name:
            if role.is_system or is_tenant_admin_name(role.name):
                raise ForbiddenError("Cannot rename a system role")
            clash = await self.session.scalar(
                select(Role).where(Role.tenant_id == ctx.tenant_id, Role.name == name, Role.id != role.id)
            )
            if clash:
                raise ConflictError("A role with that name already exists")
            role.name = name
        if description is not None:
            role.description = description
        if permission_codes is not None:
            await self._set_role_permissions(ctx, role, permission_codes)
        await write_audit(
            self.session,
            tenant_id=ctx.tenant_id,
            actor_user_id=ctx.user_id,
            action="role.update",
            resource_type="role",
            resource_id=role.id,
            request_id=ctx.request_id,
        )
        await persist_authz_bump(self.session, ctx.require_tenant())
        await self.session.flush()
        return {
            "id": str(role.id),
            "name": role.name,
            "description": role.description,
            "is_system": role.is_system,
            "permission_codes": await self._role_permission_codes(ctx.require_tenant(), role.id),
        }

    async def delete_role(self, ctx: RequestContext, role_id: UUID) -> dict:
        if not ctx.has("roles.delete"):
            raise ForbiddenError("Missing permission roles.delete")
        role = await self.session.get(Role, role_id)
        if role is None or role.tenant_id != ctx.tenant_id:
            raise NotFoundError("Role not found")
        if role.is_system or is_tenant_admin_name(role.name):
            raise ForbiddenError("Cannot delete a system role")
        assigned = await self.session.scalar(select(UserRole).where(UserRole.role_id == role.id))
        if assigned:
            raise ConflictError("Role is assigned to users")
        await self.session.execute(delete(RolePermission).where(RolePermission.role_id == role.id))
        await self.session.delete(role)
        await write_audit(
            self.session,
            tenant_id=ctx.tenant_id,
            actor_user_id=ctx.user_id,
            action="role.delete",
            resource_type="role",
            resource_id=role_id,
            metadata={"name": role.name},
            request_id=ctx.request_id,
        )
        await persist_authz_bump(self.session, ctx.require_tenant())
        await self.session.flush()
        return {"ok": True}

    async def list_workspaces(self, ctx: RequestContext, *, limit: int = 100, offset: int = 0) -> list[dict]:
        from app.api.pagination import clip_limit, clip_offset

        rows = (
            await self.session.scalars(
                select(Workspace)
                .where(Workspace.tenant_id == ctx.tenant_id)
                .order_by(Workspace.name, Workspace.id)
                .offset(clip_offset(offset))
                .limit(clip_limit(limit))
            )
        ).all()
        return [
            {"id": str(w.id), "name": w.name, "slug": w.slug, "organization_id": str(w.organization_id)}
            for w in rows
        ]

    async def create_workspace(self, ctx: RequestContext, *, name: str, organization_id: UUID | None = None) -> dict:
        if not ctx.has("workspace:manage"):
            raise ForbiddenError("Missing permission workspace:manage")
        org_id = organization_id
        if org_id is None:
            org = await self.session.scalar(select(Organization).where(Organization.tenant_id == ctx.tenant_id))
            if org is None:
                raise NotFoundError("Organization not found")
            org_id = org.id
        ws = Workspace(tenant_id=ctx.tenant_id, organization_id=org_id, name=name, slug=slugify(name))
        self.session.add(ws)
        await self.session.flush()
        return {"id": str(ws.id), "name": ws.name, "slug": ws.slug}

    async def create_team(self, ctx: RequestContext, *, name: str, workspace_id: UUID | None = None) -> dict:
        if not ctx.has("team:manage"):
            raise ForbiddenError("Missing permission team:manage")
        team = Team(tenant_id=ctx.tenant_id, name=name, workspace_id=workspace_id or ctx.workspace_id)
        self.session.add(team)
        await self.session.flush()
        return {"id": str(team.id), "name": team.name}

    async def add_team_member(self, ctx: RequestContext, *, team_id: UUID, user_id: UUID) -> dict:
        if not ctx.has("team:manage"):
            raise ForbiddenError("Missing permission team:manage")
        team = await self.session.get(Team, team_id)
        if team is None:
            raise NotFoundError("Team not found")
        self.session.add(TeamMember(tenant_id=ctx.tenant_id, team_id=team_id, user_id=user_id))
        await self.session.flush()
        return {"team_id": str(team_id), "user_id": str(user_id)}

    async def list_teams(self, ctx: RequestContext, *, limit: int = 100, offset: int = 0) -> list[dict]:
        from app.api.pagination import clip_limit, clip_offset

        rows = (
            await self.session.scalars(
                select(Team)
                .where(Team.tenant_id == ctx.tenant_id)
                .order_by(Team.name, Team.id)
                .offset(clip_offset(offset))
                .limit(clip_limit(limit))
            )
        ).all()
        return [
            {"id": str(t.id), "name": t.name, "workspace_id": str(t.workspace_id) if t.workspace_id else None}
            for t in rows
        ]

    async def list_platform_tenants(self, ctx: RequestContext, *, limit: int = 100, offset: int = 0) -> list[dict]:
        from app.api.pagination import clip_limit, clip_offset

        self._require_super_admin(ctx)
        rows = (
            await self.session.scalars(
                select(Tenant)
                .order_by(Tenant.created_at.desc(), Tenant.id)
                .offset(clip_offset(offset))
                .limit(clip_limit(limit))
            )
        ).all()
        return [self._tenant_payload(t) for t in rows]

    async def list_platform_audit_logs(
        self, ctx: RequestContext, *, limit: int = 100, offset: int = 0
    ) -> list[dict]:
        """Super-admin platform audit. Never document:read_all; no customer document contents."""
        from app.api.pagination import clip_limit, clip_offset

        self._require_super_admin(ctx)
        bound = clip_limit(limit, maximum=200)
        start = clip_offset(offset)
        visible = list(
            (
                await self.session.scalars(
                    select(AuditLog)
                    .where(self._platform_audit_filter())
                    .order_by(AuditLog.created_at.desc(), AuditLog.id)
                    .offset(start)
                    .limit(bound)
                )
            ).all()
        )
        by_id = {row.id: row for row in visible}
        for row in await self._tenant_lifecycle_audit_rows(ctx):
            by_id.setdefault(row.id, row)
        rows = sorted(
            by_id.values(),
            key=lambda row: row.created_at or datetime.min.replace(tzinfo=UTC),
            reverse=True,
        )
        return await self._serialize_platform_audit(rows[:bound])

    def _platform_audit_filter(self):
        return or_(
            AuditLog.tenant_id.is_(None),
            and_(
                AuditLog.resource_type == "tenant",
                AuditLog.action.in_(tuple(_PLATFORM_AUDIT_ACTIONS)),
            ),
        )

    async def _tenant_lifecycle_audit_rows(self, ctx: RequestContext) -> list[AuditLog]:
        tenants = (
            await self.session.scalars(select(Tenant).order_by(Tenant.created_at.desc(), Tenant.id).limit(200))
        ).all()
        if not tenants:
            return []
        collected: list[AuditLog] = []
        for tenant in tenants:
            await apply_rls_ids(self.session, tenant_id=tenant.id, user_id=ctx.user_id)
            part = (
                await self.session.scalars(
                    select(AuditLog)
                    .where(
                        AuditLog.actor_user_id == ctx.user_id,
                        AuditLog.resource_type == "tenant",
                        AuditLog.action.in_(tuple(_PLATFORM_AUDIT_ACTIONS)),
                    )
                    .order_by(AuditLog.created_at.desc(), AuditLog.id)
                    .limit(200)
                )
            ).all()
            collected.extend(part)
        await apply_rls_ids(self.session, tenant_id=None, user_id=ctx.user_id)
        collected.sort(key=lambda row: row.created_at or datetime.min.replace(tzinfo=UTC), reverse=True)
        return collected[:200]

    async def _serialize_platform_audit(self, rows: list[AuditLog]) -> list[dict]:
        tenant_ids = {row.tenant_id for row in rows if row.tenant_id}
        actor_ids = {row.actor_user_id for row in rows if row.actor_user_id}
        slugs: dict[UUID, str] = {}
        if tenant_ids:
            tenants = (
                await self.session.scalars(select(Tenant).where(Tenant.id.in_(tenant_ids)))
            ).all()
            slugs = {t.id: t.slug for t in tenants}
        emails: dict[UUID, str] = {}
        if actor_ids:
            users = (await self.session.scalars(select(User).where(User.id.in_(actor_ids)))).all()
            emails = {u.id: u.email for u in users}
        return [
            {
                "id": str(row.id),
                "action": row.action,
                "resource_type": row.resource_type,
                "resource_id": str(row.resource_id) if row.resource_id else None,
                "tenant_id": str(row.tenant_id) if row.tenant_id else None,
                "tenant_slug": slugs.get(row.tenant_id) if row.tenant_id else None,
                "actor_email": emails.get(row.actor_user_id) if row.actor_user_id else None,
                "created_at": row.created_at.isoformat() if row.created_at else None,
            }
            for row in rows
            if row.tenant_id is None
            or (row.resource_type == "tenant" and row.action in _PLATFORM_AUDIT_ACTIONS)
        ]

    async def create_platform_tenant(
        self,
        ctx: RequestContext,
        *,
        name: str,
        slug: str,
        admin_name: str,
        admin_email: str,
        status: str | None = None,
    ) -> dict:
        self._require_super_admin(ctx)
        status = status or "active"
        if status not in {"active", "suspended"}:
            raise ValidationFailedError("status must be active or suspended")
        admin_email = admin_email.strip().lower()
        slug = slugify(slug)
        if await self.session.scalar(select(Tenant).where(Tenant.slug == slug)):
            raise ConflictError("A tenant with that slug already exists")
        user = await self.session.scalar(select(User).where(User.email == admin_email))
        if user and user.is_super_admin:
            raise ForbiddenError("Super admin cannot be a tenant admin")
        if user is None:
            user = User(
                email=admin_email,
                password_hash=None,
                status="invited",
                is_super_admin=False,
                display_name=admin_name,
            )
            self.session.add(user)
            await self.session.flush()
        tenant = await self._create_tenant_graph(name=name, slug=slug, admin_user=user)
        tenant.status = status
        await apply_rls_ids(self.session, tenant_id=tenant.id, user_id=ctx.user_id)
        admin_role = await self._role_by_name(tenant.id, TENANT_ADMIN_ROLE)
        token = new_refresh_token()
        self.session.add(
            Invitation(
                tenant_id=tenant.id,
                email=admin_email,
                name=admin_name,
                token_hash=hash_token(token),
                purpose="invite",
                expires_at=datetime.now(UTC) + INVITE_TTL,
                invited_by=ctx.user_id,
                role_ids=[str(admin_role.id)] if admin_role else [],
                invited_user_id=user.id,
            )
        )
        await write_audit(
            self.session,
            tenant_id=tenant.id,
            actor_user_id=ctx.user_id,
            action="tenant.create",
            resource_type="tenant",
            resource_id=tenant.id,
            metadata={"slug": tenant.slug, "admin_email": admin_email},
            request_id=ctx.request_id,
        )
        await self.session.flush()
        log.info("platform_tenant_invite", email=admin_email, slug=tenant.slug)
        payload = {
            "tenant": self._tenant_payload(tenant),
            "message": "Invitation created. Email sending is not configured; use invitation_token.",
        }
        if expose_dev_tokens(self.settings.platform.environment):
            payload["invitation_token"] = token
        return payload

    async def patch_platform_tenant(
        self, ctx: RequestContext, tenant_id: UUID, *, name: str | None = None, status: str | None = None
    ) -> dict:
        self._require_super_admin(ctx)
        tenant = await self.session.get(Tenant, tenant_id)
        if tenant is None:
            raise NotFoundError("Tenant not found")
        if name is not None:
            tenant.name = name
        if status is not None:
            if status not in {"active", "suspended"}:
                raise ValidationFailedError("status must be active or suspended")
            tenant.status = status
            await persist_authz_bump(self.session, tenant.id)
            await apply_rls_ids(self.session, tenant_id=tenant.id, user_id=ctx.user_id)
            await write_audit(
                self.session,
                tenant_id=tenant.id,
                actor_user_id=ctx.user_id,
                action="tenant.suspend" if status == "suspended" else "tenant.update",
                resource_type="tenant",
                resource_id=tenant.id,
                metadata={"status": status},
                request_id=ctx.request_id,
            )
        await self.session.flush()
        return self._tenant_payload(tenant)

    async def ensure_super_admin(self) -> User | None:
        email = os.environ.get("PLATFORM_SUPERADMIN_EMAIL", "").strip().lower()
        password = os.environ.get("PLATFORM_SUPERADMIN_PASSWORD", "")
        if not email or not password:
            return None
        if len(password) < 8:
            log.warning("super_admin_bootstrap_skipped", reason="password_too_short")
            return None
        user = await self.session.scalar(select(User).where(User.email == email))
        if user is None:
            user = User(
                email=email,
                password_hash=hash_password(password),
                status="active",
                is_super_admin=True,
                display_name="Platform Super Admin",
            )
            self.session.add(user)
            await self.session.flush()
            log.info("super_admin_created", email=email)
            return user
        if user.is_super_admin:
            return user
        membership = await self.session.scalar(
            select(TenantMembership).where(TenantMembership.user_id == user.id)
        )
        if membership is not None:
            log.warning("super_admin_not_promoted_existing_tenant_user", email=email)
            return None
        user.is_super_admin = True
        user.status = "active"
        if not user.password_hash:
            user.password_hash = hash_password(password)
        await self.session.flush()
        log.info("super_admin_flagged", email=email)
        return user

    def _require_super_admin(self, ctx: RequestContext) -> None:
        if not ctx.is_super_admin:
            raise ForbiddenError("Super admin required")

    def _tenant_payload(self, tenant: Tenant) -> dict:
        return {
            "id": str(tenant.id),
            "name": tenant.name,
            "slug": tenant.slug,
            "status": tenant.status,
            "created_at": tenant.created_at.isoformat() if tenant.created_at else None,
        }

    async def _issue_session(self, user: User, tenant: Tenant | None, workspace_id: UUID | None = None) -> dict:
        secret = self._secret()
        is_sa = bool(user.is_super_admin) and tenant is None
        access = issue_jwt(
            secret=secret,
            user_id=user.id,
            tenant_id=tenant.id if tenant else None,
            token_type="access",
            ttl_seconds=self.settings.auth.access_ttl_seconds,
            workspace_id=workspace_id,
            is_super_admin=is_sa,
        )
        refresh = new_refresh_token()
        self.session.add(
            RefreshToken(
                id=uuid4(),
                user_id=user.id,
                tenant_id=tenant.id if tenant else None,
                token_hash=hash_token(refresh),
                expires_at=datetime.now(UTC) + timedelta(seconds=self.settings.auth.refresh_ttl_seconds),
            )
        )
        await self.session.flush()
        return {
            "access_token": access,
            "refresh_token": refresh,
            "token_type": "bearer",
            "expires_in": self.settings.auth.access_ttl_seconds,
            "tenant_id": str(tenant.id) if tenant else None,
            "user_id": str(user.id),
        }

    async def _create_tenant_graph(self, *, name: str, slug: str, admin_user: User | None = None) -> Tenant:
        if await self.session.scalar(select(Tenant).where(Tenant.slug == slug)):
            slug = f"{slug}-{str(uuid4())[:8]}"
        tenant = Tenant(name=name, slug=slug, status="active", privacy={}, budget={})
        self.session.add(tenant)
        await self.session.flush()
        await apply_rls_ids(self.session, tenant_id=tenant.id, user_id=admin_user.id if admin_user else None)
        org = Organization(tenant_id=tenant.id, name=name, slug="default")
        self.session.add(org)
        await self.session.flush()
        workspace = Workspace(tenant_id=tenant.id, organization_id=org.id, name="Default", slug="default")
        self.session.add(workspace)
        await self.session.flush()
        perms = (await self.session.scalars(select(Permission))).all()
        perm_by_code = {p.code: p for p in perms}
        for role_name, codes in SEED_ROLES.items():
            role = Role(
                tenant_id=tenant.id,
                name=role_name,
                description="",
                is_system=role_name in SYSTEM_ROLES,
            )
            self.session.add(role)
            await self.session.flush()
            for code in codes:
                perm = perm_by_code.get(code)
                if perm:
                    self.session.add(
                        RolePermission(tenant_id=tenant.id, role_id=role.id, permission_id=perm.id)
                    )
            if admin_user is not None and is_tenant_admin_name(role_name):
                self.session.add(UserRole(tenant_id=tenant.id, user_id=admin_user.id, role_id=role.id))
        if admin_user is not None:
            self.session.add(
                TenantMembership(
                    tenant_id=tenant.id, user_id=admin_user.id, default_workspace_id=workspace.id
                )
            )
        await self.session.flush()
        return tenant

    async def _role_by_name(self, tenant_id: UUID, name: str) -> Role | None:
        if is_tenant_admin_name(name):
            row = await self.session.scalar(
                select(Role).where(Role.tenant_id == tenant_id, Role.name == TENANT_ADMIN_ROLE)
            )
            if row:
                return row
            return await self.session.scalar(
                select(Role).where(Role.tenant_id == tenant_id, Role.name == "Admin")
            )
        return await self.session.scalar(select(Role).where(Role.tenant_id == tenant_id, Role.name == name))

    async def _resolve_roles(
        self,
        ctx: RequestContext,
        *,
        role_ids: list[UUID] | None,
        role_names: list[str] | None,
        default_member: bool,
    ) -> list[Role]:
        found: list[Role] = []
        seen: set[UUID] = set()
        for role_id in role_ids or []:
            role = await self.session.get(Role, role_id)
            if role is None or role.tenant_id != ctx.tenant_id:
                raise NotFoundError("Role not found")
            if role.id not in seen:
                found.append(role)
                seen.add(role.id)
        for name in role_names or []:
            role = await self._role_by_name(ctx.require_tenant(), name)
            if role is None:
                raise NotFoundError(f"Role {name} not found")
            if role.id not in seen:
                found.append(role)
                seen.add(role.id)
        if not found and default_member:
            member = await self._role_by_name(ctx.require_tenant(), "Member")
            if member:
                found.append(member)
        for role in found:
            if is_tenant_admin_name(role.name) and not is_tenant_admin(ctx.role_names):
                raise ForbiddenError("Only tenant admins can assign Tenant Admin")
        return found

    async def _set_role_permissions(self, ctx: RequestContext, role: Role, permission_codes: list[str]) -> None:
        codes = [c.strip() for c in permission_codes if c and c.strip()]
        await self.session.execute(delete(RolePermission).where(RolePermission.role_id == role.id))
        if not codes:
            return
        perms = (
            await self.session.scalars(select(Permission).where(Permission.code.in_(codes)))
        ).all()
        found = {p.code: p for p in perms}
        missing = [c for c in codes if c not in found]
        if missing:
            raise ValidationFailedError(f"Unknown permission codes: {', '.join(missing)}")
        for perm in perms:
            self.session.add(
                RolePermission(tenant_id=ctx.require_tenant(), role_id=role.id, permission_id=perm.id)
            )

    async def _role_permission_codes(self, tenant_id: UUID, role_id: UUID) -> list[str]:
        perm_ids = [
            rp.permission_id
            for rp in (
                await self.session.scalars(
                    select(RolePermission).where(
                        RolePermission.role_id == role_id, RolePermission.tenant_id == tenant_id
                    )
                )
            ).all()
        ]
        if not perm_ids:
            return []
        rows = (await self.session.scalars(select(Permission).where(Permission.id.in_(perm_ids)))).all()
        return sorted(p.code for p in rows)

    async def _user_role_names(self, tenant_id: UUID, user_id: UUID) -> list[str]:
        role_ids = [
            ur.role_id
            for ur in (
                await self.session.scalars(
                    select(UserRole).where(UserRole.tenant_id == tenant_id, UserRole.user_id == user_id)
                )
            ).all()
        ]
        if not role_ids:
            return []
        rows = (
            await self.session.scalars(select(Role).where(Role.id.in_(role_ids), Role.tenant_id == tenant_id))
        ).all()
        return [r.name for r in rows]

    async def _revoke_user_sessions(self, user_id: UUID, *, tenant_id: UUID | None) -> int:
        rows = (
            await self.session.scalars(
                select(RefreshToken).where(
                    RefreshToken.user_id == user_id,
                    RefreshToken.revoked_at.is_(None),
                )
            )
        ).all()
        now = datetime.now(UTC)
        count = 0
        for row in rows:
            if tenant_id is not None and row.tenant_id is not None and row.tenant_id != tenant_id:
                continue
            if tenant_id is not None and row.tenant_id is None:
                continue
            row.revoked_at = now
            count += 1
        return count
