from __future__ import annotations

import hashlib

from app.config.models import PlatformSettings

# Map stored chunks (owned by a canonical version) onto every logical file
# whose active version is that canonical row or derives from it.
LOGICAL_CHUNK_FROM = """
FROM document_chunks c
JOIN document_versions canon ON canon.id = c.version_id
JOIN document_versions v ON (v.id = canon.id OR v.derived_from_version_id = canon.id)
JOIN documents d ON d.id = v.document_id AND d.active_version_id = v.id AND d.external_status = 'active'
"""


def pipeline_fingerprint(settings: PlatformSettings) -> str:
    """Identity of parse → chunk → embed. Same bytes + same fingerprint share one index."""
    chunking = settings.chunking
    embedding = settings.embedding
    raw = "|".join(
        [
            settings.parser.provider,
            chunking.strategy,
            str(chunking.chunk_size),
            str(chunking.chunk_overlap),
            embedding.provider,
            embedding.model,
            str(embedding.dimensions or ""),
        ]
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:32]
