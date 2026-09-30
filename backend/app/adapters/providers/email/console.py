from __future__ import annotations

import logging
from email.message import EmailMessage as StdlibEmail
from email.utils import formataddr

from app.config.models import EmailConfig
from app.domain.ports.email import EmailMessage, EmailProvider, EmailResult
from app.domain.registry import register

log = logging.getLogger("email.console")

_INBOX: list[EmailMessage] = []


def captured_emails() -> list[EmailMessage]:
    return list(_INBOX)


def clear_captured_emails() -> None:
    _INBOX.clear()


def last_captured_email() -> EmailMessage | None:
    return _INBOX[-1] if _INBOX else None


@register("email", "console")
class ConsoleEmailProvider(EmailProvider):
    """Captures mail in-process. Does not log bodies or tokens."""

    def __init__(self, config: EmailConfig):
        self.config = config

    async def send(self, message: EmailMessage) -> EmailResult:
        _INBOX.append(message)
        log.info(
            "email_console_captured",
            extra={"to": message.to, "subject": message.subject, "provider": "console"},
        )
        return EmailResult(ok=True, provider="console")


def format_rfc822(message: EmailMessage, *, from_name: str, from_address: str) -> StdlibEmail:
    msg = StdlibEmail()
    msg["Subject"] = message.subject
    msg["From"] = formataddr((from_name or message.from_name, from_address or message.from_address))
    msg["To"] = message.to
    if message.reply_to:
        msg["Reply-To"] = message.reply_to
    if message.cc:
        msg["Cc"] = ", ".join(message.cc)
    if message.bcc:
        msg["Bcc"] = ", ".join(message.bcc)
    msg.set_content(message.text)
    if message.html:
        msg.add_alternative(message.html, subtype="html")
    return msg
