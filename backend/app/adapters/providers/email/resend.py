from __future__ import annotations

import logging
import os

import httpx

from app.config.models import EmailConfig
from app.domain.ports.email import EmailMessage, EmailProvider, EmailResult
from app.domain.registry import register

log = logging.getLogger("email.resend")
_API = "https://api.resend.com/emails"


def _env(name: str, fallback: str) -> str:
    return os.environ.get(name, "").strip() or fallback


@register("email", "resend")
class ResendEmailProvider(EmailProvider):
    def __init__(self, config: EmailConfig):
        self.config = config

    async def send(self, message: EmailMessage) -> EmailResult:
        api_key = _env("RESEND_API_KEY", self.config.api_key)
        if not api_key:
            return EmailResult(ok=False, provider="resend", error="RESEND_API_KEY is not configured")
        from_name = _env("EMAIL_FROM_NAME", self.config.from_name)
        from_address = _env("EMAIL_FROM_ADDRESS", self.config.from_address)
        if not from_address:
            return EmailResult(ok=False, provider="resend", error="EMAIL_FROM_ADDRESS is not configured")
        sender = f"{from_name} <{from_address}>" if from_name else from_address
        payload = {
            "from": sender,
            "to": [message.to],
            "subject": message.subject,
            "text": message.text,
            "html": message.html,
        }
        try:
            async with httpx.AsyncClient(timeout=20.0) as client:
                response = await client.post(
                    _API,
                    headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                    json=payload,
                )
        except Exception as exc:
            log.warning("email_resend_failed", extra={"error": type(exc).__name__})
            return EmailResult(ok=False, provider="resend", error=type(exc).__name__)
        if response.status_code >= 400:
            log.warning("email_resend_rejected", extra={"status": response.status_code})
            return EmailResult(ok=False, provider="resend", error=f"http_{response.status_code}")
        return EmailResult(ok=True, provider="resend")
