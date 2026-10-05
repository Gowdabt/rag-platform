# Architecture decisions

Each row is something the repository already does. "Why it appears chosen" quotes an ADR or a code comment when one exists. Otherwise the cell is the required sentence. Alternatives are those named in an ADR or in `KNOWN_PROVIDERS`, not a new design proposal. Improvement ideas are in [IMPROVEMENTS.md](IMPROVEMENTS.md).

## D1. Modular monolith

| | |
| --- | --- |
| Decision | One FastAPI process hosts HTTP, ingestion, retrieval, chat, and the scheduler. |
| Context | `backend/app/main.py` `create_app` registers every router. Workers are the same code package. |
| Why it appears chosen | ADR `docs/adr/001-modular-monolith.md` accepts a modular monolith. |
| Alternatives | Named in that ADR (microservices). Not implemented. |
| Trade-offs | One deploy and one transaction boundary. The scheduler and ingestion share the API process, so a long embed blocks that worker's event loop for the request. |
| Current implications | `scripts/start.sh` starts only uvicorn and Vite. Compose still defines a worker that does not dequeue. |

## D2. No LangChain

| | |
| --- | --- |
| Decision | Pipeline code is owned by `IngestionService` and `ChatService`. `pyproject.toml` does not depend on LangChain. |
| Context | Providers implement small ports under `backend/app/domain/ports/`. |
| Why it appears chosen | ADR `docs/adr/002-no-langchain.md`. |
| Alternatives | A framework RAG stack. Not in the dependency list. |
| Trade-offs | Every retriever and prompt path is local code. New model vendors need an adapter. |
| Current implications | Hybrid search is `ChatService._retrieve` plus `reciprocal_rank_fusion`. |

## D3. PostgreSQL as system of record

| | |
| --- | --- |
| Decision | Tenants, documents, jobs, chat, audit, vectors, and FTS live in Postgres. |
| Context | Models in `backend/app/adapters/db/models.py`. Migrations `001`–`009`. |
| Why it appears chosen | ADR `docs/adr/003-postgres-system-of-record.md` and `docs/adr/004-pgvector-fts-defaults.md`. |
| Alternatives | `KNOWN_PROVIDERS` lists qdrant, milvus, weaviate, pinecone, opensearch, chroma. None of those vector stores are `@register`ed. Sparse alternative `opensearch` is not registered. |
| Trade-offs | One database to back up. Vector and lexical search share ACL SQL. Large embeddings sit beside OLTP data. |
| Current implications | `vector_store.provider` default in base YAML is `pgvector`. `sparse_index.provider` is `postgres_fts`. |

## D4. Ollama as the default model host

| | |
| --- | --- |
| Decision | Development YAML sets LLM `ollama` / `llama3.2` and embeddings `ollama` / `nomic-embed-text`. |
| Context | Base YAML uses `llama3.1` and `secret://env/OLLAMA_BASE_URL`. Development overrides model and `api_base`. |
| Why it appears chosen | ADR `docs/adr/005-ollama-implicit-provider.md`: do not send documents to a cloud API unless an overlay says so, and do not fall back to a cloud provider when Ollama is down. |
| Alternatives | `extractive` LLM is registered (no network). OpenAI-compatible LLM and OpenAI embeddings are registered and used only when configured. Anthropic, Gemini, Azure, Cohere, Voyage are catalog names without adapters. |
| Trade-offs | Local inference has no vendor key. Availability is the operator's Ollama process. |
| Current implications | LLM errors become HTTP 502 `PlatformError`. Embedding client ignores `OLLAMA_BASE_URL` (see [DEPLOYMENT.md](DEPLOYMENT.md)). Health reports `degraded` when tags cannot be listed; it does not switch providers. |

## D5. Job state in Postgres

