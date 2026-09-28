from uuid import uuid4

from app.application.authz import (
    can_manage_source,
    can_read_document,
    document_acl_sql,
    inherit_acl,
    merge_acl,
    owner_acl,
)
from app.application.ingestion import _visible
from app.application.rbac import SYSTEM_ROLES
from app.core.context import RequestContext


def _ctx(**kwargs) -> RequestContext:
    defaults = {
        "request_id": "t",
        "user_id": uuid4(),
        "permissions": frozenset({"document:read"}),
        "team_names": (),
        "role_names": (),
    }
    defaults.update(kwargs)
    return RequestContext(**defaults)


def test_restricted_acl_never_visible_to_other_user():
    owner = uuid4()
    other = uuid4()
    ctx = _ctx(user_id=other)
    assert not _visible({"allowed_users": [str(owner)], "owner_id": str(owner)}, ctx)


def test_empty_acl_is_denied_even_with_document_read():
    ctx = _ctx()
    assert not _visible({}, ctx)
    assert not can_read_document({}, ctx)
    assert not can_read_document(None, ctx)


def test_missing_read_permission_hides_even_empty_acl():
    ctx = _ctx(permissions=frozenset())
    assert not _visible({}, ctx)


def test_owner_can_read_private_acl():
    owner = uuid4()
    ctx = _ctx(user_id=owner)
    assert can_read_document(owner_acl(owner), ctx)


def test_other_user_cannot_read_owner_acl():
    owner = uuid4()
    ctx = _ctx(user_id=uuid4())
    assert not can_read_document(owner_acl(owner), ctx)


def test_inherit_acl_keeps_document_share_across_folder_reapply():
    owner = uuid4()
    other = uuid4()
    current = owner_acl(owner)
    current["allowed_users"].append(str(other))
    folder = owner_acl(owner)
    combined = inherit_acl(current, owner, folder)
    assert str(other) in combined["allowed_users"]
    assert str(owner) in combined["allowed_users"]


def test_visibility_tenant_is_readable_by_any_tenant_member():
    owner = uuid4()
    acl = owner_acl(owner)
    acl["visibility"] = "tenant"
    ctx = _ctx(user_id=uuid4())
    assert can_read_document(acl, ctx)


def test_explicit_deny_wins_for_non_admin():
    owner = uuid4()
    other = uuid4()
    acl = owner_acl(owner)
    acl["allowed_users"].append(str(other))
    acl["denied_users"] = [str(other)]
    ctx = _ctx(user_id=other)
    assert not can_read_document(acl, ctx)


def test_role_grant_allows_matching_role():
    owner = uuid4()
    acl = owner_acl(owner)
    acl["allowed_roles"] = ["Manager"]
    ctx = _ctx(user_id=uuid4(), role_names=("Manager", "Member"))
    assert can_read_document(acl, ctx)
    ctx2 = _ctx(user_id=uuid4(), role_names=("Member",))
    assert not can_read_document(acl, ctx2)


def test_group_grant_allows_matching_team():
    owner = uuid4()
    acl = owner_acl(owner)
    acl["allowed_groups"] = ["Engineering"]
    ctx = _ctx(user_id=uuid4(), team_names=("Engineering",))
    assert can_read_document(acl, ctx)
    ctx2 = _ctx(user_id=uuid4(), team_names=("Sales",))
    assert not can_read_document(acl, ctx2)


def test_admin_read_all_bypasses_empty_and_private_acl():
    admin = _ctx(permissions=frozenset({"document:read", "document:read_all"}))
    assert can_read_document({}, admin)
    assert can_read_document(owner_acl(uuid4()), admin)


def test_merge_acl_ignores_empty_extra():
    owner = uuid4()
    base = owner_acl(owner)
    assert merge_acl(base, {})["allowed_users"] == [str(owner)]
    assert merge_acl(base, None)["owner_id"] == str(owner)


def test_can_manage_source_is_owner_or_admin():
    owner = uuid4()
    other = uuid4()

    class Src:
        def __init__(self, owner_user_id):
            self.owner_user_id = owner_user_id

    source = Src(owner)
    member_owner = RequestContext(
        request_id="t", user_id=owner, permissions=frozenset({"source:manage"})
    )
    member_other = RequestContext(
        request_id="t", user_id=other, permissions=frozenset({"source:manage"})
    )
    admin = RequestContext(
        request_id="t", user_id=other, permissions=frozenset({"source:admin"})
    )
    assert can_manage_source(source, member_owner)
    assert not can_manage_source(source, member_other)
    assert can_manage_source(source, admin)


def test_document_acl_sql_matches_python_semantics():
    sql = document_acl_sql("d")
    assert "denied_users" in sql
    assert "owner_id" in sql
    assert "visibility" in sql
    assert "acl_read_all" in sql
    assert "{}'::jsonb" in sql


def test_admin_only_permissions_are_not_on_member():
    assert "document:read_all" in SYSTEM_ROLES["Tenant Admin"]
    assert "source:admin" in SYSTEM_ROLES["Tenant Admin"]
    from app.application.rbac import DEFAULT_ROLES

    assert "document:read_all" not in DEFAULT_ROLES["Member"]
    assert "source:admin" not in DEFAULT_ROLES["Member"]
    assert "source:manage" in DEFAULT_ROLES["Member"]
