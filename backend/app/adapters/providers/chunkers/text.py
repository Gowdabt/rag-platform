from __future__ import annotations

import re
from uuid import UUID

from app.config.models import ChunkingConfig
from app.core.context import RequestContext
from app.domain.ports.chunker import Chunker
from app.domain.registry import register
from app.domain.types import Chunk, ParsedDocument


def _split(text: str, size: int, overlap: int) -> list[str]:
    if size <= 0:
        return [text]
    chunks = []
    start = 0
    while start < len(text):
        end = min(len(text), start + size)
        chunks.append(text[start:end])
        if end == len(text):
            break
        start = max(end - overlap, start + 1)
    return chunks


def _to_chunks(parts: list[str], document: ParsedDocument, document_id: UUID, version_id: UUID) -> list[Chunk]:
    out = []
    for i, part in enumerate(parts):
        page = document.pages[0].page_number if document.pages else None
        if document.pages:
            for p in document.pages:
                if part[:80] in p.text or p.text[:80] in part:
                    page = p.page_number
                    break
        out.append(
            Chunk(
                document_id=document_id,
                document_version_id=version_id,
                chunk_index=i,
                text=part.strip(),
                page=page,
                token_count=max(1, len(part.split())),
            )
        )
    return [c for c in out if c.text]


@register("chunker", "recursive")
@register("chunker", "fixed")
@register("chunker", "token")
@register("chunker", "sentence")
@register("chunker", "markdown")
class TextChunker(Chunker):
    def __init__(self, config: ChunkingConfig, ctx: RequestContext):
        super().__init__(config, ctx)

    async def chunk(
        self, document: ParsedDocument, *, document_id: UUID, document_version_id: UUID
    ) -> list[Chunk]:
        text = document.text or ""
        size = self.config.chunk_size
        overlap = self.config.chunk_overlap
        strategy = self.config.strategy
        if strategy == "sentence":
            parts = [p.strip() for p in re.split(r"(?<=[.!?])\s+", text) if p.strip()]
            merged: list[str] = []
            buf = ""
            for p in parts:
                if len(buf) + len(p) + 1 <= size:
                    buf = f"{buf} {p}".strip()
                else:
                    if buf:
                        merged.append(buf)
                    buf = p
            if buf:
                merged.append(buf)
            return _to_chunks(merged, document, document_id, document_version_id)
        if strategy == "markdown":
            parts = re.split(r"(?=^#{1,6} )", text, flags=re.M)
            parts = [p for p in parts if p.strip()]
            if not parts:
                parts = _split(text, size, overlap)
            return _to_chunks(parts, document, document_id, document_version_id)
        if strategy == "token":
            size = size * 4
            overlap = overlap * 4
        return _to_chunks(_split(text, size, overlap), document, document_id, document_version_id)
