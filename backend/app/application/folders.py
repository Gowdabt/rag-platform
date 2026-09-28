from __future__ import annotations

from uuid import UUID

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.attributes import flag_modified

from app.adapters.db.models import (
    Document,
    Folder,
    ResourcePermission,
    Role,
    SourceSubscription,
    TenantMembership,
    User,
)
from app.application.audit import write_audit
from app.application.authz import _str_list, inherit_acl, owner_acl
from app.application.authz_epoch import persist_authz_bump
from app.core.context import RequestContext
from app.core.errors import ForbiddenError, NotFoundError, ValidationFailedError

FOLDER_ACTIONS = ("view", "edit", "upload", "delete", "share")

# Folder ACL vs document ACL (deny-by-default; do not weaken this):
# - Empty document ACL denies read (see can_read_document).
# - ResourcePermission rows are folder grants (user/role, allow or deny).
# - Folder *actions* inherit down the parent chain: a view grant on a parent
#   allows viewing children (`_has_action` walks ancestors).
# - Folder *read* grants are compiled onto documents in the subtree so retrieval
#   SQL can enforce them. Document-only shares (allowed_users not tagged as
#   folder_grant_users) survive recompile. Revoke/move drop prior folder users
#   via that bookkeeping, then merge the current chain extra.
# - Moving a folder recompiles against the new parent chain.
# - Revoking a grant recompiles; empty remaining ACL still denies non-owners.


