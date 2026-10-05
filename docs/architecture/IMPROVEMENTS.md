# Recommended improvements

These are not implemented. Current behavior is in the other files in this directory.

## Critical

### Connect as a non-superuser so RLS applies

- **Current situation.** Migrations `ENABLE` and `FORCE ROW LEVEL SECURITY`. Compose and `.env.example` use database user `rag`, created by `POSTGRES_USER`, which is a superuser. Superusers bypass RLS.
- **Problem / risk.** A missing `tenant_id` predicate in one query returns other tenants' rows when the app role is superuser. Application queries usually filter `tenant_id`, but RLS was added as a backstop that does not work for this role.
- **Proposed change.** Create a `NOBYPASSRLS` login used only by the API. Run migrations as a different owner role. Keep `FORCE ROW LEVEL SECURITY`.
- **Expected benefit.** The policies in migration `001` and later actually bind.
- **Downside.** Migrations and the app need two roles. Local scripts must set the URL.
- **Complexity.** Medium.
- **Relevant files.** `docker/docker-compose.yml`, `.env.example`, `backend/alembic/versions/001_initial_schema.py`, `backend/app/adapters/db/session.py`.

### Point embeddings at the configured Ollama base URL

- **Current situation.** `OllamaEmbedding._base` returns `http://127.0.0.1:11434`. `OllamaLLM` uses `llm.api_base`. Development YAML sets that base to loopback. Compose sets `OLLAMA_BASE_URL=http://ollama:11434` and `RAG_ENV=development`, so the LLM override also points at loopback inside the API container.
- **Problem / risk.** Indexing and chat embeddings fail in Compose even when the Ollama service is healthy. LLM calls fail for the same loopback reason under the development layer.
- **Proposed change.** One resolver for Ollama base URL used by LLM, embeddings, and `/health`. In Compose, do not let `development.yaml` replace the service DNS name.
- **Expected benefit.** The compose file matches runtime behavior.
- **Downside.** Local host Ollama and container Ollama need an explicit switch.
- **Complexity.** Low.
- **Relevant files.** `backend/app/adapters/providers/embeddings/ollama.py`, `backend/app/adapters/providers/llm/ollama.py`, `configs/development.yaml`, `docker/docker-compose.yml`.

## High

### Do not block the HTTP request on the full embed loop

- **Current situation.** Upload and connector sync `await process_job`, and each chunk is a sequential Ollama HTTP call (`OllamaEmbedding.embed_documents`).
- **Problem / risk.** Large files hold a DB connection and a worker until every chunk returns. Client and proxy timeouts look like failure after the server may still be working. Sync of many files multiplies this.
- **Proposed change.** Commit the `queued` job, then process it on a concurrency-limited worker that actually calls the handler. Batch embedding requests if the provider supports it.
- **Expected benefit.** Upload latency tracks storage, not model time. Timeouts do not roll back a finished index.
- **Downside.** Clients must poll `GET /jobs`. Needs a real consumer and a crash sweeper.
- **Complexity.** High.
- **Relevant files.** `backend/app/api/v1/documents.py`, `backend/app/application/connectors.py`, `backend/app/adapters/providers/queues/asyncio_queue.py`, `backend/app/adapters/providers/embeddings/ollama.py`, `backend/app/workers/main.py`.

### Add a vector index or document why sequential scan is enough

- **Current situation.** `chunk_embeddings.embedding` is `vector`. `PgVectorStore.create_collection` returns immediately. Migration `001` creates no `ivfflat` or `hnsw` index. Search orders by `<=>` with `LIMIT`.
- **Problem / risk.** Dense search reads more of the table as chunks grow, inside the request.
- **Proposed change.** Add an ANN index compatible with cosine distance, built per embedding profile if dimensions differ.
- **Expected benefit.** Bounded search cost.
- **Downside.** Index build time and recall trade-off. Dimension changes need a new index.
- **Complexity.** Medium.
- **Relevant files.** `backend/alembic/versions/001_initial_schema.py`, `backend/app/adapters/providers/vectorstores/pgvector_store.py`.

### Single scheduler leader

