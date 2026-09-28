# Relational schema

PostgreSQL 16 is the system of record. Alembic migrations in `backend/alembic/versions` are the source of truth — do not rely on autogenerate alone.

## Conventions

- UUID primary keys (`gen_random_uuid()`).
- Every **tenant-owned** table has `tenant_id UUID NOT NULL` referencing `tenants(id)` and an index on `tenant_id`.
- `created_at` / `updated_at` timestamptz where the row is mutable; versions are insert-only.
- Row Level Security is enabled and **forced** on tenant-owned tables. The application sets `SET LOCAL app.tenant_id = '<uuid>'` per request/job.
- Tables **without** `tenant_id`: `tenants`, `users`, `permissions` (global catalogs).

## Isolation

```sql
SET LOCAL app.tenant_id = '…';
```

Policies use:

```sql
tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid
```

Migrations and a dedicated admin role may bypass RLS. The API/worker database role must not.

## Entity relationship (logical)

```
tenants 1──* organizations 1──* workspaces
tenants 1──* tenant_memberships *──1 users
workspaces 1──* data_sources 1──* documents 1──* document_versions 1──* document_chunks
documents *──1 document_versions (active_version_id)
document_chunks 1──* chunk_embeddings *──1 embedding_profiles
users 1──* conversations 1──* messages 1──* message_citations
messages 1──* retrieval_events
```

## Tables

### Identity and tenancy

**tenants** — isolation, residency, privacy JSON, budget JSON, status (`active` \| `suspended`).

**organizations** — child of tenant. Phase 2 creates one default org per tenant.

**workspaces** — corpus and default ACL boundary. Unique `(tenant_id, organization_id, slug)`.

**users** — global identity: email (unique, citext), `password_hash`, status.

**tenant_memberships** — `(tenant_id, user_id)` unique; optional `default_workspace_id`.

**teams** / **team_members** — groups used in document ACL `allowed_groups`.

**permissions** — global codes such as `document:read`, `source:manage`.

**roles** — tenant-scoped named roles (`Admin`, `Manager`, `Member`, `Viewer` seeded per tenant in Phase 2). Healthcare names (`Doctor`, `HR`) are data, not schema.

**role_permissions** — M2M.

**user_roles** — assignment, optional `workspace_id` for workspace-scoped grants.

### Configuration

**config_overlays** — `scope_type` ∈ `tenant` \| `organization` \| `workspace` \| `user`; `scope_id`; JSON `payload`; monotonic `version`. Unique `(tenant_id, scope_type, scope_id)`.

### Documents and ingestion

**data_sources** — connector type, config (secret refs only), sync cursor, status, `last_synced_at`.

**documents** — logical document: `source_id`, `source_file_id`, path, `active_version_id`, ACL JSON (`allowed_users`, `allowed_groups`, `classification`).

**content_objects** — tenant-scoped CAS blob: unique `(tenant_id, content_hash)`, `storage_key`, `ref_count`. Identical files share one object.

**document_versions** — immutable snapshot of a **named file**: checksum, content_hash, `content_object_id`, `derived_from_version_id` (shared index), `pipeline_fingerprint`, mime, parser/chunker versions, processing status.

**document_chunks** — text + page/section/index/token_count + `search_vector tsvector`. Owned by the canonical version; logical copies join through `derived_from_version_id`.

**embedding_profiles** — `(provider, model, dimensions, version)` used by indexes. A model change inserts a new profile and rebuilds embeddings; versions stay put.

**chunk_embeddings** — `(chunk_id, embedding_profile_id)` unique; `embedding vector` (pgvector, no typmod so dimension can vary per profile; HNSW indexes are added per profile later).

**ingestion_jobs** — system of record for async work: type, status, progress JSON, attempts, `idempotency_key` unique per tenant, error, FK to document/version/source.

Job status: `queued` → `processing` → `parsing` → `chunking` → `embedding` → `indexing` → `completed`, or `failed` → retry → `dead_letter`.

### Conversations and RAG audit

**conversations** — tenant, workspace, user, title.

**messages** — role, content, model, config snapshot JSON, token usage JSON.

**message_citations** — document/version/chunk, page, section, name, score.

**retrieval_events** — full retrieval trace: query, retriever, reranker, llm, embedding model, candidate chunks and scores, latency.

**user_memories** — opt-in long-term memory; empty unless tenant enables the memory provider. No automatic PHI capture.

**message_feedback** — thumbs, optional reason / expected source.

### Usage, audit, evaluation

**audit_logs** — actor, action, resource type/id, `request_id`, metadata (never secrets).

**usage_events** — token counts, estimated cost, provider/model.

**evaluation_datasets** / **evaluation_items** — questions, expected answers, expected sources.

**evaluation_runs** / **evaluation_results** — config snapshot, metrics JSON, actual answer/sources.

## Vector payloads (Qdrant or pgvector metadata)

Every indexed point must carry:

`tenant_id`, `workspace_id`, `document_id`, `version_id`, `chunk_id`, `principals[]`, `classification`

Search without `tenant_id` is a programmer error and must fail closed.

## Indexes (initial)

- `(tenant_id)` on all tenant-owned tables
- unique slugs as noted
- `documents (tenant_id, workspace_id)`
- `document_versions (document_id, version_number)` unique
- GIN on `document_chunks.search_vector`
- `ingestion_jobs (tenant_id, status)`
- `audit_logs (tenant_id, created_at)`
- `messages (conversation_id, created_at)`
- `documents (tenant_id, source_id, source_file_id)` unique (`uq_documents_source_file`)

## Connectors (migration `003_connectors`)

**oauth_states** — one-time OAuth `state`, expiry, connector type.

**connector_credentials** — encrypted access/refresh tokens per data source.

**source_subscriptions** — folder/location subscription (filters, schedule, status, ACL copy).

**sync_runs** — discovered/added/updated/deleted/skipped/failed counts and errors.

**documents** extra columns: `subscription_id`, `external_revision`, `external_status` (`active` \| `deleted_externally`).
