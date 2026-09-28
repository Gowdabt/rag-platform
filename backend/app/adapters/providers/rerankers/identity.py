from __future__ import annotations

from app.config.models import RerankerConfig
from app.core.context import RequestContext
from app.domain.ports.reranker import Reranker
from app.domain.registry import register
from app.domain.types import RerankCandidate


@register("reranker", "identity")
class IdentityReranker(Reranker):
    def __init__(self, config: RerankerConfig, ctx: RequestContext):
        super().__init__(config, ctx)

    async def rerank(
        self, query: str, candidates: list[RerankCandidate], *, top_k: int | None = None
    ) -> list[RerankCandidate]:
        ranked = sorted(candidates, key=lambda c: c.score, reverse=True)
        k = top_k or self.config.top_k
        return ranked[:k]
