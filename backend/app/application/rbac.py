from __future__ import annotations

from app.core.permissions import TENANT_ADMIN_ROLE

OLD_PERMISSIONS = (
    "document:read",
    "document:read_all",
    "document:write",
    "document:delete",
    "conversation:read",
    "conversation:write",
    "conversation:delete",
    "source:manage",
    "source:admin",
    "user:manage",
    "config:read",
    "config:write",
    "job:read",
    "audit:read",
    "workspace:manage",
    "team:manage",
)

NEW_PERMISSIONS = (
    "users.view",
    "users.create",
    "users.update",
    "users.disable",
    "roles.view",
    "roles.create",
    "roles.update",
    "roles.delete",
    "roles.assign",
    "folders.view",
    "folders.create",
    "folders.update",
    "folders.delete",
    "folders.share",
    "documents.view",
    "documents.upload",
    "documents.update",
    "documents.delete",
    "documents.share",
    "ai.chat",
    "ai.configuration.view",
    "ai.configuration.update",
    "audit.view",
    "tenant.settings.view",
    "tenant.settings.update",
)

ALL_PERMISSIONS = OLD_PERMISSIONS + NEW_PERMISSIONS

# Tenant Admin follows document ACLs by default (no automatic private-doc bypass).
# document:read_all remains in the catalog for explicit break-glass grants.
TENANT_ADMIN_PERMISSIONS = tuple(code for code in ALL_PERMISSIONS if code != "document:read_all")

PERMISSION_DESCRIPTIONS: dict[str, str] = {
    "document:read": "Read documents and retrieved chunks",
    "document:read_all": "Read all documents in the tenant regardless of ACL",
    "document:write": "Upload or update documents",
    "document:delete": "Delete documents",
    "conversation:read": "Read conversations",
    "conversation:write": "Create messages",
    "conversation:delete": "Delete conversations",
    "source:manage": "Connect and sync data sources",
    "source:admin": "Administer all connectors in the tenant",
    "user:manage": "Manage users, teams, and roles",
    "config:read": "Read effective configuration",
    "config:write": "Update tenant/workspace configuration",
    "job:read": "View ingestion jobs",
    "audit:read": "Read audit logs",
    "workspace:manage": "Manage workspaces",
    "team:manage": "Manage teams",
    "users.view": "View tenant users",
    "users.create": "Invite tenant users",
    "users.update": "Update tenant users",
    "users.disable": "Disable or enable tenant users",
    "roles.view": "View roles",
    "roles.create": "Create roles",
    "roles.update": "Update roles",
    "roles.delete": "Delete roles",
    "roles.assign": "Assign roles to users",
    "folders.view": "View all folders in the tenant",
    "folders.create": "Create folders",
    "folders.update": "Update folders",
    "folders.delete": "Delete folders",
    "folders.share": "Share folders",
    "documents.view": "View documents",
    "documents.upload": "Upload documents",
    "documents.update": "Update documents",
    "documents.delete": "Delete documents",
    "documents.share": "Share documents",
    "ai.chat": "Use AI chat",
    "ai.configuration.view": "View tenant AI configuration",
    "ai.configuration.update": "Update tenant AI configuration",
    "audit.view": "View audit logs",
    "tenant.settings.view": "View tenant settings",
    "tenant.settings.update": "Update tenant settings",
}

# The only system tenant role. Platform super_admin is users.is_super_admin, not a tenant role.
SYSTEM_ROLES: dict[str, tuple[str, ...]] = {
    TENANT_ADMIN_ROLE: TENANT_ADMIN_PERMISSIONS,
}

# Non-system defaults so existing Member invites keep working. Not is_system.
DEFAULT_ROLES: dict[str, tuple[str, ...]] = {
    "Member": (
        "document:read",
        "document:write",
        "conversation:read",
        "conversation:write",
        "conversation:delete",
        "source:manage",
        "job:read",
        "config:read",
        "documents.view",
        "documents.upload",
        "documents.update",
        "documents.share",
        "folders.create",
        "folders.share",
        "ai.chat",
        "ai.configuration.view",
    ),
    "Viewer": (
        "document:read",
        "conversation:read",
        "config:read",
        "documents.view",
        "ai.chat",
        "ai.configuration.view",
    ),
}

SEED_ROLES: dict[str, tuple[str, ...]] = {**SYSTEM_ROLES, **DEFAULT_ROLES}
