# ADR 003: PostgreSQL is the system of record

## Status

Accepted

## Context

Users, ACL, document versions, jobs, conversations, and audit must be consistent. Vector databases and object stores are poor sources of truth for that.

## Decision

**PostgreSQL holds canonical metadata.** Qdrant/pgvector vectors and MinIO/S3 objects are derived. If they diverge, rebuild from Postgres + object storage.

Job status, idempotency keys, and progress live in `ingestion_jobs`, not in Redis.

## Consequences

- One backup/restore story for business data.
- Vector/object rebuilds are operationally expected after embedding-profile changes.
- Local development can run RAG with Postgres alone (pgvector + FTS).
