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

# Same privilege, either code. Subset codes must never appear here next to a superset.
PERMISSION_EQUIVALENTS: dict[str, frozenset[str]] = {
    "document:read": frozenset({"document:read", "documents.view"}),
    "documents.view": frozenset({"document:read", "documents.view"}),
    "document:write": frozenset({"document:write", "documents.upload"}),
    "documents.upload": frozenset({"document:write", "documents.upload"}),
    "document:delete": frozenset({"document:delete", "documents.delete"}),
    "documents.delete": frozenset({"document:delete", "documents.delete"}),
    "audit:read": frozenset({"audit:read", "audit.view"}),
    "audit.view": frozenset({"audit:read", "audit.view"}),
    "conversation:write": frozenset({"conversation:write", "ai.chat"}),
    "ai.chat": frozenset({"conversation:write", "ai.chat"}),
}

# Having the key grants the values. Reverse is false (users.create is not user:manage).
PERMISSION_GRANTS: dict[str, frozenset[str]] = {
    "user:manage": frozenset(
        {
            "users.view",
            "users.create",
            "users.update",
            "users.disable",
            "roles.view",
            "roles.create",
            "roles.update",
            "roles.delete",
            "roles.assign",
        }
    ),
    "config:write": frozenset({"tenant.settings.update", "ai.configuration.update"}),
    "config:read": frozenset({"tenant.settings.view", "ai.configuration.view"}),
    "document:write": frozenset(
        {
            "documents.update",
            "documents.share",
            "folders.create",
            "folders.share",
            "folders.update",
        }
    ),
    "document:delete": frozenset({"folders.delete"}),
}

# Legacy name: equivalent pairs only. Do not put superset/subset codes in the same set.
PERMISSION_ALIASES: dict[str, frozenset[str]] = dict(PERMISSION_EQUIVALENTS)


def expand_permissions(have: frozenset[str] | set[str]) -> frozenset[str]:
    out: set[str] = set(have)
    changed = True
    while changed:
        changed = False
        snapshot = tuple(out)
        for code in snapshot:
            for peer in PERMISSION_EQUIVALENTS.get(code, ()):
                if peer not in out:
                    out.add(peer)
                    changed = True
            for granted in PERMISSION_GRANTS.get(code, ()):
                if granted not in out:
                    out.add(granted)
                    changed = True
    return frozenset(out)


def permissions_include(have: frozenset[str], needed: str) -> bool:
    if needed in have:
        return True
    return needed in expand_permissions(have)


def is_tenant_admin_name(name: str) -> bool:
    return name in TENANT_ADMIN_NAMES


def is_tenant_admin(role_names: tuple[str, ...] | list[str]) -> bool:
    return bool(TENANT_ADMIN_NAMES.intersection(role_names))
