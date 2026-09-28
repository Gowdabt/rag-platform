from __future__ import annotations

from app.application.query import lexical_score
from app.config.models import RerankerConfig
from app.core.context import RequestContext
from app.domain.ports.reranker import Reranker
from app.domain.registry import register
from app.domain.types import RerankCandidate


@register("reranker", "lexical")
class LexicalReranker(Reranker):
    """Score chunks by token overlap. Used when embeddings are hashing or identity."""

    def __init__(self, config: RerankerConfig, ctx: RequestContext):
        super().__init__(config, ctx)

    async def rerank(
        self, query: str, candidates: list[RerankCandidate], *, top_k: int | None = None
    ) -> list[RerankCandidate]:
        k = top_k or self.config.top_k
        scored: list[RerankCandidate] = []
        for cand in candidates:
            page = cand.payload.get("page") if cand.payload else None
            score = lexical_score(query, cand.text, page=page if isinstance(page, int) else None)
            scored.append(cand.model_copy(update={"score": score}))
        scored.sort(key=lambda c: c.score, reverse=True)
        meaningful = [c for c in scored if c.score > 0]
        return (meaningful or scored)[:k]
