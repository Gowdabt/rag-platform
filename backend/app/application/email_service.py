from __future__ import annotations

import logging
import os

from app.config.models import PlatformSettings
from app.domain.ports.email import EmailMessage, EmailResult
from app.domain.registry import registry
from app.email.renderer import UnknownEmailTemplateError, render_template

log = logging.getLogger("email")

KNOWN_TEMPLATES = frozenset({"password_reset", "password_changed", "user_invitation", "tenant_welcome"})


def _env(name: str, fallback: str) -> str:
    return os.environ.get(name, "").strip() or fallback


def resolved_email_provider_name(settings: PlatformSettings) -> str:
    return _env("EMAIL_PROVIDER", settings.email.provider).strip().lower() or "console"


def public_app_url(settings: PlatformSettings) -> str:
    return _env("PUBLIC_APP_URL", settings.email.public_app_url).rstrip("/")


def app_links(settings: PlatformSettings) -> dict[str, str]:
    base = public_app_url(settings)
    return {
        "applicationName": _env("EMAIL_FROM_NAME", settings.email.from_name) or settings.platform.name,
        "loginUrl": f"{base}/",
        "publicAppUrl": base,
    }


def invite_url(settings: PlatformSettings, token: str) -> str:
    return f"{public_app_url(settings)}/invite?token={token}"


def reset_url(settings: PlatformSettings, token: str, slug: str) -> str:
    from urllib.parse import urlencode

    query = urlencode({"token": token, "slug": slug})
    return f"{public_app_url(settings)}/reset?{query}"


class EmailService:
    def __init__(self, settings: PlatformSettings):
        self.settings = settings

    async def send(self, *, template: str, to: str, data: dict[str, str]) -> EmailResult:
        to = (to or "").strip()
        if not to:
            return EmailResult(ok=False, provider=resolved_email_provider_name(self.settings), error="missing_recipient")
        if template not in KNOWN_TEMPLATES:
            log.warning("email_unknown_template", extra={"template": template})
            return EmailResult(ok=False, provider=resolved_email_provider_name(self.settings), error="unknown_template")
        try:
            subject, text, html_body = render_template(template, data)
        except UnknownEmailTemplateError as exc:
            log.warning("email_template_error", extra={"template": template, "error": str(exc)})
            return EmailResult(ok=False, provider=resolved_email_provider_name(self.settings), error="template")
        from_name = _env("EMAIL_FROM_NAME", self.settings.email.from_name)
        from_address = _env("EMAIL_FROM_ADDRESS", self.settings.email.from_address)
        message = EmailMessage(
            to=to,
            subject=subject,
            text=text,
            html=html_body,
            from_name=from_name,
            from_address=from_address,
        )
        provider_name = resolved_email_provider_name(self.settings)
        try:
            provider = registry.create("email", provider_name, self.settings.email)
            result = await provider.send(message)
        except Exception as exc:
            log.warning("email_provider_error", extra={"template": template, "provider": provider_name, "error": type(exc).__name__})
            return EmailResult(ok=False, provider=provider_name, error=type(exc).__name__)
        if result.ok:
            log.info("email_sent", extra={"template": template, "provider": result.provider})
        else:
            log.warning("email_send_failed", extra={"template": template, "provider": result.provider, "error": result.error})
        return result