- **Current situation.** Every API process starts `scheduler_loop`. Failed sync does not move `next_sync_at`, so the row stays due.
- **Problem / risk.** Two replicas sync the same subscription. A failing connector is retried every 60 seconds with no backoff.
- **Proposed change.** A Postgres advisory lock or `UPDATE ... WHERE next_sync_at` claim. On failure, set `next_sync_at` with backoff.
- **Expected benefit.** One syncer, quieter failures.
- **Downside.** Lock wait and clock skew.
- **Complexity.** Medium.
- **Relevant files.** `backend/app/application/scheduler.py`, `backend/app/application/connectors.py` (`sync` success path assigns `next_sync_at`).

### Production config should not allow localhost CORS or a dead OpenTelemetry flag to imply tracing

- **Current situation.** `configs/production.yaml` lists localhost origins and `otel_enabled: true`. `backend/app/observability/__init__.py` has no exporter. `enforce_runtime_safety` does not reject localhost CORS, only `*`.
- **Problem / risk.** A production boot can allow browser calls from a developer's machine if that file is deployed as-is. Operators may believe traces exist.
- **Proposed change.** Require an explicit public origin list in production. Either implement OTLP or stop setting `otel_enabled` until the module exports spans.
- **Expected benefit.** Safer default deploy and honest operations.
- **Downside.** Deployments must set origins on purpose.
- **Complexity.** Low.
- **Relevant files.** `configs/production.yaml`, `backend/app/core/runtime.py`, `backend/app/observability/__init__.py`.

## Medium

### Align or retire the worker and Redis

- **Current situation.** Compose starts Redis and a worker. `AsyncioJobQueue` is also registered as `taskiq_redis` and does not connect. ADR 006 describes Taskiq, backoff, and cancellation. `cancel` is a no-op.
- **Problem / risk.** Operators expect the worker container to drain `ingestion_jobs`. It will not. Redis outages fail Compose `depends_on` without the app using Redis.
- **Proposed change.** Either implement the ADR transport or stop shipping the worker and Redis until then. Update ADR 006 to match the code if the in-process design is intentional.
- **Expected benefit.** The deploy diagram matches the process.
- **Downside.** A later broker is a larger change if removed now.
- **Complexity.** Medium if implementing a consumer; low if removing unused services.
- **Relevant files.** `docker/docker-compose.yml`, `backend/app/workers/main.py`, `backend/app/adapters/providers/queues/asyncio_queue.py`, `docs/adr/006-job-state-in-postgres.md`.

### Catch duplicate idempotency keys

- **Current situation.** Unique `(tenant_id, idempotency_key)`. `ingest_content` does not catch `IntegrityError` on the job insert. Content objects do catch it.
- **Problem / risk.** Two concurrent uploads of new bytes with the same key surface as HTTP 500.
- **Proposed change.** On conflict, reload the existing job and return it.
- **Expected benefit.** Concurrent sync and upload share one job.
- **Downside.** Must define which ACL wins.
- **Complexity.** Low.
- **Relevant files.** `backend/app/application/ingestion.py`.

### Stop swallowing FTS errors as empty results

- **Current situation.** `PostgresFTSIndex.search` returns `[]` on any exception inside a savepoint.
- **Problem / risk.** A SQL error looks like "no documents" and the chat path may refuse or answer from dense results only, with no log required by that `except`.
- **Proposed change.** Log the exception and fail the request, or degrade with an explicit flag in the response.
- **Expected benefit.** Operators can see broken queries.
- **Downside.** Users see 500 instead of a partial answer.
- **Complexity.** Low.
- **Relevant files.** `backend/app/adapters/providers/sparse_indexes/postgres_fts.py`.

### Make the minimum relevance score apply to the default reranker

- **Current situation.** `generation.minimum_relevance_score` is 0.72. `_has_evidence` returns true for any hit when `reranker.provider` is `identity`, which is the development and base default.
- **Problem / risk.** Weak chunks still go to the LLM. The setting reads as a guard that does not run.
- **Proposed change.** Apply a threshold for identity as well, or change the default reranker to `lexical` and document the branch.
- **Expected benefit.** Refusal matches the configuration comment.
- **Downside.** More refusals on short documents.
- **Complexity.** Low.
- **Relevant files.** `backend/app/application/chat.py`, `configs/base.yaml`.

