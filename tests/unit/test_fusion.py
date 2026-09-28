from uuid import uuid4

from app.application.fusion import reciprocal_rank_fusion
from app.domain.types import VectorHit


def test_rrf_prefers_items_high_in_both_lists():
    a, b, c = uuid4(), uuid4(), uuid4()
    dense = [
        VectorHit(chunk_id=a, document_id=a, version_id=a, score=0.9),
        VectorHit(chunk_id=b, document_id=b, version_id=b, score=0.8),
    ]
    sparse = [
        VectorHit(chunk_id=a, document_id=a, version_id=a, score=0.7),
        VectorHit(chunk_id=c, document_id=c, version_id=c, score=0.6),
    ]
    fused = reciprocal_rank_fusion([dense, sparse])
    assert fused[0].chunk_id == a


def test_rrf_keeps_same_chunk_for_two_logical_documents():
    chunk, d1, d2 = uuid4(), uuid4(), uuid4()
    dense = [VectorHit(chunk_id=chunk, document_id=d1, version_id=d1, score=0.9)]
    sparse = [VectorHit(chunk_id=chunk, document_id=d2, version_id=d2, score=0.8)]
    fused = reciprocal_rank_fusion([dense, sparse])
    assert {(h.document_id, h.chunk_id) for h in fused} == {(d1, chunk), (d2, chunk)}