| | |
| --- | --- |
| Decision | `ingestion_jobs` stores status, attempts, error, and idempotency key. |
| Context | Check constraint on status. Unique `(tenant_id, idempotency_key)`. |
| Why it appears chosen | ADR `docs/adr/006-job-state-in-postgres.md`: job state should survive a Redis flush and be visible to the admin API. |
| Alternatives | The ADR names Taskiq + Redis as transport. `KNOWN_PROVIDERS["queue"]` includes `celery_redis` and `rabbitmq`. |
| Trade-offs | The admin `GET /jobs` reads Postgres. There is no second source of truth to drift. |
| Current implications | **Divergence.** The registered queue does not use Redis. `enqueue` does not dispatch. `cancel` is empty. There is no backoff sleep. Idempotency key uses the embedding **model string**, not `embedding_profile_id`. `dead_letter` is a column value after the third failed `process_job` call, not a broker queue. Automatic re-enqueue of `processing` rows after a crash is not implemented. |

## D6. Versions separate from embedding profiles

| | |
| --- | --- |
| Decision | A file change creates `document_versions`. Embeddings point at `embedding_profiles` `(provider, model, dimensions, version)`. |
| Context | Unique constraints on both tables. `reembed_active` deletes `chunk_embeddings` for chunks and upserts again. |
| Why it appears chosen | ADR `docs/adr/007-versions-vs-embedding-profiles.md`. |
| Alternatives | Storing the vector only on the chunk row. Not the schema. |
| Trade-offs | Re-embedding can add a profile without a new document version. Identical bytes with the same pipeline fingerprint share a canonical version (`derived_from_version_id`). |
| Current implications | Retrieval joins logical versions through `LOGICAL_CHUNK_FROM` and filters `embedding_profiles.provider/model`. |

## D7. Authorize before the model sees text

| | |
| --- | --- |
| Decision | ACL parameters are bound into FTS and pgvector SQL. Hits are filtered again in Python. Streaming authorizes in a committed-or-rolled-back session before tokens are generated. |
| Context | `document_acl_sql`, `ChatService.authorize_ask`, `chat_stream`. |
| Why it appears chosen | ADR `docs/adr/008-authorization-before-retrieval.md`. Code comment on `chat_stream`: authorize before retrieval or LLM tokens. |
| Alternatives | Prompt-only hiding. The ADR rejects that. |
| Trade-offs | Two filters (SQL and Python) can disagree if one is updated without the other. Hidden documents return 404 on direct read, which avoids confirming ids. |
| Current implications | Tenant Admin no longer has `document:read_all` in `TENANT_ADMIN_PERMISSIONS`. Migration `009` deletes that grant from existing Admin / Tenant Admin rows. Private member documents stay private unless visibility, roles, or user grants say otherwise. |

## D8. Config cascade with a denylist

| | |
| --- | --- |
| Decision | YAML layers merge, then a tenant `config_overlays` payload merges per request. Some keys cannot be overlaid. |
| Context | `load_platform_settings`, `assert_overlay_allowed`. |
| Why it appears chosen | ADR `docs/adr/009-config-cascade-denylist.md`. |
| Alternatives | Per-tenant databases or unrestricted JSON settings. Not implemented. |
| Trade-offs | Tenants can change LLM temperature, retrieval `top_k`, and AI model via the AI-config endpoint where that endpoint allows it. They cannot set JWT secret, database URL, or storage keys through the overlay. |
| Current implications | Startup uses `resolve=False`. A bad overlay parse is ignored and base settings are returned (`get_tenant_settings` `except Exception`). |

## D9. Plugin registry

| | |
| --- | --- |
| Decision | `@register(kind, name)` fills `ProviderRegistry`. Entry-point group `rag_platform.providers` is loaded on first `get`. The group in `pyproject.toml` is empty. |
| Context | `backend/app/domain/registry.py`, `backend/app/config/catalog.py`. |
| Why it appears chosen | ADR `docs/adr/010-plugin-registry.md`. |
| Alternatives | Hard-coded imports only. The code uses both: `load_providers` imports adapter modules so decorators run (`backend/app/application/providers.py`). |
| Trade-offs | Catalog names and registered factories differ. Selecting an unregistered known name fails at runtime with 501 `provider_not_implemented`. |
| Current implications | `taskiq_redis` and `asyncio` are the same class. |

## D10. Content-addressed dedup

