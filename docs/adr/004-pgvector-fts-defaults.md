# ADR 004: pgvector + PostgreSQL FTS as default retrieval backends

## Status

Accepted

## Context

Hybrid search needs dense and sparse indexes. Requiring Qdrant and OpenSearch in every local compose would make the Ollama-first developer path heavy.

## Decision

Default `vector_store.provider: pgvector` and `sparse_index.provider: postgres_fts`.

Qdrant is the second implemented `VectorStore`. OpenSearch is a later `SparseIndex` provider.

## Consequences

- `docker compose up` needs Postgres, Redis, MinIO, Ollama — not Qdrant/OpenSearch.
- FTS quality is good enough for v1; BM25 via OpenSearch can be added without changing the query pipeline.
- HNSW/IVF indexes on pgvector will be per embedding profile because dimensions vary.
