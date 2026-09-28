import pytest
from app.config.secrets import is_secret_ref, resolve_secret, resolve_secrets
from app.core.errors import SecretResolutionError


def test_detects_secret_refs():
    assert is_secret_ref("secret://env/JWT_SECRET")
    assert not is_secret_ref("not-a-secret")


def test_resolve_secret_from_env(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("JWT_SECRET", "super-secret")
    assert resolve_secret("secret://env/JWT_SECRET") == "super-secret"


def test_missing_env_fails():
    try:
        resolve_secret("secret://env/DOES_NOT_EXIST_RAG")
        assert False, "expected SecretResolutionError"
    except SecretResolutionError:
        pass


def test_unsupported_scheme():
    try:
        resolve_secret("secret://vault/foo")
        assert False, "expected SecretResolutionError"
    except SecretResolutionError:
        pass


def test_resolve_nested(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("JWT_SECRET", "abc")
    out = resolve_secrets({"auth": {"jwt_secret": "secret://env/JWT_SECRET"}, "x": 1})
    assert out == {"auth": {"jwt_secret": "abc"}, "x": 1}
