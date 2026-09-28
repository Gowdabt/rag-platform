from uuid import uuid4

from app.application.chat import _unique_hits
from app.application.content_address import pipeline_fingerprint
from app.config.load import load_platform_settings, load_yaml_layers, parse_settings
from app.domain.types import VectorHit


def test_pipeline_fingerprint_is_stable_and_sensitive_to_pipeline():
    settings = load_platform_settings(resolve=False)
    baseline = pipeline_fingerprint(settings)
    assert baseline == pipeline_fingerprint(settings)
    assert len(baseline) == 32

    data = load_yaml_layers()
    chunking = dict(data["chunking"])
    chunking["chunk_size"] = int(chunking["chunk_size"]) + 64
    other = parse_settings({**data, "chunking": chunking})
    assert pipeline_fingerprint(other) != baseline

    embedding = dict(data["embedding"])
    embedding["model"] = f"{embedding['model']}-other"
    other_embed = parse_settings({**data, "embedding": embedding})
    assert pipeline_fingerprint(other_embed) != baseline


def test_unique_hits_keeps_shared_chunk_per_logical_document():
    chunk = uuid4()
    d1, d2 = uuid4(), uuid4()
    v1, v2 = uuid4(), uuid4()
    hits = [
        VectorHit(chunk_id=chunk, document_id=d1, version_id=v1, score=0.4),
        VectorHit(chunk_id=chunk, document_id=d2, version_id=v2, score=0.9),
        VectorHit(chunk_id=chunk, document_id=d1, version_id=v1, score=0.2),
    ]
    out = _unique_hits(hits)
    assert {(h.document_id, h.chunk_id) for h in out} == {(d1, chunk), (d2, chunk)}
    kept = next(h for h in out if h.document_id == d1)
    assert kept.score == 0.4
