# High-level design (as implemented)

## Problem

Teams need a self-hosted, multi-tenant RAG workspace: upload or subscribe to knowledge sources, retrieve with hybrid search, and answer with citations — without locking the pipeline to one vendor SDK.

## Decisions already in the code

1. **Modular monolith** over microservices (ADR 001).
2. **Platform-owned pipeline** over LangChain (ADR 002).
3. **PostgreSQL as system of record**, including pgvector and FTS (ADR 003–004).
4. **YAML config cascade** with a denylist so tenants cannot override isolation/security keys (ADR 009).
5. **Single plugin registry** for every provider kind, including connectors (ADR 010).
6. **Authorization before generation.** Retrieval may return candidates; `_authorized_hits` / `_visible` drop unauthorized documents before rerank/LLM. Streaming uses the same `_prepare()` as `ask()`.
7. **Immutable document versions.** Content change creates a new version. External deletes set `external_status=deleted_externally` and keep history.
8. **External identity is not filename.** Connector sync keys documents on `(tenant_id, source_id, source_file_id)`. Uploads still use filename as the file id.

## Bounded contexts

| Context | Owner modules | Notes |
| --- | --- | --- |
| Identity | `api/v1/auth.py`, `core/security.py` | JWT access + refresh. |
| Tenancy / RBAC | `application/rbac.py`, RLS | Admin/Manager/Member/Viewer. Member includes `source:manage` in code (existing DB role rows are not auto-migrated). |
| Documents / ingest | `application/ingestion.py`, `application/jobs.py` | Parse → chunk → embed → FTS + pgvector. |
| Connectors | `application/connectors.py`, `adapters/providers/connectors/mock.py` | Mock providers only. |
| Chat / RAG | `application/chat.py`, fusion, query | Hybrid + RRF when embeddings are not hashing. |
| Eval | `application/eval.py` | Dataset + run + lexical F1 / citation recall. |
| Admin | `api/v1/admin.py` | Jobs, audit, usage, redacted config. |

## Connector HLD

A **data source** is a connected account (`data_sources` + encrypted `connector_credentials`).

A **subscription** is a folder/location under that account (`source_subscriptions`).

A **sync run** records discovered/added/updated/deleted/skipped/failed (`sync_runs`).

Mocks simulate OAuth, trees, auth expiry, rate limits, and partial failure. They are test-only unless `RAG_CONNECTOR_MOCKS=1`. Default catalog is live `local_fs`, `s3`, `google_drive`, `onedrive`, `sharepoint`, and `dropbox`.

## Secrets

`SecretStore` + `LocalTokenCipher` encrypt connector tokens at rest. Key from `TOKEN_ENCRYPTION_KEY` or `JWT_SECRET`. Not KMS/Vault yet.

## What this HLD does not claim

- Cloud OAuth production apps
- Desktop folder watcher
- Scheduled sync worker
- Semantic embeddings in default dev config (still hashing)
- Automatic production changes from user feedback
