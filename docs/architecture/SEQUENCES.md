# Sequence diagrams

Each diagram is a path that exists in this repository. Participants use the function or process that actually runs.

## Sequence diagram index

| # | Diagram | Represents |
| --- | --- | --- |
| 1 | Successful authenticated read | `GET /api/v1/documents` from bearer token through ACL SQL |
| 2 | Authentication | `POST /api/v1/auth/login` for a tenant member |
| 3 | Authorization denial | `require_permission` failure and audit |
| 4 | Document hidden by ACL | Version read returns 404 |
| 5 | Upload and ingest | `POST /api/v1/documents` including inline `process_job` |
| 6 | Chat / RAG | `POST /api/v1/chat` hybrid retrieval and Ollama |
| 7 | Database session | RLS GUCs inside `session.begin()` |
| 8 | External API | `OllamaLLM.stream` and `OllamaEmbedding.embed_documents` |
| 9 | Async / worker | Why the worker process does not run the job the API runs inline |
| 10 | Error | Ollama connection error on chat |
| 11 | Retry | `POST /api/v1/jobs/{job_id}/retry` |
| 12 | Timeout | Embedding httpx timeout inside `process_job` |
| 13 | Scheduled sync | `scheduler_loop` → `ConnectorService.sync` |

## 1. Successful authenticated read

`list_documents` in `backend/app/api/v1/documents.py`, `authorized_document_ids` in `authz.py`.

```mermaid
sequenceDiagram
  participant C as Client
  participant M as Middleware
  participant D as get_context
  participant R as list_documents
  participant S as IngestionService
  participant DB as Postgres

  C->>M: GET /api/v1/documents Authorization Bearer
  M->>M: rate limit, x-request-id, security headers
  M->>D: decode_jwt typ=access
  D->>DB: set_config app.tenant_id, hydrate roles
  D->>R: require_permission document:read
  R->>S: list_documents
  S->>DB: authorized_document_ids with document_acl_sql
  DB-->>S: ids
  S->>DB: load Document and active DocumentVersion
  S-->>C: 200 JSON array
```

## 2. Authentication

`IdentityService.login`.

```mermaid
sequenceDiagram
  participant C as Client
  participant A as login route
  participant I as IdentityService
  participant DB as Postgres

  C->>A: POST /api/v1/auth/login email password tenant_slug
  A->>I: login
  I->>DB: select users by email
  I->>I: verify_password Argon2
  I->>DB: select tenants by slug
  I->>DB: set_config tenant and user
  I->>DB: select tenant_memberships
  I->>DB: update last_login_at
  I->>DB: insert audit_logs auth.login.success
  I->>DB: insert refresh_tokens hash
  I-->>C: access JWT and refresh token
```

## 3. Authorization denial

`require_permission` in `backend/app/api/deps.py`.

```mermaid
sequenceDiagram
  participant C as Client
  participant P as require_permission
  participant DB as Postgres

  C->>P: Bearer with hydrated context missing document:write
  P->>DB: insert audit_logs action authz.denied
  Note over P,DB: audit failure is swallowed
  P-->>C: 403 code forbidden detail Missing permission document:write
```

## 4. Document hidden by ACL

`IngestionService.list_versions` calls `_visible` → `can_read_document`. SQL list uses the same predicate. A viewer who is not allowed receives 404, including when the UUID exists.

```mermaid
sequenceDiagram
  participant C as Client
  participant H as document_versions
  participant S as IngestionService
  participant DB as Postgres

  C->>H: GET /documents/{id}/versions
  H->>S: list_versions
  S->>DB: select documents
  S->>S: can_read_document false or not live
  S-->>C: 404 code not_found detail Document not found
```

## 5. Upload and ingest

`upload_document` then `IngestionService.process_job`. Queue provider `asyncio` (development) or `taskiq_redis`.

```mermaid
sequenceDiagram
  participant C as Client
  participant H as upload_document
  participant S as IngestionService
  participant DB as Postgres
  participant FS as Storage
  participant O as Ollama

  C->>H: POST /documents multipart
  H->>S: upload
  S->>S: resolve_upload_acl
  S->>DB: data_sources upload row
  S->>DB: advisory lock, documents, versions, content_objects
  S->>FS: put if new hash
  S->>DB: ingestion_jobs queued
  S->>S: AsyncioJobQueue.enqueue returns handle
  H->>S: process_job same session
  S->>FS: get bytes
  S->>S: BuiltinParser and chunker
  S->>O: POST /api/embeddings per chunk
  S->>DB: document_chunks and chunk_embeddings
  S->>DB: job and version completed
  Note over H,DB: transaction commits when the request dependency exits
  H-->>C: 200 status completed
```

## 6. Chat / RAG

`ChatService.ask` with development settings: hybrid, identity reranker, Ollama.

```mermaid
sequenceDiagram
  participant C as Client
  participant H as chat route
  participant S as ChatService
  participant DB as Postgres
  participant O as Ollama

  C->>H: POST /chat question
  H->>S: ask
  S->>S: authorize_ask
  S->>DB: load_authz_epoch and cache lookup
  S->>S: _rewrite then _retrieve
  S->>DB: FTS search with document_acl_sql
  S->>O: POST /api/embeddings query
  S->>DB: pgvector search with document_acl_sql
  S->>S: reciprocal_rank_fusion
  S->>S: _authorized_hits and identity rerank
  S->>O: POST /api/chat stream consumed fully
  S->>DB: messages, citations, retrieval_events, usage_events
  S->>S: cache set if citations nonempty
  S-->>C: answer and citations
```

