from __future__ import annotations

import logging
import os

from app.config.models import PlatformSettings
from app.config.secrets import is_secret_ref
from app.core.errors import ConfigError
from app.core.flags import allow_public_signup

log = logging.getLogger("runtime")

_WEAK_JWT = frozenset(
    {
        "",
        "secret",
        "jwt_secret",
        "changeme",
        "change-me",
        "change-me-to-a-long-random-string",
        "secret://env/JWT_SECRET",
    }
)


class RuntimeSafetyError(ConfigError):
    code = "runtime_safety"
    status_code = 500


def resolved_jwt_secret(raw: str) -> str:
    if is_secret_ref(raw):
        return os.environ.get("JWT_SECRET", "").strip()
    return (raw or "").strip()


def jwt_secret_is_unsafe(raw: str) -> bool:
    value = resolved_jwt_secret(raw)
    if len(value) < 32:
        return True
    lowered = value.lower()
    if lowered in _WEAK_JWT or "change-me" in lowered:
        return True
    return False


def cors_origins_unsafe(origins: list[str]) -> bool:
    return any(str(item).strip() == "*" for item in origins)


def enforce_runtime_safety(settings: PlatformSettings) -> None:
    """Fail closed in production; warn in other environments for the same class of mistakes."""
    environment = (settings.platform.environment or "").strip().lower()
    production = environment == "production"
    problems: list[str] = []
    if allow_public_signup():
        problems.append("RAG_ALLOW_PUBLIC_SIGNUP is enabled")
    if jwt_secret_is_unsafe(settings.auth.jwt_secret):
        problems.append("JWT secret is missing, too short, or a placeholder")
    if cors_origins_unsafe(list(settings.http.cors_origins)):
        problems.append("CORS allowlist contains wildcard *")
    if not problems:
        return
    message = "; ".join(problems)
    if production:
        raise RuntimeSafetyError(f"Refusing to start in production: {message}")
    log.warning("runtime_safety_warning: %s", message)
