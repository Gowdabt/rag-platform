from uuid import uuid4

import pytest
from app.adapters.providers.chunkers.text import TextChunker
from app.adapters.providers.embeddings.hashing import HashingEmbedding
from app.adapters.providers.parsers.builtin import BuiltinParser
from app.config.models import ChunkingConfig, EmbeddingConfig, ParserConfig
from app.core.context import RequestContext
from app.domain.types import ParsedDocument


@pytest.mark.asyncio
async def test_recursive_chunker_respects_size():
    ctx = RequestContext(request_id="t")
    chunker = TextChunker(ChunkingConfig(strategy="recursive", chunk_size=50, chunk_overlap=10), ctx)
    doc = ParsedDocument(text="a" * 120, mime_type="text/plain")
    chunks = await chunker.chunk(document=doc, document_id=uuid4(), document_version_id=uuid4())
    assert len(chunks) >= 2
    assert all(len(c.text) <= 50 for c in chunks)


@pytest.mark.asyncio
async def test_builtin_parser_plain_text():
    parser = BuiltinParser(ParserConfig(), RequestContext(request_id="t"))
    parsed = await parser.parse(b"hello policy", mime_type="text/plain", filename="a.txt")
    assert "hello policy" in parsed.text


@pytest.mark.asyncio
async def test_hashing_embeddings_are_deterministic():
    emb = HashingEmbedding(EmbeddingConfig(provider="hashing", model="hashing", dimensions=32), RequestContext(request_id="t"))
    a = await emb.embed_query("leave policy")
    b = await emb.embed_query("leave policy")
    assert a.vectors[0] == b.vectors[0]
    assert len(a.vectors[0]) == 32