| | |
| --- | --- |
| Decision | SHA-256 of bytes plus a pipeline fingerprint. A second document with the same pair points `derived_from_version_id` at the canonical version and does not re-embed when the canonical is already completed or failed. |
| Context | `IngestionService.ingest_content`, `_canonical_version`, `_stamp_derived`. |
| Why it appears chosen | ADR `docs/adr/011-content-addressed-dedup.md`. |
| Alternatives | Re-index every upload. Not the code path when a canonical row exists. |
| Trade-offs | Storage is shared (`content_objects.ref_count`). ACL stays on each `documents` row. Retrieval uses the logical join so derived files still match chunks. |
| Current implications | Unchanged bytes for the same source file return `status: unchanged` and do not enqueue a job. |

## D11. Document visibility defaults

| | |
| --- | --- |
| Decision | Member uploads default to private owner ACL. Tenant Admin uploads default to `visibility: tenant`. The upload form may set `visibility` and `allowed_roles`. |
| Context | `default_upload_acl`, `resolve_upload_acl`, migration `009`. |
| Why it appears chosen | Comments in `rbac.py` and migration `009`: Tenant Admin must follow ACLs; private member uploads stay private unless granted. |
| Alternatives | A historical `document:read_all` grant on Tenant Admin. Removed from the seed and deleted by `009`. |
| Trade-offs | Admins do not see member-private documents. Admin-owned historical private rows are rewritten to tenant visibility by `009`. |
| Current implications | List, versions, FTS, pgvector, and `authorized_document_ids` share `document_acl_sql`. |

## D12. Password auth, not OIDC

| | |
| --- | --- |
| Decision | `auth.provider` default `password`. Adapter `@register("auth", "password")`. |
| Context | `configs/base.yaml`. `KNOWN_PROVIDERS["auth"]` includes `oidc`. |
| Why it appears chosen | Rationale not evident from repository. |
| Alternatives | `oidc` is a catalog name. No OIDC adapter was found. |
| Trade-offs | No external identity provider. Password policy is minimum length 10 plus Argon2. |
| Current implications | All interactive users have `password_hash` except accounts that have not set one (nullable column). Login treats a null hash as failure. |

## D13. Process-local chat cache keyed by authz epoch

| | |
| --- | --- |
| Decision | Successful cited answers are stored in `TenantCache` under `tenant:user:epoch:chat:...`. Epoch is `tenants.authz_epoch + users.authz_epoch`. |
| Context | `ChatService.ask`, `load_authz_epoch`, `persist_authz_bump`. |
| Why it appears chosen | Comment on `TenantCache`: epochs live in Postgres so role/share/disable/suspend bumps are visible to every worker. |
| Alternatives | Redis cache. Not implemented. |
| Trade-offs | A second API process does not see the first process's LRU, but it does see the epoch and will miss. Cache is skipped when citations are empty. Cached hits are re-checked with `can_read_document`. |
| Current implications | Share bumps the tenant epoch. Stream path does not write this cache (only `ask` does). |

## D14. Fail-closed empty ACL

| | |
| --- | --- |
| Decision | `can_read_document` returns false when ACL is missing or empty, unless `document:read_all`. SQL requires a non-empty JSON object. |
| Context | `can_read_document`, `document_acl_sql`. |
| Why it appears chosen | Comment on `document_acl_sql`: fail closed without user id unless read_all. |
| Alternatives | Treat empty ACL as tenant-visible. Not the code. |
| Trade-offs | A bug that writes `{}` hides the document from everyone except read_all. |
| Current implications | New uploads always write `owner_acl` via `merge_acl`. |

## D15. In-process scheduler

| | |
| --- | --- |
| Decision | `scheduler_loop` is an asyncio task started in the API lifespan. Interval 60 seconds. It is not started in `workers/main.py`. |
| Context | `create_app` lifespan, `run_due_syncs`. |
| Why it appears chosen | Rationale not evident from repository. |
| Alternatives | Cron, a dedicated worker loop. The worker entrypoint does not call `scheduler_loop`. |
| Trade-offs | One API process is also the cron. Two API replicas would both fire. |
| Current implications | Subscriptions need `status=active` and `next_sync_at <= now()`. Manual sync is `POST /subscriptions/{id}/sync`. |
