from __future__ import annotations

from abc import ABC, abstractmethod

from app.config.models import RerankerConfig
from app.core.context import RequestContext
from app.domain.types import RerankCandidate


class Reranker(ABC):
    def __init__(self, config: RerankerConfig, ctx: RequestContext):
        self.config = config
        self.ctx = ctx

    @abstractmethod
    async def rerank(
        self,
        query: str,
        candidates: list[RerankCandidate],
        *,
        top_k: int | None = None,
    ) -> list[RerankCandidate]:
        raise NotImplementedError
