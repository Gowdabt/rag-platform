import base64
import json
from uuid import uuid4

import jwt
import pytest
from app.core.errors import UnauthenticatedError
from app.core.security import decode_jwt, hash_password, issue_jwt, verify_password


def test_password_hash_roundtrip():
    hashed = hash_password("correct-horse-battery")
    assert verify_password("correct-horse-battery", hashed)
    assert not verify_password("wrong-password", hashed)


def test_jwt_roundtrip_and_type_check():
    secret = "x" * 32
    user = uuid4()
    tenant = uuid4()
    token = issue_jwt(secret=secret, user_id=user, tenant_id=tenant, token_type="access", ttl_seconds=60)
    payload = decode_jwt(token, secret, expected_type="access")
    assert payload["sub"] == str(user)
    assert payload["tid"] == str(tenant)
    assert "permissions" not in payload
    try:
        decode_jwt(token, secret, expected_type="refresh")
        assert False
    except UnauthenticatedError:
        pass


def test_jwt_rejects_none_and_non_hs256():
    secret = "x" * 32
    user = uuid4()
    tenant = uuid4()

    def b64(raw: bytes) -> str:
        return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()

    none_token = (
        b64(b'{"alg":"none","typ":"JWT"}')
        + "."
        + b64(
            json.dumps(
                {"sub": str(user), "tid": str(tenant), "typ": "access", "exp": 2_000_000_000}
            ).encode()
        )
        + "."
    )
    with pytest.raises(UnauthenticatedError):
        decode_jwt(none_token, secret, expected_type="access")
    hs384 = jwt.encode(
        {"sub": str(user), "tid": str(tenant), "typ": "access", "exp": 2_000_000_000},
        secret,
        algorithm="HS384",
    )
    with pytest.raises(UnauthenticatedError):
        decode_jwt(hs384, secret, expected_type="access")
