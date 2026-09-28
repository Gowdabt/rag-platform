from __future__ import annotations

from collections import defaultdict

from app.domain.types import VectorHit


def reciprocal_rank_fusion(result_sets: list[list[VectorHit]], k: int = 60) -> list[VectorHit]:
    scores: dict[str, float] = defaultdict(float)
    by_id: dict[str, VectorHit] = {}
    for results in result_sets:
        for rank, hit in enumerate(results, start=1):
            key = f"{hit.document_id}:{hit.chunk_id}"
            scores[key] += 1.0 / (k + rank)
            by_id[key] = hit
    ordered = sorted(scores, key=lambda x: scores[x], reverse=True)
    fused = []
    for key in ordered:
        hit = by_id[key]
        fused.append(hit.model_copy(update={"score": scores[key]}))
    return fused