class FolderService:
    def __init__(self, session: AsyncSession, ctx: RequestContext):
        self.session = session
        self.ctx = ctx

    async def list_folders(self, *, limit: int = 100, offset: int = 0) -> list[dict]:
        from app.api.pagination import clip_limit, clip_offset

        bound = clip_limit(limit)
        start = clip_offset(offset)
        tenant = self.ctx.require_tenant()
        if self._has_exact("folders.view"):
            rows = (
                await self.session.scalars(
                    select(Folder)
                    .where(Folder.tenant_id == tenant)
                    .order_by(Folder.created_at.desc(), Folder.id)
                    .offset(start)
                    .limit(bound)
                )
            ).all()
            return [await self._summary(folder) for folder in rows]
        ids = await self._listable_folder_ids(limit=bound, offset=start)
        if not ids:
            return []
        rows = (
            await self.session.scalars(
                select(Folder)
                .where(Folder.tenant_id == tenant, Folder.id.in_(ids))
                .order_by(Folder.created_at.desc(), Folder.id)
            )
        ).all()
        out = []
        for folder in rows:
            if await self._can_view(folder):
                out.append(await self._summary(folder))
        return out

    async def create_folder(
        self, *, name: str, parent_id: UUID | None = None, workspace_id: UUID | None = None
    ) -> dict:
        if not self.ctx.has("folders.create"):
            raise ForbiddenError("Missing permission folders.create")
        name = name.strip()
        if not name:
            raise ValidationFailedError("name is required")
        workspace_id = workspace_id or self.ctx.workspace_id
        if workspace_id is None:
            raise ValidationFailedError("workspace_id is required")
        parent = None
        if parent_id:
            parent = await self._get_folder(parent_id)
            if not await self._can_edit(parent):
                raise ForbiddenError("Missing permission to add a child folder")
            workspace_id = parent.workspace_id
        folder = Folder(
            tenant_id=self.ctx.require_tenant(),
            workspace_id=workspace_id,
            parent_id=parent.id if parent else None,
            name=name,
            owner_user_id=self.ctx.user_id,
        )
        self.session.add(folder)
        await self.session.flush()
        return await self._summary(folder)

    async def get_folder(self, folder_id: UUID) -> dict:
        folder = await self._get_folder(folder_id)
        if not await self._can_view(folder):
            raise NotFoundError("Folder not found")
        payload = await self._summary(folder)
        payload["documents_count"] = await self._document_count(folder.id)
        payload["grants"] = await self._grants_payload(folder.id)
        return payload

    async def update_folder(
        self, folder_id: UUID, *, name: str | None = None, parent_id: UUID | None = None
    ) -> dict:
        folder = await self._get_folder(folder_id)
        if not await self._can_edit(folder):
            raise ForbiddenError("Missing permission folders.update")
        if name is not None:
            name = name.strip()
            if not name:
                raise ValidationFailedError("name is required")
            folder.name = name
        if parent_id is not None:
            if parent_id == folder.id:
                raise ValidationFailedError("Folder cannot be its own parent")
            parent = await self._get_folder(parent_id)
            if await self._is_descendant(parent, folder.id):
                raise ValidationFailedError("Cannot move a folder under its descendant")
            folder.parent_id = parent.id
            folder.workspace_id = parent.workspace_id
            await self.session.flush()
            await self._compile_and_apply(folder)
            await persist_authz_bump(self.session, self.ctx.require_tenant())
        await self.session.flush()
        return await self._summary(folder)

    async def delete_folder(self, folder_id: UUID) -> dict:
        folder = await self._get_folder(folder_id)
        if not await self._can_delete(folder):
            raise ForbiddenError("Missing permission folders.delete")
        child = await self.session.scalar(select(Folder).where(Folder.parent_id == folder.id))
        if child:
            raise ValidationFailedError("Delete child folders first")
        docs = (
            await self.session.scalars(select(Document).where(Document.folder_id == folder.id))
        ).all()
        for doc in docs:
            doc.folder_id = None
        subs = (
            await self.session.scalars(
                select(SourceSubscription).where(SourceSubscription.folder_id == folder.id)
            )
        ).all()
        for sub in subs:
            sub.folder_id = None
        grants = (
            await self.session.scalars(
                select(ResourcePermission).where(
                    ResourcePermission.tenant_id == self.ctx.tenant_id,
                    ResourcePermission.resource_type == "folder",
                    ResourcePermission.resource_id == folder.id,
                )
            )
        ).all()
        for grant in grants:
            await self.session.delete(grant)
        await self.session.delete(folder)
        await self.session.flush()
        return {"ok": True}

    async def share_folder(
        self,
        folder_id: UUID,
        *,
        subject_type: str,
        actions: list[str],
        deny: bool = False,
        email: str | None = None,
        user_id: UUID | None = None,
        role_id: UUID | None = None,
        role_name: str | None = None,
    ) -> dict:
        folder = await self._get_folder(folder_id)
        if not await self._can_share(folder):
            raise ForbiddenError("Missing permission folders.share")
        subject_type = subject_type.strip().lower()
        if subject_type not in {"user", "role"}:
            raise ValidationFailedError("subject_type must be user or role")
        clean_actions = []
        for action in actions:
            item = str(action).strip().lower()
            if item not in FOLDER_ACTIONS:
                raise ValidationFailedError(f"Unsupported action {action}")
            if item not in clean_actions:
                clean_actions.append(item)
        if not clean_actions:
            raise ValidationFailedError("actions is required")
        subject_id = await self._resolve_subject(
            subject_type, email=email, user_id=user_id, role_id=role_id, role_name=role_name
        )
        existing = await self.session.scalar(
            select(ResourcePermission).where(
                ResourcePermission.tenant_id == self.ctx.tenant_id,
                ResourcePermission.resource_type == "folder",
                ResourcePermission.resource_id == folder.id,
                ResourcePermission.subject_type == subject_type,
                ResourcePermission.subject_id == subject_id,
            )
        )
        if existing:
            existing.actions = clean_actions
            existing.deny = deny
            grant = existing
        else:
            grant = ResourcePermission(
                tenant_id=self.ctx.require_tenant(),
                resource_type="folder",
                resource_id=folder.id,
                subject_type=subject_type,
                subject_id=subject_id,
                actions=clean_actions,
                deny=deny,
            )
            self.session.add(grant)
        await self.session.flush()
        await self._compile_and_apply(folder)
        await write_audit(
            self.session,
            tenant_id=self.ctx.tenant_id,
            actor_user_id=self.ctx.user_id,
            action="folder.share",
            resource_type="folder",
            resource_id=folder.id,
            metadata={"subject_type": subject_type, "subject_id": str(subject_id), "deny": deny},
            request_id=self.ctx.request_id,
        )
        await persist_authz_bump(self.session, self.ctx.require_tenant())
        return await self._grant_payload(grant)

    async def delete_grant(self, folder_id: UUID, grant_id: UUID) -> dict:
        folder = await self._get_folder(folder_id)
        if not await self._can_share(folder):
            raise ForbiddenError("Missing permission folders.share")
        grant = await self.session.get(ResourcePermission, grant_id)
        if (
            grant is None
            or grant.tenant_id != self.ctx.tenant_id
            or grant.resource_type != "folder"
            or grant.resource_id != folder.id
        ):
            raise NotFoundError("Grant not found")
        await self.session.delete(grant)
        await self.session.flush()
        await self._compile_and_apply(folder)
        await write_audit(
            self.session,
            tenant_id=self.ctx.tenant_id,
            actor_user_id=self.ctx.user_id,
            action="folder.unshare",
            resource_type="folder",
            resource_id=folder.id,
            metadata={"grant_id": str(grant_id)},
            request_id=self.ctx.request_id,
        )
        await persist_authz_bump(self.session, self.ctx.require_tenant())
        return {"ok": True}

    async def list_shares(self, folder_id: UUID) -> list[dict]:
        folder = await self._get_folder(folder_id)
        if not await self._can_view(folder):
            raise NotFoundError("Folder not found")
        return await self._grants_payload(folder.id)

    async def _get_folder(self, folder_id: UUID) -> Folder:
        folder = await self.session.get(Folder, folder_id)
        if folder is None or folder.tenant_id != self.ctx.tenant_id:
            raise NotFoundError("Folder not found")
        return folder

    def _has_exact(self, permission: str) -> bool:
        return permission in self.ctx.permissions

    def _tenant_wide(self, permission: str) -> bool:
        # document:write aliases must not grant tenant-wide folder mutation.
        return self._has_exact(permission) and self._has_exact("folders.view")

    async def _can_view(self, folder: Folder) -> bool:
        if self._has_exact("folders.view"):
            return True
        if self.ctx.user_id and folder.owner_user_id == self.ctx.user_id:
            return True
        return await self._has_action(folder, "view")

    async def _can_edit(self, folder: Folder) -> bool:
        if self.ctx.user_id and folder.owner_user_id == self.ctx.user_id:
            return True
        if await self._has_action(folder, "edit"):
            return True
        return self._tenant_wide("folders.update")

    async def _can_delete(self, folder: Folder) -> bool:
        if self.ctx.user_id and folder.owner_user_id == self.ctx.user_id:
            return True
        if await self._has_action(folder, "delete"):
            return True
        return self._tenant_wide("folders.delete")

    async def _can_share(self, folder: Folder) -> bool:
        if self.ctx.user_id and folder.owner_user_id == self.ctx.user_id:
            return True
        if await self._has_action(folder, "share"):
            return True
        return self._tenant_wide("folders.share")

    async def _has_action(self, folder: Folder, action: str) -> bool:
        if self.ctx.user_id is None:
            return False
        chain = await self._chain(folder)
        grants = (
            await self.session.scalars(
                select(ResourcePermission).where(
                    ResourcePermission.tenant_id == self.ctx.tenant_id,
                    ResourcePermission.resource_type == "folder",
                    ResourcePermission.resource_id.in_(chain),
                )
            )
        ).all()
        role_ids = await self._ctx_role_ids()
        denied = False
        allowed = False
        for grant in grants:
            if action not in (grant.actions or []) and grant.actions:
                continue
            matches = False
            if grant.subject_type == "user" and grant.subject_id == self.ctx.user_id:
                matches = True
            elif grant.subject_type == "role" and grant.subject_id in role_ids:
                matches = True
            if not matches:
                continue
            if grant.deny:
                denied = True
            else:
                allowed = True
        return allowed and not denied

    async def _ctx_role_ids(self) -> set[UUID]:
        if not self.ctx.role_names:
            return set()
        rows = (
            await self.session.scalars(
                select(Role).where(
                    Role.tenant_id == self.ctx.tenant_id, Role.name.in_(list(self.ctx.role_names))
                )
            )
        ).all()
        return {r.id for r in rows}

    async def _chain(self, folder: Folder) -> list[UUID]:
        ids = [folder.id]
        current = folder
        seen = {folder.id}
        while current.parent_id:
            if current.parent_id in seen:
                break
            parent = await self.session.get(Folder, current.parent_id)
            if parent is None or parent.tenant_id != self.ctx.tenant_id:
                break
            ids.append(parent.id)
            seen.add(parent.id)
            current = parent
        return ids

    async def _is_descendant(self, folder: Folder, ancestor_id: UUID) -> bool:
        current = folder
        seen: set[UUID] = set()
        while current.parent_id:
            if current.parent_id == ancestor_id:
                return True
            if current.parent_id in seen:
                return False
            seen.add(current.parent_id)
            parent = await self.session.get(Folder, current.parent_id)
            if parent is None:
                return False
            current = parent
        return False

    async def _subtree_ids(self, folder: Folder) -> list[UUID]:
        ids = [folder.id]
        pending = [folder.id]
        while pending:
            current = pending.pop()
            children = (
                await self.session.scalars(select(Folder).where(Folder.parent_id == current))
            ).all()
            for child in children:
                ids.append(child.id)
                pending.append(child.id)
        return ids

    async def _compile_acl_extra(self, folder: Folder) -> dict:
        allowed_users: list[str] = []
        allowed_roles: list[str] = []
        denied_users: list[str] = []
        denied_roles: list[str] = []
        chain = await self._chain(folder)
        grants = (
            await self.session.scalars(
                select(ResourcePermission).where(
                    ResourcePermission.tenant_id == self.ctx.tenant_id,
                    ResourcePermission.resource_type == "folder",
                    ResourcePermission.resource_id.in_(chain),
                )
            )
        ).all()
        for grant in grants:
            actions = grant.actions or []
            affects_read = "view" in actions or not actions
            if grant.subject_type == "user":
                key = str(grant.subject_id)
                if grant.deny and affects_read:
                    denied_users.append(key)
                elif affects_read:
                    allowed_users.append(key)
            elif grant.subject_type == "role":
                role = await self.session.get(Role, grant.subject_id)
                if role is None:
                    continue
                if grant.deny and affects_read:
                    denied_roles.append(role.name)
                elif affects_read:
                    allowed_roles.append(role.name)
        return {
            "allowed_users": allowed_users,
            "allowed_roles": allowed_roles,
            "denied_users": denied_users,
            "denied_roles": denied_roles,
        }

    def _merge_folder_extra(self, existing: dict, owner_id: UUID | str, extra: dict) -> dict:
        prior_users = {str(x) for x in (existing.get("folder_grant_users") or [])}
        prior_roles = {str(x) for x in (existing.get("folder_grant_roles") or [])}
        prior_denied_users = {str(x) for x in (existing.get("folder_grant_denied_users") or [])}
        prior_denied_roles = {str(x) for x in (existing.get("folder_grant_denied_roles") or [])}
        base = owner_acl(owner_id)
        base["visibility"] = existing.get("visibility") or "private"
        base["allowed_groups"] = list(existing.get("allowed_groups") or [])
        base["denied_groups"] = list(existing.get("denied_groups") or [])
        base["allowed_users"] = [u for u in _str_list(existing.get("allowed_users")) if u not in prior_users]
        base["allowed_roles"] = [r for r in _str_list(existing.get("allowed_roles")) if r not in prior_roles]
        base["denied_users"] = [u for u in _str_list(existing.get("denied_users")) if u not in prior_denied_users]
        base["denied_roles"] = [r for r in _str_list(existing.get("denied_roles")) if r not in prior_denied_roles]
        compiled = inherit_acl(base, owner_id, extra)
        compiled["folder_grant_users"] = list(extra.get("allowed_users") or [])
        compiled["folder_grant_roles"] = list(extra.get("allowed_roles") or [])
        compiled["folder_grant_denied_users"] = list(extra.get("denied_users") or [])
        compiled["folder_grant_denied_roles"] = list(extra.get("denied_roles") or [])
        return compiled

    async def _compile_and_apply(self, folder: Folder) -> None:
        extra = await self._compile_acl_extra(folder)
        folder_ids = await self._subtree_ids(folder)
        docs = (
            await self.session.scalars(select(Document).where(Document.folder_id.in_(folder_ids)))
        ).all()
        for doc in docs:
            owner_id = doc.owner_user_id
            if owner_id is None:
                continue
            doc.acl = self._merge_folder_extra(doc.acl or {}, owner_id, extra)
            flag_modified(doc, "acl")
        subs = (
            await self.session.scalars(
                select(SourceSubscription).where(SourceSubscription.folder_id.in_(folder_ids))
            )
        ).all()
        for sub in subs:
            owner_id = None
            existing = sub.acl or {}
            if existing.get("owner_id"):
                try:
                    owner_id = UUID(str(existing["owner_id"]))
                except ValueError:
                    owner_id = None
            if owner_id is None:
                continue
            sub.acl = self._merge_folder_extra(existing, owner_id, extra)
            flag_modified(sub, "acl")

    async def _listable_folder_ids(self, *, limit: int, offset: int) -> list[UUID]:
        if self.ctx.user_id is None:
            return []
        tenant = self.ctx.require_tenant()
        role_ids = await self._ctx_role_ids()
        grant_filter = [
            (ResourcePermission.subject_type == "user") & (ResourcePermission.subject_id == self.ctx.user_id)
        ]
        if role_ids:
            grant_filter.append(
                (ResourcePermission.subject_type == "role") & (ResourcePermission.subject_id.in_(list(role_ids)))
            )
        grants = (
            await self.session.scalars(
                select(ResourcePermission.resource_id).where(
                    ResourcePermission.tenant_id == tenant,
                    ResourcePermission.resource_type == "folder",
                    ResourcePermission.deny.is_(False),
                    or_(*grant_filter),
                )
            )
        ).all()
        owned = (
            await self.session.scalars(
                select(Folder.id).where(Folder.tenant_id == tenant, Folder.owner_user_id == self.ctx.user_id)
            )
        ).all()
        seeds = set(grants) | set(owned)
        if not seeds:
            return []
        visible = set(seeds)
        pending = list(seeds)
        while pending:
            children = (
                await self.session.scalars(select(Folder.id).where(Folder.parent_id.in_(pending)))
            ).all()
            pending = [cid for cid in children if cid not in visible]
            visible.update(pending)
        rows = (
            await self.session.scalars(
                select(Folder.id)
                .where(Folder.tenant_id == tenant, Folder.id.in_(list(visible)))
                .order_by(Folder.created_at.desc(), Folder.id)
                .offset(offset)
                .limit(limit)
            )
        ).all()
        return list(rows)

    async def _resolve_subject(
        self,
        subject_type: str,
        *,
        email: str | None,
        user_id: UUID | None,
        role_id: UUID | None,
        role_name: str | None,
    ) -> UUID:
        if subject_type == "user":
            user = None
            if user_id:
                user = await self.session.get(User, user_id)
            elif email:
                user = await self.session.scalar(select(User).where(User.email == email.strip().lower()))
            else:
                raise ValidationFailedError("email or user_id is required")
            if user is None:
                raise ValidationFailedError("User is not in this tenant")
            membership = await self.session.scalar(
                select(TenantMembership).where(
                    TenantMembership.tenant_id == self.ctx.tenant_id,
                    TenantMembership.user_id == user.id,
                )
            )
            if membership is None:
                raise ValidationFailedError("User is not in this tenant")
            return user.id
        role = None
        if role_id:
            role = await self.session.get(Role, role_id)
        elif role_name:
            role = await self.session.scalar(
                select(Role).where(Role.tenant_id == self.ctx.tenant_id, Role.name == role_name)
            )
        else:
            raise ValidationFailedError("role_id or role_name is required")
        if role is None or role.tenant_id != self.ctx.tenant_id:
            raise NotFoundError("Role not found")
        return role.id

    async def _document_count(self, folder_id: UUID) -> int:
        value = await self.session.scalar(
            select(func.count())
            .select_from(Document)
            .where(
                Document.folder_id == folder_id,
                Document.external_status == "active",
            )
        )
        return int(value or 0)

    async def _grants_payload(self, folder_id: UUID) -> list[dict]:
        grants = (
            await self.session.scalars(
                select(ResourcePermission).where(
                    ResourcePermission.tenant_id == self.ctx.tenant_id,
                    ResourcePermission.resource_type == "folder",
                    ResourcePermission.resource_id == folder_id,
                )
            )
        ).all()
        return [await self._grant_payload(g) for g in grants]

    async def _grant_payload(self, grant: ResourcePermission) -> dict:
        email = None
        role_name = None
        if grant.subject_type == "user":
            user = await self.session.get(User, grant.subject_id)
            email = user.email if user else None
        elif grant.subject_type == "role":
            role = await self.session.get(Role, grant.subject_id)
            role_name = role.name if role else None
        return {
            "id": str(grant.id),
            "subject_type": grant.subject_type,
            "subject_id": str(grant.subject_id),
            "email": email,
            "role_name": role_name,
            "actions": list(grant.actions or []),
            "deny": grant.deny,
        }

    async def _summary(self, folder: Folder) -> dict:
        return {
            "id": str(folder.id),
            "name": folder.name,
            "parent_id": str(folder.parent_id) if folder.parent_id else None,
            "workspace_id": str(folder.workspace_id),
            "owner_user_id": str(folder.owner_user_id) if folder.owner_user_id else None,
        }
