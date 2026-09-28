from __future__ import annotations

import hashlib
import hmac
import os
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError

from app.config.secrets import is_secret_ref, resolve_secret
from app.core.errors import UnauthenticatedError

_hasher = PasswordHasher()


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password: str, password_hash: str | None) -> bool:
    if not password_hash:
        return False
    try:
        return _hasher.verify(password_hash, password)
    except VerifyMismatchError:
        return False


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def resolve_jwt_secret(raw: str) -> str:
    if is_secret_ref(raw):
        return resolve_secret(raw)
    return raw


def issue_jwt(
    *,
    secret: str,
    user_id: UUID,
    tenant_id: UUID | None,
    token_type: str,
    ttl_seconds: int,
    workspace_id: UUID | None = None,
    is_super_admin: bool = False,
) -> str:
    now = datetime.now(UTC)
    payload: dict[str, Any] = {
        "sub": str(user_id),
        "typ": token_type,
        "jti": str(uuid4()),
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(seconds=ttl_seconds)).timestamp()),
    }
    if tenant_id is not None:
        payload["tid"] = str(tenant_id)
    if workspace_id:
        payload["wid"] = str(workspace_id)
    if is_super_admin:
        payload["sa"] = True
    return jwt.encode(payload, secret, algorithm="HS256")


def decode_jwt(token: str, secret: str, *, expected_type: str | None = None) -> dict[str, Any]:
    try:
        payload = jwt.decode(
            token,
            secret,
            algorithms=["HS256"],
            options={"require": ["exp", "sub", "typ"]},
        )
    except jwt.PyJWTError as exc:
        raise UnauthenticatedError("Invalid or expired token") from exc
    if expected_type and payload.get("typ") != expected_type:
        raise UnauthenticatedError("Invalid token type")
    return payload


def constant_time_equals(left: str, right: str) -> bool:
    return hmac.compare_digest(left, right)


def new_refresh_token() -> str:
    return os.urandom(32).hex()