## 7. Database interaction

`_db` dependencies and `apply_rls`.

```mermaid
sequenceDiagram
  participant H as Route
  participant DB as Postgres

  H->>DB: BEGIN
  H->>DB: SELECT set_config app.tenant_id is_local true
  H->>DB: SELECT set_config app.user_id is_local true
  H->>DB: SELECT or INSERT tenant-scoped rows
  Note over DB: RLS policy compares tenant_id to current_tenant_id unless role is superuser
  alt success
    H->>DB: COMMIT
  else PlatformError or other
    H->>DB: ROLLBACK
  end
```

`process_job` adds `SAVEPOINT` via `begin_nested()` around chunk writes.

## 8. External API (Ollama)

`OllamaLLM.stream` timeout 120s. `OllamaEmbedding` uses base `http://127.0.0.1:11434` regardless of `llm.api_base`.

```mermaid
sequenceDiagram
  participant S as ChatService or IngestionService
  participant L as OllamaLLM
  participant E as OllamaEmbedding
  participant O as Ollama HTTP

  S->>E: embed_query or embed_documents
  loop each text
    E->>O: POST /api/embeddings
    O-->>E: embedding array
  end
  S->>L: stream
  L->>O: POST /api/chat stream true
  O-->>L: NDJSON message content
  L-->>S: tokens
```

Health uses a different call: `GET /api/tags` with timeout 2s (`backend/app/api/v1/health.py`).

## 9. Async / worker

```mermaid
sequenceDiagram
  participant API as API lifespan
  participant Q as AsyncioJobQueue
  participant W as python -m app.workers.main
  participant S as IngestionService

  API->>API: set_job_handler run_ingestion_job
  W->>W: set_job_handler then wait for signal
  Note over W: enqueue is never called inside the worker
  API->>Q: enqueue from ingest_content
  Q-->>API: JobHandle only
  API->>S: process_job on the request session
  Note over W: handler function is not invoked by the queue
```

## 10. Error (Ollama down during chat)

`OllamaLLM.stream` raises `PlatformError` status 502. `ask` does not catch it. The global handler returns the problem body. `stream_ask` catches `PlatformError` and yields an SSE error instead.

```mermaid
sequenceDiagram
  participant C as Client
  participant S as ChatService.ask
  participant O as Ollama

  C->>S: POST /chat
  S->>O: POST /api/chat
  O-->>S: connection refused
  S-->>C: 502 code platform_error detail names ollama serve
```

## 11. Retry

`retry_job` in `backend/app/api/v1/admin.py` calls `run_ingestion_job`, which opens a new transaction and calls `process_job`. `attempts` increments again. The third failed attempt sets `dead_letter`.

```mermaid
sequenceDiagram
  participant C as Client
  participant R as retry_job
  participant J as run_ingestion_job
  participant S as IngestionService
  participant DB as Postgres

  C->>R: POST /jobs/{id}/retry
  R->>R: ACL or source ownership check
  R->>J: new session
  J->>DB: hydrate_context
  J->>S: process_job
  alt success
    S->>DB: status completed attempts incremented
  else failure and attempts less than 3
    S->>DB: status failed
  else failure and attempts at least 3
    S->>DB: status dead_letter
  end
  R-->>C: 200 ok true
```

The HTTP response is `ok: true` even when `process_job` caught an error and stored `failed`. The client must `GET /jobs` to see status. `run_ingestion_job` also swallows unexpected exceptions after logging `ingestion_job_failed`.

## 12. Timeout during ingest

httpx client timeout is 120 seconds. There is no separate application timeout.

```mermaid
sequenceDiagram
  participant H as upload_document
  participant S as process_job
  participant O as Ollama
  participant DB as Postgres

  H->>S: process_job
  S->>DB: SAVEPOINT
  S->>O: POST /api/embeddings
  O-->>S: httpx timeout after 120s
  S->>DB: ROLLBACK TO SAVEPOINT
  S->>DB: job failed or dead_letter version failed
  H-->>H: request transaction commits the failure row
  H-->>H: response status is the job status not HTTP 502
```

Upload maps the failure into the JSON `status` / `error` fields because `process_job` does not re-raise. Chat does not use that catch.

## 13. Scheduled sync

`scheduler_loop` waits 60 seconds or until shutdown. `run_due_syncs` is not started in the worker module.

```mermaid
sequenceDiagram
  participant L as scheduler_loop
  participant R as run_due_syncs
  participant I as IdentityService
  participant C as ConnectorService
  participant S as IngestionService

  L->>R: every 60s
  R->>R: list tenant ids
  loop each due subscription
    R->>I: hydrate_context as source owner
    R->>C: sync trigger scheduled
    C->>S: ingest_content
    C->>S: process_job if status queued
  end
  Note over L: tick exceptions are logged and the loop continues
```

On sync failure, `next_sync_at` stays in the past, so the next tick can select the same subscription again.
