from __future__ import annotations

import json
from typing import Any
from uuid import UUID

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.context import RequestContext
from app.core.errors import NotFoundError, ValidationFailedError
from app.domain.types import VectorFilter

_ACL_LIST_KEYS = (
    "allowed_users",
    "allowed_groups",
    "allowed_roles",
    "denied_users",
    "denied_groups",
    "denied_roles",
)


def owner_acl(user_id: UUID | str) -> dict:
    uid = str(user_id)
    return {
        "owner_id": uid,
        "visibility": "private",
        "allowed_users": [uid],
        "allowed_groups": [],
        "allowed_roles": [],
        "denied_users": [],
        "denied_groups": [],
        "denied_roles": [],
    }


def _str_list(values: Any) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for item in values or []:
        text = str(item)
        if text and text not in seen:
            out.append(text)
            seen.add(text)
    return out


def merge_acl(base: dict, extra: dict | None) -> dict:
    """Merge subscription/share grants onto an owner ACL. Empty extra is ignored."""
    owner = base.get("owner_id")
    merged = owner_acl(owner) if owner else {
        "owner_id": None,
        "visibility": "private",
        "allowed_users": [],
        "allowed_groups": [],
        "allowed_roles": [],
        "denied_users": [],
        "denied_groups": [],
        "denied_roles": [],
    }
    merged["visibility"] = base.get("visibility") or "private"
    for key in _ACL_LIST_KEYS:
        merged[key] = _str_list(base.get(key))
    if not extra:
        return merged
    if extra.get("visibility"):
        merged["visibility"] = str(extra["visibility"])
    for key in _ACL_LIST_KEYS:
        merged[key] = _str_list(list(merged[key]) + list(extra.get(key) or []))
    if owner and str(owner) not in merged["allowed_users"]:
        merged["allowed_users"] = [str(owner), *merged["allowed_users"]]
    return merged


def inherit_acl(existing: dict | None, owner_id: UUID | str, incoming: dict | None) -> dict:
    """Keep document-level shares when folder/subscription ACL is reapplied on sync."""
    base = existing if existing and (existing.get("owner_id") or existing.get("allowed_users")) else owner_acl(owner_id)
    return merge_acl(base, incoming)


def apply_acl_patch(owner_id: UUID | str, current: dict | None, patch: dict) -> dict:
    """Replace provided grant fields while keeping the owner. Omitted fields stay as-is."""
    src = current if current and (current.get("owner_id") or current.get("allowed_users")) else owner_acl(owner_id)
    result = owner_acl(owner_id)
    result["visibility"] = str(patch["visibility"]) if patch.get("visibility") else (src.get("visibility") or "private")
    for key in _ACL_LIST_KEYS:
        if key in patch and patch[key] is not None:
            result[key] = _str_list(patch[key])
        else:
            result[key] = _str_list(src.get(key))
    oid = str(owner_id)
    result["owner_id"] = oid
    if oid not in result["allowed_users"]:
        result["allowed_users"] = [oid, *result["allowed_users"]]
    return result


def can_read_document(acl: dict | None, ctx: RequestContext) -> bool:
    if not ctx.has("document:read"):
        return False
    if ctx.has("document:read_all"):
        return True
    if ctx.user_id is None:
        return False
    if not acl:
        return False
    uid = str(ctx.user_id)
    denied_users = {str(x) for x in (acl.get("denied_users") or [])}
    denied_groups = {str(x) for x in (acl.get("denied_groups") or [])}
    denied_roles = {str(x) for x in (acl.get("denied_roles") or [])}
    if uid in denied_users:
        return False
    if denied_groups.intersection(ctx.team_names):
        return False
    if denied_roles.intersection(ctx.role_names):
        return False
    if acl.get("owner_id") and str(acl["owner_id"]) == uid:
        return True
    if acl.get("visibility") == "tenant":
        return True
    allowed_users = {str(x) for x in (acl.get("allowed_users") or [])}
    if uid in allowed_users:
        return True
    allowed_groups = {str(x) for x in (acl.get("allowed_groups") or [])}
    if allowed_groups.intersection(ctx.team_names):
        return True
    allowed_roles = {str(x) for x in (acl.get("allowed_roles") or [])}
    if allowed_roles.intersection(ctx.role_names):
        return True
    return False


def can_manage_source(source: Any, ctx: RequestContext) -> bool:
    if ctx.has("source:admin"):
        return True
    owner = getattr(source, "owner_user_id", None)
    return bool(ctx.has("source:manage") and owner is not None and ctx.user_id is not None and owner == ctx.user_id)


def can_share_document(document: Any, ctx: RequestContext) -> bool:
    if ctx.has("source:admin"):
        return True
    if not ctx.has("document:write"):
        return False
    owner = getattr(document, "owner_user_id", None)
    if owner is not None and ctx.user_id is not None and owner == ctx.user_id:
        return True
    acl = getattr(document, "acl", None) or {}
    return bool(ctx.user_id and str(acl.get("owner_id") or "") == str(ctx.user_id))


