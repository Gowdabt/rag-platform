from __future__ import annotations

import asyncio
import logging
import os
import smtplib
import ssl

from app.adapters.providers.email.console import format_rfc822
from app.config.models import EmailConfig
from app.domain.ports.email import EmailMessage, EmailProvider, EmailResult
from app.domain.registry import register

log = logging.getLogger("email.smtp")


def _env(name: str, fallback: str) -> str:
    return os.environ.get(name, "").strip() or fallback


@register("email", "smtp")
class SMTPEmailProvider(EmailProvider):
    def __init__(self, config: EmailConfig):
        self.config = config

    def _settings(self) -> tuple[str, int, str, str, bool]:
        host = _env("SMTP_HOST", self.config.smtp_host)
        port_raw = _env("SMTP_PORT", str(self.config.smtp_port or 587))
        try:
            port = int(port_raw)
        except ValueError:
            port = 587
        username = _env("SMTP_USERNAME", self.config.smtp_username)
        password = _env("SMTP_PASSWORD", self.config.smtp_password)
        secure_raw = _env("SMTP_SECURE", "1" if self.config.smtp_secure else "0").lower()
        secure = secure_raw in {"1", "true", "yes", "on"}
        return host, port, username, password, secure

    async def send(self, message: EmailMessage) -> EmailResult:
        host, port, username, password, secure = self._settings()
        if not host:
            return EmailResult(ok=False, provider="smtp", error="SMTP_HOST is not configured")
        from_name = _env("EMAIL_FROM_NAME", self.config.from_name)
        from_address = _env("EMAIL_FROM_ADDRESS", self.config.from_address)
        if not from_address:
            return EmailResult(ok=False, provider="smtp", error="EMAIL_FROM_ADDRESS is not configured")
        packed = format_rfc822(message, from_name=from_name, from_address=from_address)
        loop = asyncio.get_running_loop()
        try:
            await loop.run_in_executor(None, self._send_sync, packed, host, port, username, password, secure)
        except Exception as exc:
            log.warning("email_smtp_failed", extra={"error": type(exc).__name__})
            return EmailResult(ok=False, provider="smtp", error=type(exc).__name__)
        return EmailResult(ok=True, provider="smtp")

    def _send_sync(
        self,
        packed,
        host: str,
        port: int,
        username: str,
        password: str,
        secure: bool,
    ) -> None:
        if port == 465:
            context = ssl.create_default_context()
            with smtplib.SMTP_SSL(host, port, timeout=20, context=context) as client:
                if username:
                    client.login(username, password)
                client.send_message(packed)
            return
        with smtplib.SMTP(host, port, timeout=20) as client:
            client.ehlo()
            if secure:
                context = ssl.create_default_context()
                client.starttls(context=context)
                client.ehlo()
            if username:
                client.login(username, password)
            client.send_message(packed)
