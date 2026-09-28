from __future__ import annotations

from abc import ABC, abstractmethod

from app.config.models import ParserConfig
from app.core.context import RequestContext
from app.domain.types import ParsedDocument


class DocumentParser(ABC):
    def __init__(self, config: ParserConfig, ctx: RequestContext):
        self.config = config
        self.ctx = ctx

    @abstractmethod
    async def parse(
        self,
        content: bytes,
        *,
        mime_type: str,
        filename: str | None = None,
    ) -> ParsedDocument:
        raise NotImplementedError
