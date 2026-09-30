from app.core.context import RequestContext
from app.core.permissions import PLATFORM_PERMISSIONS, expand_permissions, permissions_include


def test_equivalent_codes_are_interchangeable():
    assert permissions_include(frozenset({"documents.view"}), "document:read")
    assert permissions_include(frozenset({"document:read"}), "documents.view")
    assert permissions_include(frozenset({"documents.upload"}), "document:write")
    assert permissions_include(frozenset({"ai.chat"}), "conversation:write")
    assert permissions_include(frozenset({"audit.view"}), "audit:read")


def test_legacy_superset_grants_new_codes_not_reverse():
    have_manage = frozenset({"user:manage"})
    assert permissions_include(have_manage, "users.create")
    assert permissions_include(have_manage, "users.disable")
    assert permissions_include(have_manage, "roles.view")
    assert not permissions_include(frozenset({"users.create"}), "user:manage")
    assert not permissions_include(frozenset({"users.create"}), "users.disable")
    assert not permissions_include(frozenset({"users.view"}), "user:manage")
    assert not permissions_include(frozenset({"roles.create"}), "roles.delete")


def test_config_and_folder_grants_are_one_way():
    assert permissions_include(frozenset({"config:write"}), "ai.configuration.update")
    assert not permissions_include(frozenset({"ai.configuration.update"}), "config:write")
    assert not permissions_include(frozenset({"ai.configuration.view"}), "config:read")
    assert permissions_include(frozenset({"document:write"}), "folders.create")
    assert not permissions_include(frozenset({"folders.create"}), "document:write")
    assert not permissions_include(frozenset({"folders.create"}), "documents.upload")


def test_expand_permissions_does_not_invent_read_all():
    expanded = expand_permissions(frozenset({"document:read", "document:write", "users.create"}))
    assert "document:read_all" not in expanded
    assert "source:admin" not in expanded
    assert "user:manage" not in expanded


def test_super_admin_context_never_has_tenant_document_read_all():
    ctx = RequestContext(request_id="t", is_super_admin=True, permissions=frozenset())
    assert not ctx.has("document:read_all")
    assert not ctx.has("document:read")
    assert not ctx.has("user:manage")
    assert ctx.has("platform.tenants.view")
    for code in PLATFORM_PERMISSIONS:
        assert ctx.has(code)
