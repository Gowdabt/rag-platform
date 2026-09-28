from __future__ import annotations

TENANT_ADMIN_NAMES = frozenset({"Admin", "Tenant Admin"})
TENANT_ADMIN_ROLE = "Tenant Admin"

PLATFORM_PERMISSIONS = frozenset(
    {
        "platform.tenants.view",
        "platform.tenants.create",
        "platform.tenants.update",
        "platform.ai_catalog.view",
    }
)

# Bidirectional aliases so old JWT-era codes and new catalog codes both work.
PERMISSION_ALIASES: dict[str, frozenset[str]] = {
    "document:read": frozenset({"document:read", "documents.view"}),
    "documents.view": frozenset({"documents.view", "document:read"}),
    "document:write": frozenset({"document:write", "documents.upload"}),
    "documents.upload": frozenset({"documents.upload", "document:write"}),
    "document:delete": frozenset({"document:delete", "documents.delete"}),
    "documents.delete": frozenset({"documents.delete", "document:delete"}),
    "user:manage": frozenset({"user:manage", "users.create", "users.update", "users.disable"}),
    "users.view": frozenset({"users.view", "user:manage"}),
    "users.create": frozenset({"users.create", "user:manage"}),
    "users.update": frozenset({"users.update", "user:manage"}),
    "users.disable": frozenset({"users.disable", "user:manage"}),
    "roles.view": frozenset({"roles.view", "user:manage"}),
    "roles.create": frozenset({"roles.create", "user:manage"}),
    "roles.update": frozenset({"roles.update", "user:manage"}),
    "roles.delete": frozenset({"roles.delete", "user:manage"}),
    "roles.assign": frozenset({"roles.assign", "user:manage"}),
    "config:write": frozenset({"config:write", "tenant.settings.update", "ai.configuration.update"}),
    "tenant.settings.update": frozenset({"tenant.settings.update", "config:write"}),
    "ai.configuration.update": frozenset({"ai.configuration.update", "config:write"}),
    "config:read": frozenset({"config:read", "tenant.settings.view", "ai.configuration.view"}),
    "tenant.settings.view": frozenset({"tenant.settings.view", "config:read"}),
    "ai.configuration.view": frozenset({"ai.configuration.view", "config:read"}),
    "audit:read": frozenset({"audit:read", "audit.view"}),
    "audit.view": frozenset({"audit.view", "audit:read"}),
    "conversation:write": frozenset({"conversation:write", "ai.chat"}),
    "ai.chat": frozenset({"ai.chat", "conversation:write"}),
    "folders.create": frozenset({"folders.create", "document:write"}),
    "folders.share": frozenset({"folders.share", "document:write"}),
    "folders.delete": frozenset({"folders.delete", "document:delete"}),
    "folders.update": frozenset({"folders.update", "document:write"}),
    "documents.share": frozenset({"documents.share", "document:write"}),
    "documents.update": frozenset({"documents.update", "document:write"}),
}


def permissions_include(have: frozenset[str], needed: str) -> bool:
    if needed in have:
        return True
    alts = PERMISSION_ALIASES.get(needed)
    return bool(alts and have.intersection(alts))


def is_tenant_admin_name(name: str) -> bool:
    return name in TENANT_ADMIN_NAMES


def is_tenant_admin(role_names: tuple[str, ...] | list[str]) -> bool:
    return bool(TENANT_ADMIN_NAMES.intersection(role_names))
