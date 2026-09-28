from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from uuid import UUID

from app.core.permissions import PLATFORM_PERMISSIONS, permissions_include


@dataclass(frozen=True, slots=True)
class RequestContext:
    """Security context attached to a request or worker job."""

    request_id: str
    tenant_id: UUID | None = None
    user_id: UUID | None = None
    workspace_id: UUID | None = None
    email: str | None = None
    display_name: str | None = None
    principal_ids: tuple[str, ...] = ()
    team_names: tuple[str, ...] = ()
    permissions: frozenset[str] = field(default_factory=frozenset)
    role_names: tuple[str, ...] = ()
    is_super_admin: bool = False
    last_login_at: datetime | None = None

    def require_tenant(self) -> UUID:
        if self.tenant_id is None:
            from app.core.errors import UnauthenticatedError

            raise UnauthenticatedError("Tenant is required")
        return self.tenant_id

    def has(self, permission: str) -> bool:
        # Super admin is a platform principal only — never tenant document:read_all.
        if self.is_super_admin:
            return permission in PLATFORM_PERMISSIONS or permission.startswith("platform.")
        return permissions_include(self.permissions, permission)
