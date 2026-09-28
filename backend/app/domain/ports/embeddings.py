from __future__ import annotations

from abc import ABC, abstractmethod

from app.config.models import EmbeddingConfig
from app.core.context import RequestContext
from app.domain.types import EmbeddingResult


class EmbeddingProvider(ABC):
    def __init__(self, config: EmbeddingConfig, ctx: RequestContext):
        self.config = config
        self.ctx = ctx

    @property
    def model_id(self) -> str:
        return self.config.model

    @property
    def dimensions(self) -> int | None:
        return self.config.dimensions

    @abstractmethod
    async def embed_documents(self, texts: list[str]) -> EmbeddingResult:
        raise NotImplementedError

    @abstractmethod
    async def embed_query(self, text: str) -> EmbeddingResult:
        raise NotImplementedError
