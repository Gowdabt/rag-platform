from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field


@dataclass(frozen=True)
class EmailMessage:
    to: str
    subject: str
    text: str
    html: str
    from_name: str = ""
    from_address: str = ""
    reply_to: str = ""
    cc: tuple[str, ...] = field(default_factory=tuple)
    bcc: tuple[str, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class EmailResult:
    ok: bool
    provider: str
    error: str | None = None


class EmailProvider(ABC):
    @abstractmethod
    async def send(self, message: EmailMessage) -> EmailResult:
        raise NotImplementedError
