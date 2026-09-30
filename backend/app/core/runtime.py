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


def _email_provider_name(settings: PlatformSettings) -> str:
    return (os.environ.get("EMAIL_PROVIDER") or settings.email.provider or "console").strip().lower()


def email_config_unsafe(settings: PlatformSettings) -> str | None:
    """Production-only mail configuration problems. Console is allowed outside production."""
    provider = _email_provider_name(settings)
    if provider == "console":
        return "email provider 'console' is not allowed"
    from_address = (os.environ.get("EMAIL_FROM_ADDRESS") or settings.email.from_address or "").strip().lower()
    if not from_address or from_address in {"no-reply@localhost", "noreply@localhost"}:
        return "EMAIL_FROM_ADDRESS is missing or still a localhost placeholder"
    if provider == "smtp":
        host = (os.environ.get("SMTP_HOST") or settings.email.smtp_host or "").strip()
        if not host:
            return "SMTP_HOST is required when EMAIL_PROVIDER=smtp"
    if provider == "resend":
        key = (os.environ.get("RESEND_API_KEY") or settings.email.api_key or "").strip()
        if not key:
            return "RESEND_API_KEY is required when EMAIL_PROVIDER=resend"
    public_url = (os.environ.get("PUBLIC_APP_URL") or settings.email.public_app_url or "").strip().lower()
    if not public_url or "localhost" in public_url or "127.0.0.1" in public_url:
        return "PUBLIC_APP_URL must be a public HTTPS origin in production"
    return None


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
    if production:
        email_problem = email_config_unsafe(settings)
        if email_problem:
            problems.append(email_problem)
    if not problems:
        return
    message = "; ".join(problems)
    if production:
        raise RuntimeSafetyError(f"Refusing to start in production: {message}")
    log.warning("runtime_safety_warning: %s", message)
