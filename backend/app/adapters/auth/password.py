from __future__ import annotations

from uuid import UUID

from app.config.models import AuthConfig
from app.core.context import RequestContext
from app.core.errors import UnauthenticatedError
from app.core.security import decode_jwt, issue_jwt, resolve_jwt_secret
from app.domain.ports.auth import AuthProvider
from app.domain.registry import register


@register("auth", "password")
class PasswordAuthProvider(AuthProvider):
    def __init__(self, config: AuthConfig):
        super().__init__(config)

    async def authenticate(self, username: str, password: str) -> UUID:
        raise UnauthenticatedError("Use IdentityService.login")

    async def issue_tokens(self, user_id: UUID, tenant_id: UUID) -> dict[str, str]:
        secret = resolve_jwt_secret(self.config.jwt_secret)
        access = issue_jwt(
            secret=secret,
            user_id=user_id,
            tenant_id=tenant_id,
            token_type="access",
            ttl_seconds=self.config.access_ttl_seconds,
        )
        return {"access_token": access}

    async def authenticate_request(self, token: str) -> RequestContext:
        secret = resolve_jwt_secret(self.config.jwt_secret)
        payload = decode_jwt(token, secret, expected_type="access")
        return RequestContext(
            request_id="jwt",
            tenant_id=UUID(payload["tid"]) if payload.get("tid") else None,
            user_id=UUID(payload["sub"]),
            is_super_admin=bool(payload.get("sa")),
        )
