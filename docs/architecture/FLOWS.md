# Business and data flows

Diagrams describe the code paths named under each figure. They are not target flows.

## Signup

`POST /api/v1/auth/signup` → `IdentityService.signup` → `_create_tenant_graph` → `_issue_session`.

Only when `RAG_ALLOW_PUBLIC_SIGNUP` is truthy. Otherwise the route raises `ForbiddenError` before the service.

```mermaid
flowchart TD
  post[POST /api/v1/auth/signup]
  flag{RAG_ALLOW_PUBLIC_SIGNUP?}
  email{email unused and password length at least 10?}
  user[Insert users]
  graph[Tenant org workspace roles membership Tenant Admin]
  tok[Insert refresh_tokens and return JWT]
  post --> flag
  flag -->|no| f403[403 Public signup is disabled]
  flag -->|yes| email
  email -->|no| err[409 or 422]
  email -->|yes| user --> graph --> tok
```

Database writes: `users`, `tenants`, `organizations`, `workspaces`, `roles`, `role_permissions`, `user_roles`, `tenant_memberships`, `refresh_tokens`. No document rows.

## Login

```mermaid
flowchart TD
  login[POST /api/v1/auth/login]
  user{user active and Argon2 ok?}
  sa{is_super_admin?}
  slug{tenant_slug or tenant_id?}
  mem{membership and tenant active?}
  ok[JWT plus refresh hash]
  fail[401 and optional audit auth.login.fail]
  login --> user
  user -->|no| fail
  user -->|yes| sa
  sa -->|yes| ok
  sa -->|no| slug
  slug -->|missing| v422[422 tenant required]
  slug -->|unknown or inactive or no membership| fail
  slug -->|ok| mem --> ok
```

## Upload and ingest

`POST /api/v1/documents` → `IngestionService.upload` → `ingest_content`. For `asyncio` and `taskiq_redis`, `process_job` runs before the request transaction commits.

```mermaid
flowchart TD
  up[Multipart file plus optional visibility and allowed_roles]
  perm{document:write and workspace in tenant?}
  size{bytes at most 50 MiB?}
  acl[resolve_upload_acl]
  src[Get or create data_sources connector_type upload for this user]
  hash[SHA-256 and pipeline fingerprint]
  same{same source file and same hash?}
  lock[pg_advisory_xact_lock]
  canon{canonical version for hash and fingerprint?}
  job[Insert ingestion_jobs status queued]
  proc[process_job same session]
  up --> perm
  perm -->|no| deny[403 or 404 workspace]
  perm -->|yes| size
  size -->|no| big[422 File too large]
  size -->|yes| acl --> src --> hash --> same
  same -->|yes| unch[Return unchanged]
  same -->|no| lock --> canon
  canon -->|completed or failed| dedup[derived version status deduplicated]
  canon -->|none| job --> proc
```

`process_job` data movement:

```mermaid
flowchart LR
  store[Storage get bytes]
  parse[BuiltinParser]
  chunk[Text chunker]
  emb[OllamaEmbedding one call per chunk]
  rows[document_chunks and chunk_embeddings]
  store --> parse --> chunk --> emb --> rows
```

FTS needs no extra write: `search_vector` is a generated column.

External calls: storage `put` on first sight of a hash; Ollama `POST /api/embeddings` per chunk. No queue broker call.

## Document read path

```mermaid
flowchart TD
  list[GET /documents or versions or chat retrieval]
  readp{document:read?}
  ids[authorized_document_ids or document_acl_sql inside search]
  live{external_status active and source feeds index?}
  out[JSON or hits]
  list --> readp
  readp -->|no| no[403]
  readp -->|yes| ids --> live
  live -->|no| hide[omitted or 404]
  live -->|yes| out
```

Tenant Admin does not skip `ids` unless some role still has `document:read_all`. The seed and migration `009` remove that code from Tenant Admin.

## Chat

`POST /api/v1/chat` and `POST /api/v1/chat/stream`.

```mermaid
flowchart TD
  ask[question conversation_id workspace_id version_id]
  auth[authorize_ask]
  cache{ask only and cache hit and citations still allowed?}
  prep[_prepare]
  rag{generation.rag_enabled?}
  corp{is_corpus_question?}
  cat[_document_catalog via authorized_document_ids]
  ret[_retrieve FTS and maybe dense]
  filt[_authorized_hits]
  rr[_rerank]
  ev{_has_evidence?}
  gen[LLM or refusal_message]
  db[messages citations retrieval_events usage_events]
  ask --> auth --> cache
  cache -->|hit| retn[return cached JSON]
  cache -->|miss| prep --> rag
  rag -->|no| gen
  rag -->|yes| corp
  corp -->|yes| cat --> gen
  corp -->|no| ret --> filt --> rr --> ev
  ev -->|no and refuse_without_evidence| gen
  ev -->|yes| gen
  gen --> db
```

Development reranker is `identity`, so any remaining hit counts as evidence (`ChatService._has_evidence`). Hybrid fusion is reciprocal rank fusion (`backend/app/application/fusion.py`) when strategy is `hybrid` and the embedding provider is not `hashing`.

Stream events, in order, from `stream_ask`: `retrieval.completed`, `generation.started`, zero or more `token`, `citations`, `generation.completed` or `error`. The route commits the session before yielding `generation.completed`.

## Connector sync

Manual: `POST /api/v1/subscriptions/{id}/sync` → `ConnectorService.sync` with `trigger=manual`.

Scheduled: API `scheduler_loop` → `run_due_syncs` → `sync(..., trigger=scheduled)` as the source owner.

```mermaid
flowchart TD
  due[subscription active and next_sync_at due]
  owner{owner user active and still a member?}
  run[sync_runs status processing]
  files[connector list files]
  ing[ingest_content per added or changed file]
  del[external_status deleted_externally for missing files]
  done[sync_runs completed or failed]
  due --> owner
  owner -->|no| skip[log warning and skip]
  owner -->|yes| run --> files --> ing --> del --> done
```

Sync does not publish a broker event. After `ingest_content`, if the result status is `queued` and `job_id` is set, `ConnectorService.sync` calls `IngestionService.process_job` on the same session (`backend/app/application/connectors.py`). That is the same in-process execution the upload route uses. `unchanged` increments `files_skipped`. `queued` with `version_new` increments `files_updated`. Any other status, including a new file and `deduplicated`, increments `files_added`. Files that disappeared from the listing get `external_status = deleted_externally` and `active_version_id` cleared. If any were marked deleted, `persist_authz_bump` runs. A per-file `get_file` exception increments `files_failed` and continues.
