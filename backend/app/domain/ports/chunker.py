from __future__ import annotations

from abc import ABC, abstractmethod
from uuid import UUID

from app.config.models import ChunkingConfig
from app.core.context import RequestContext
from app.domain.types import Chunk, ParsedDocument


class Chunker(ABC):
    def __init__(self, config: ChunkingConfig, ctx: RequestContext):
        self.config = config
        self.ctx = ctx

    @abstractmethod
    async def chunk(
        self,
        document: ParsedDocument,
        *,
        document_id: UUID,
        document_version_id: UUID,
    ) -> list[Chunk]:
        raise NotImplementedError