def document_acl_sql(alias: str = "d") -> str:
    """SQL matching can_read_document. Bind params from document_acl_params(). Fail closed without user_id unless read_all."""
    a = alias
    teams = "COALESCE(ARRAY(SELECT jsonb_array_elements_text(CAST(:acl_team_names AS jsonb))), ARRAY[]::text[])"
    roles = "COALESCE(ARRAY(SELECT jsonb_array_elements_text(CAST(:acl_role_names AS jsonb))), ARRAY[]::text[])"
    return f"""
              AND (
                CAST(:acl_read_all AS boolean)
                OR (
                  CAST(:acl_user_id AS text) IS NOT NULL
                  AND {a}.acl IS NOT NULL
                  AND jsonb_typeof({a}.acl) = 'object'
                  AND {a}.acl <> '{{}}'::jsonb
                  AND NOT (
                    jsonb_exists(COALESCE({a}.acl->'denied_users', '[]'::jsonb), CAST(:acl_user_id AS text))
                    OR jsonb_exists_any(COALESCE({a}.acl->'denied_groups', '[]'::jsonb), {teams})
                    OR jsonb_exists_any(COALESCE({a}.acl->'denied_roles', '[]'::jsonb), {roles})
                  )
                  AND (
                    ({a}.acl->>'owner_id') = CAST(:acl_user_id AS text)
                    OR ({a}.acl->>'visibility') = 'tenant'
                    OR jsonb_exists(COALESCE({a}.acl->'allowed_users', '[]'::jsonb), CAST(:acl_user_id AS text))
                    OR jsonb_exists_any(COALESCE({a}.acl->'allowed_groups', '[]'::jsonb), {teams})
                    OR jsonb_exists_any(COALESCE({a}.acl->'allowed_roles', '[]'::jsonb), {roles})
                  )
                )
              )
    """


def document_acl_params(filters: VectorFilter | RequestContext) -> dict:
    if isinstance(filters, RequestContext):
        user_id = filters.user_id
        team_names = list(filters.team_names or ())
        role_names = list(filters.role_names or ())
        read_all = filters.has("document:read_all")
    else:
        user_id = filters.user_id
        team_names = list(filters.team_names or [])
        role_names = list(filters.role_names or [])
        read_all = bool(filters.read_all)
    return {
        "acl_user_id": str(user_id) if user_id else None,
        "acl_team_names": json.dumps(team_names),
        "acl_role_names": json.dumps(role_names),
        "acl_read_all": read_all,
    }


def retrieval_filter(ctx: RequestContext, **kwargs) -> VectorFilter:
    return VectorFilter(
        tenant_id=ctx.require_tenant(),
        user_id=ctx.user_id,
        team_names=list(ctx.team_names or ()),
        role_names=list(ctx.role_names or ()),
        read_all=ctx.has("document:read_all"),
        principal_ids=list(ctx.principal_ids or ()),
        **kwargs,
    )


async def authorized_document_ids(
    session: AsyncSession,
    ctx: RequestContext,
    *,
    workspace_id: UUID | None = None,
    limit: int | None = None,
    offset: int | None = None,
) -> list[UUID]:
    """Document ids the caller may read, authorized in SQL (empty ACL deny, live docs only)."""
    sql = f"""
        SELECT d.id
        FROM documents d
        WHERE d.tenant_id = :tenant
          AND d.external_status = 'active'
          {document_acl_sql("d")}
    """
    params: dict = {"tenant": str(ctx.require_tenant())}
    if workspace_id is not None:
        sql += " AND d.workspace_id = :workspace"
        params["workspace"] = str(workspace_id)
    params.update(document_acl_params(ctx))
    sql += " ORDER BY d.created_at DESC, d.id"
    if limit is not None:
        sql += " OFFSET :offset LIMIT :limit"
        params["offset"] = max(0, int(offset or 0))
        params["limit"] = max(1, int(limit))
    rows = (await session.execute(text(sql), params)).all()
    return [row[0] for row in rows]


async def assert_workspace_access(session: AsyncSession, ctx: RequestContext, workspace_id: UUID) -> None:
    from app.adapters.db.models import Workspace

    workspace = await session.get(Workspace, workspace_id)
    if workspace is None or workspace.tenant_id != ctx.tenant_id:
        raise NotFoundError("Workspace not found")


async def assert_version_readable(session: AsyncSession, ctx: RequestContext, version_id: UUID) -> None:
    from app.adapters.db.models import Document, DocumentVersion

    version = await session.get(DocumentVersion, version_id)
    if version is None:
        raise NotFoundError("Document not found")
    document = await session.get(Document, version.document_id)
    from app.application.connectors import document_is_live

    if (
        document is None
        or not can_read_document(document.acl or {}, ctx)
        or not document_is_live(document)
    ):
        raise NotFoundError("Document not found")


async def resolve_share_user_ids(
    session: AsyncSession,
    ctx: RequestContext,
    *,
    user_ids: list[UUID] | None = None,
    emails: list[str] | None = None,
) -> list[str]:
    from app.adapters.db.models import TenantMembership, User

    resolved = _str_list(user_ids)
    for raw in emails or []:
        email = str(raw).strip().lower()
        if not email:
            continue
        user = await session.scalar(select(User).where(User.email == email))
        membership = None
        if user is not None:
            membership = await session.scalar(
                select(TenantMembership).where(
                    TenantMembership.tenant_id == ctx.tenant_id,
                    TenantMembership.user_id == user.id,
                )
            )
        if user is None or membership is None:
            raise ValidationFailedError(f"User {email} is not in this tenant")
        if str(user.id) not in resolved:
            resolved.append(str(user.id))
    return resolved
