from __future__ import annotations

from abc import ABC, abstractmethod

from app.config.models import OCRConfig
from app.core.context import RequestContext
from app.domain.types import ParsedDocument


class OCRProvider(ABC):
    def __init__(self, config: OCRConfig, ctx: RequestContext):
        self.config = config
        self.ctx = ctx

    @abstractmethod
    async def extract(self, content: bytes, *, mime_type: str) -> ParsedDocument:
        raise NotImplementedError