### Same permission on the chat route and in `authorize_ask`

- **Current situation.** The route requires `document:read`. `authorize_ask` allows `conversation:write` or `ai.chat` without `document:read`. The route check wins.
- **Problem / risk.** The service method is not a faithful description of HTTP access. A future internal caller could chat without `document:read` while still applying ACL SQL, which denies reads when `document:read` is absent (`can_read_document` first line).
- **Proposed change.** One helper used by the route and the service.
- **Expected benefit.** No split brain.
- **Downside.** Need a decision on whether chat requires read, write, or `ai.chat`.
- **Complexity.** Low.
- **Relevant files.** `backend/app/api/v1/chat.py`, `backend/app/application/chat.py`.

### Admin stats ignore ACL

- **Current situation.** `GET /api/v1/admin/stats` counts active documents in the tenant for anyone with `audit:read`.
- **Problem / risk.** A viewer does not have `audit:read` in the seed, but a custom role could. The count includes private documents the caller cannot open.
- **Proposed change.** Count through `authorized_document_ids` or require Tenant Admin.
- **Expected benefit.** Counts match what the caller can list.
- **Downside.** Tenant-wide operations metrics disappear for non-admin auditors.
- **Complexity.** Low.
- **Relevant files.** `backend/app/api/v1/admin.py`.

### Access token storage

- **Current situation.** `frontend/src/api/client.ts` stores `access_token` in `localStorage`.
- **Problem / risk.** Any XSS reads the token. CSP on API responses does not cover the Vite origin.
- **Proposed change.** Memory plus httpOnly refresh cookie, or a BFF. This is a product change, not a one-line fix.
- **Expected benefit.** Token not readable by page scripts.
- **Downside.** CSRF design for cookie auth.
- **Complexity.** High.
- **Relevant files.** `frontend/src/api/client.ts`, `backend/app/api/v1/auth.py`.

## Low

### Reconcile stale design docs

- **Current situation.** `docs/HLD.md` and `docs/schema.md` still say roles include Manager and that connectors are mock-only in one table. ADR 006 does not match `AsyncioJobQueue`.
- **Problem / risk.** Readers implement the wrong role model.
- **Proposed change.** Point those files at `docs/architecture/` or edit them to match `SEED_ROLES`.
- **Expected benefit.** One story.
- **Downside.** Editing historical ADRs needs a status note ("superseded by code").
- **Complexity.** Low.
- **Relevant files.** `docs/HLD.md`, `docs/schema.md`, `docs/adr/006-job-state-in-postgres.md`, `backend/app/application/rbac.py`.

### Implement or drop `cancelled`

- **Current situation.** The job check constraint allows `cancelled`. No writer assigns it. `AsyncioJobQueue.cancel` returns immediately.
- **Problem / risk.** API clients cannot cancel. The status looks supported.
- **Proposed change.** Remove it from the constraint or set it from an endpoint that `process_job` honors.
- **Expected benefit.** The state machine matches the schema.
- **Downside.** A migration to drop a constraint value.
- **Complexity.** Low.
- **Relevant files.** `backend/alembic/versions/001_initial_schema.py`, `backend/app/adapters/providers/queues/asyncio_queue.py`.

### Do not swallow engine init and super-admin seed failures silently

- **Current situation.** `try_init_engine` and the lifespan seed use bare `except`.
- **Problem / risk.** The API looks live (`/health/live`) with a dead database and no super admin, and logs may not explain the seed failure.
- **Proposed change.** Log the exception type at warning. Keep ready at 503.
- **Expected benefit.** Faster diagnosis.
- **Downside.** Noisy logs if Postgres starts a few seconds late.
- **Complexity.** Low.
- **Relevant files.** `backend/app/main.py`, `backend/app/adapters/db/session.py`.

### `GET /jobs` retry response should return the new status

- **Current situation.** Retry returns `{ok: true}` after `process_job` may have set `failed`.
- **Problem / risk.** Clients treat HTTP 200 as success.
- **Proposed change.** Return the job row status and error.
- **Expected benefit.** One round trip.
- **Downside.** None significant.
- **Complexity.** Low.
- **Relevant files.** `backend/app/api/v1/admin.py`, `backend/app/application/jobs.py`.
