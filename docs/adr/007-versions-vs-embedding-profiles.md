# ADR 007: Immutable document versions; separate embedding profiles

## Status

Accepted

## Context

Users must ask “what did the policy say before the March update?” Embedding-model upgrades must not destroy that history or silently mix vector spaces.

## Decision

- Content changes create a new **document_version**. Old versions remain searchable when the query asks for them; `documents.active_version_id` is the default.
- Embedding model/dimension/version is an **embedding_profile**. Reindex writes new `chunk_embeddings` (or Qdrant points) for existing versions.
- Retrieval uses the workspace’s active embedding profile unless an evaluation run pins another.

## Consequences

- Storage grows with versions × embedding profiles; retention policies must be explicit.
- Change detection compares content hashes, not embedding blobs.
- Evaluation experiments can swap chunker/embedder/reranker without rewriting source files.
