# API design

Base path: `/api/v1`. Routers are included from `create_app` in `backend/app/main.py`. There is no API gateway in front of uvicorn.

**92 route registrations** are listed below. `PUT` and `PATCH` on `/roles/{role_id}` are two registrations of one function. Folder grant delete is registered on two paths.

## Common behavior

### Authentication header

Protected routes use `HTTPBearer`: `Authorization: Bearer <access jwt>`. `typ` must be `access`. Exceptions: auth routes other than `switch-tenant` and `me`, and all three health routes.

### Error body

`backend/app/api/errors.py` `problem()`:

| Field | Meaning |
| --- | --- |
| type | `about:blank` |
| title | Reason phrase for the status |
| status | HTTP status |
| detail | Exception message, or a fixed string for unhandled errors |
| code | `PlatformError.code` |
| request_id | Present when `RequestIdMiddleware` ran |
| errors | Only on 422, list of `{loc, msg, type}` without the raw input |

| Status | code | When |
| --- | --- | --- |
| 401 | `unauthenticated` | Missing, bad, or expired token; bad login; bad refresh |
| 403 | `forbidden` | Permission, signup disabled, overlay, inactive tenant |
| 404 | `not_found` | Missing or ACL-hidden document, conversation, job |
| 409 | `conflict` | Duplicate signup email |
| 422 | `validation_error` | Pydantic or `ValidationFailedError` |
| 429 | `rate_limited` | `RateLimitMiddleware` (body has no `request_id`) |
| 402 | `budget_exceeded` | Type exists; no chat call site was found that raises it |
| 501 | `provider_not_implemented` | Catalog provider without an adapter |
| 502 | `platform_error` or `connector_error` | Ollama or connector failure |
| 500 | `platform_error` | Unhandled exception; detail is generic |
| 503 | none | Ready check returns `{"status":"unavailable"}` without the problem envelope |

### Pagination

Query `limit` and `offset` on list routes. FastAPI bounds are usually `limit` 1–100 default 100, `offset` ≥ 0. Audit log route allows `limit` ≤ 200. Services also call `clip_limit` / `clip_offset` (`backend/app/api/pagination.py`, max 100). There is no cursor and no `Link` header. Responses are JSON arrays, not `{items, total}` envelopes, unless a specific handler returns an object (called out below).

### Idempotency

No `Idempotency-Key` header. Ingestion uniqueness is the database constraint on `ingestion_jobs.idempotency_key`. Repeating an upload of the same bytes for the same source file returns `status: unchanged` without a new job. Refresh rotates tokens; repeating the old refresh value fails once the row is revoked.

### Rate limit and CORS

See [SECURITY.md](SECURITY.md). General cap is 180/60s in `create_app` (the class default of 120 is overridden). Auth cap defaults to 10/60s.

## Auth — prefix `/api/v1/auth`

| Method | Endpoint | Purpose | Authentication | Request | Response | Errors |
| --- | --- | --- | --- | --- | --- | --- |
| GET | `/features` | Public signup flag | None | — | `{public_signup: bool}` | — |
| POST | `/signup` | Create user and tenant | None | JSON `email`, `password` (≥10), `tenant_name` | Token object from `_issue_session` | 403 if flag off; 409 duplicate email; 422 |
| POST | `/login` | Password login | None | JSON `email`, `password`, optional `tenant_id` or `tenant_slug` | `access_token`, `refresh_token`, `token_type`, `expires_in`, `tenant_id`, `user_id` | 401; 422 if non-super-admin omits tenant |
| POST | `/refresh` | Rotate refresh token | None (refresh body) | JSON `refresh_token` | New token object | 401 invalid; 403 inactive tenant |
| POST | `/logout` | Revoke refresh hash | None | JSON `refresh_token` | `{ok: true}` even if unknown | — |
| POST | `/switch-tenant` | New tokens for another membership | Bearer | JSON `tenant_id` | Token object | 403 super admin or non-member or inactive |
| POST | `/accept-invite` | Set password from invite token | None | JSON `token`, `password` (≥10) | Token object | 401/422 from service if token bad |
| POST | `/forgot-password` | Start reset | None | JSON `email`, `tenant_slug` | Service payload (may include dev token outside production) | 422 empty slug |
| POST | `/reset-password` | Consume reset token | None | JSON `token`, `password` (≥10) | Service payload | 401/422 |
| GET | `/me` | Hydrated profile | Bearer | — | `user_id`, `email`, `name`, tenant fields, `workspace_id`, `roles`, `permissions`, `teams`, `is_super_admin`, `last_login_at` | 401, 403 |

## Health — prefix `/api/v1`

| Method | Endpoint | Purpose | Authentication | Request | Response | Errors |
| --- | --- | --- | --- | --- | --- | --- |
| GET | `/health/live` | Process up | None | — | `{status: ok}` | — |
| GET | `/health/ready` | Database `SELECT 1` | None | — | `{status: ok}` | 503 `{status: unavailable}` |
| GET | `/health` | Configured providers and Ollama tags | None | — | `status` `ok` or `degraded`, environment, provider names, `ollama` object | Probe errors become `reachable: false`, HTTP 200 |

## Identity — prefix `/api/v1`

| Method | Endpoint | Purpose | Authentication | Request | Response | Errors |
| --- | --- | --- | --- | --- | --- | --- |
| GET | `/tenants` | Tenants for the caller | Bearer | `limit`, `offset` | Array from `list_tenants` | 401 |
| GET | `/users` | Tenant users | `user:manage` or `users.view` | `limit`, `offset` | Array | 403 |
| POST | `/users` | Direct invite with password | `user:manage` | JSON email, password, role (`InviteIn`) | Service dict | 403, 422 |
| POST | `/users/invitations` | Email invitation | `users.create` or `user:manage` | JSON invitation body | Service dict | 403, 422 |
| PATCH | `/users/{user_id}` | Update user, roles, status | any of `users.update`, `users.disable`, `roles.assign`, `user:manage` | JSON patch | Service dict | 403, 404 |
| POST | `/users/{user_id}/resend-invite` | Resend | `users.create` or `user:manage` | — | Service dict | 403 |
| POST | `/users/{user_id}/revoke-sessions` | Revoke refresh rows | `users.update`, `users.disable`, or `user:manage` | — | Service dict | 403 |
| GET | `/permissions` | Permission catalog | `roles.view` or `user:manage` | — | Array | 403 |
| GET | `/workspaces` | Workspaces | Bearer via `get_context` | `limit`, `offset` | Array | 401 |
| POST | `/workspaces` | Create workspace | `workspace:manage` | JSON `name`, optional organization | Service dict | 403 |
| GET | `/roles` | Roles and their permission codes | Bearer tenant member. `list_roles` does not check `roles.view` | `limit`, `offset` | Array of role payloads including permission codes | 401 |
| POST | `/roles` | Create role | `roles.create` or `user:manage` | JSON name and permission codes | Role payload | 403 |
| PUT | `/roles/{role_id}` | Replace role | `roles.update` or `user:manage` | JSON | Role payload | 403, 404 |
| PATCH | `/roles/{role_id}` | Same handler as PUT | same | same | same | same |
| DELETE | `/roles/{role_id}` | Delete non-system role | `roles.delete` or `user:manage` | — | Service dict | 403 |
| GET | `/teams` | Teams | Bearer | `limit`, `offset` | Array | 401 |
| POST | `/teams` | Create team | `team:manage` | JSON name, optional workspace | Service dict | 403 |
| POST | `/teams/{team_id}/members` | Add member | `team:manage` | JSON `user_id` | Service dict | 403 |

`GET /roles` and `GET /teams` depend on `get_context` only. Further checks, if any, are inside `IdentityService`.

## Platform — prefix `/api/v1/platform`

Every route depends on `require_super_admin`. A tenant JWT without `sa` receives 403 `Super admin required`.

| Method | Endpoint | Purpose | Request | Response | Errors |
| --- | --- | --- | --- | --- | --- |
| GET | `/tenants` | List all tenants | `limit`, `offset` | Array | 403 |
| POST | `/tenants` | Create a customer tenant | JSON name and admin fields (`create_platform_tenant`) | Tenant payload | 403, 422 |
| GET | `/tenants/{tenant_id}` | One tenant | — | Tenant payload plus admins | 404 |
| PATCH | `/tenants/{tenant_id}` | Status or name | JSON patch | Tenant payload | 403 |
| GET | `/ai-catalog` | YAML `ai_catalog.llm` entries | — | Catalog | 403 |
| GET | `/audit-logs` | Platform audit rows | `limit`, `offset` | Array | 403 |

## Tenant AI — prefix `/api/v1/tenant`

| Method | Endpoint | Purpose | Authentication | Request | Response | Errors |
| --- | --- | --- | --- | --- | --- | --- |
| GET | `/ai-config` | Effective AI fields | any of `ai.configuration.view`, `tenant.settings.view`, `config:read` | — | `ai_config_payload` | 403 |
| PUT | `/ai-config` | Update overlay fields | any of `ai.configuration.update`, `tenant.settings.update`, `config:write` | JSON provider, model, temperature, max_tokens, system_instructions, rag_enabled (all optional) | `put_ai_config` result | 403, 422 |

## Folders — prefix `/api/v1`

Authentication is Bearer. Permission checks are inside `FolderService`, not `require_permission`.

| Method | Endpoint | Purpose | Service gate | Request | Errors |
| --- | --- | --- | --- | --- | --- |
| GET | `/folders` | List | `folders.view` sees all; else viewable subset | `limit`, `offset` | 401 |
| POST | `/folders` | Create | `folders.create` | JSON `name`, optional `parent_id`, `workspace_id` | 403 |
| GET | `/folders/{folder_id}` | Get | view rule | — | 404 |
| PATCH | `/folders/{folder_id}` | Rename or reparent | `folders.update` plus edit rule | JSON | 403, 404 |
| DELETE | `/folders/{folder_id}` | Delete | `folders.delete` | — | 403, 404 |
| GET | `/folders/{folder_id}/share` | List grants | view | — | 404 |
| POST | `/folders/{folder_id}/share` | Grant | `folders.share` | JSON subject, actions, deny, email or user or role | 403, 422 |
| DELETE | `/folders/{folder_id}/grants/{grant_id}` | Remove grant | `folders.share` | — | 404 |
| DELETE | `/folders/{folder_id}/share/{grant_id}` | Same handler | same | — | 404 |

## Documents — prefix `/api/v1`

| Method | Endpoint | Purpose | Authentication | Request | Response | Errors |
| --- | --- | --- | --- | --- | --- | --- |
| POST | `/documents` | Upload and, for in-process queues, index before the response | `document:write` | multipart `file`; form `workspace_id` optional; `visibility` `private` or `tenant`; `allowed_roles` JSON array or comma-separated | `document_id`, `version_id`, `status` (`queued` updated to job status, `unchanged`, or `deduplicated`), optional `job_id`, `error`, `version_new`, `canonical_version_id` | 403, 404 workspace, 422 size or role or visibility |
| GET | `/documents` | ACL-filtered list | `document:read` | `limit`, `offset` | Array of id, title, path, classification, version status, owner, `acl`, storage fields | 403 |
| GET | `/documents/{document_id}/versions` | Versions | `document:read` plus `can_read_document` and live document | — | Array of id, version_number, status, content_hash, derived id, created_at | 404 if hidden |
| POST | `/documents/{document_id}/acl` | Replace provided ACL fields | Route: `document:read`. Service: `can_share_document` | JSON `DocumentAclIn`: allowed and denied users, emails, roles, groups, `visibility` | `{id, acl}` | 404 if not owner/admin; 422 unknown role or email not in tenant |

Upload is not safe to retry blindly after a timeout: the server may have committed a completed index if the client gave up after the server finished. Same-byte retry returns `unchanged`.

## Connectors — prefix `/api/v1`

| Method | Endpoint | Purpose | Authentication | Notes |
| --- | --- | --- | --- | --- |
| GET | `/connectors/catalog` | Adapter catalog | `document:read` | Mocks only if `RAG_CONNECTOR_MOCKS` |
| GET | `/connectors/oauth/clients` | OAuth client display | `source:manage` | |
| PUT | `/connectors/oauth/clients` | Save OAuth clients | `source:manage` | |
| GET | `/connectors/local-fs/browse` | Browse allowed roots | `source:manage` | |
| GET | `/connectors` | List sources the caller may see | Bearer. Service requires `document:read` or `source:manage`. Without `source:admin`, only rows owned by the caller. Excludes `connector_type=upload` and `disconnected` | `limit`, `offset` |
| POST | `/connectors` | Create source | `source:manage` | JSON connector type and config |
| POST | `/connectors/oauth/start` | Start OAuth | `source:manage` | Returns state / URL |
| POST | `/connectors/oauth/callback` | Finish OAuth | `source:manage` | |
| GET | `/connectors/{source_id}/health` | Connector health | `source:manage` and ownership | |
| DELETE | `/connectors/{source_id}` | Disconnect | `source:manage` | |
| GET | `/connectors/{source_id}/locations` | Root locations | `source:manage` | |
| GET | `/connectors/{source_id}/locations/{location_id}/children` | Children | `source:manage` | |
| POST | `/connectors/{source_id}/resolve-location` | Resolve a path | `source:manage` | |
| POST | `/connectors/{source_id}/subscriptions` | Watch a location | `source:manage` | |
| GET | `/subscriptions` | List subscriptions | Bearer. Service requires `document:read`, `source:manage`, or `source:admin`. Without `source:admin`, only the caller's sources | |
| PATCH | `/subscriptions/{subscription_id}` | Update schedule, filters, ACL | `source:manage` | |
| DELETE | `/subscriptions/{subscription_id}` | Remove | `source:manage` | |
| POST | `/subscriptions/{subscription_id}/sync` | Sync now, inline `process_job` | `source:manage` | 422 if paused |
| GET | `/subscriptions/{subscription_id}/sync-history` | Past `sync_runs` | `source:manage` | |

Ownership failures use `can_manage_source`. Hidden sources are 404 in the paths that call `_require_owned_source`.

## Chat — prefix `/api/v1`

| Method | Endpoint | Purpose | Authentication | Request | Response | Errors |
| --- | --- | --- | --- | --- | --- | --- |
| POST | `/chat` | RAG answer | `document:read` | JSON `question`, optional `conversation_id`, `workspace_id`, `version_id` | `conversation_id`, `message_id`, `answer`, `citations` | 403, 404 conversation or version, 502 Ollama |
| POST | `/chat/stream` | SSE tokens | `document:read` | Same JSON | `text/event-stream` events `retrieval.completed`, `generation.started`, `token`, `citations`, `generation.completed` or `error` | Authorize failures happen before the stream (403/404). Generation failures are SSE `error` |
| GET | `/conversations` | Caller's conversations | `conversation:read` | `limit`, `offset` | id, title, updated_at | 403 |
| DELETE | `/conversations` | Delete all of the caller's conversations | `conversation:delete` | — | `{deleted: n}` | 403 |
| DELETE | `/conversations/{conversation_id}` | Delete one | `conversation:delete` | — | `{id, status: deleted}` | 404 if not owner |
| GET | `/conversations/{conversation_id}` | Messages | `conversation:read` | — | Messages; citations dropped when ACL fails now | 404 |
| POST | `/messages/{message_id}/feedback` | Rating | Bearer only | JSON `rating`, optional `reason` | `{id}` | 404 if message not in caller's conversation |

`ChatService.authorize_ask` also accepts `conversation:write` or `ai.chat`, but the route never calls it unless `document:read` already passed.

Conversations are always filtered to `user_id = caller`. There is no tenant-admin read of another user's chats in these handlers.

## Eval — prefix `/api/v1/eval`

| Method | Endpoint | Purpose | Authentication | Request | Errors |
| --- | --- | --- | --- | --- | --- |
| POST | `/datasets` | Create dataset | `config:write` | JSON name, description | 403 |
| GET | `/datasets` | List | `config:read` | `limit`, `offset` | 403 |
| POST | `/datasets/{dataset_id}/items` | Add question | `config:write` | JSON question, expected answer/sources | 403 |
| GET | `/datasets/{dataset_id}/items` | List items | `config:read` | — | 403 |
| POST | `/datasets/{dataset_id}/runs` | Run dataset through chat scoring | `config:write` | — | 403 |
| GET | `/runs/{run_id}` | Run and results | `config:read` | — | 404 |

Runs execute inside the request (`backend/app/application/eval.py`), not on a worker.

## Admin — prefix `/api/v1`

| Method | Endpoint | Purpose | Authentication | Request | Response | Errors |
| --- | --- | --- | --- | --- | --- | --- |
| GET | `/config` | YAML plus tenant overlay, redacted | `config:read` | — | Settings object | 403 |
| PUT | `/config` | Merge tenant overlay | `config:write` | JSON `{payload: object}` | `{ok, version}` | 403 `overlay_denied` |
| GET | `/jobs` | Jobs the caller may see | `job:read` | `limit`, `offset` | id, status, job_type, error, document_id | 403 |
| POST | `/jobs/{job_id}/retry` | `run_ingestion_job` | Bearer; `document:write` unless `document:read_all` or `source:admin`; must read the document or manage the source | — | `{ok, job_id}` | 403, 404 |
| GET | `/audit-logs` | Tenant audit | `audit:read` | `limit` ≤ 200, `offset` | id, action, resource_type, resource_id, created_at | 403 |
| GET | `/usage` | Sum of `usage_events` | `audit:read` | — | events, token sums, estimated cost | 403 |
| GET | `/admin/stats` | Counts of active documents and jobs | `audit:read` | — | `documents`, `jobs`, `failed_jobs` | 403 |
| POST | `/admin/reindex` | `reembed_active` | `document:write` | — | embedded, failed, skipped, provider, model | 403, 502 from embedder counted as `failed` per document |

`GET /admin/stats` counts documents with `external_status=active` and does **not** apply document ACL. It excludes `mock_*` sources unless mocks are enabled. A caller with `audit:read` can learn a tenant-wide document count.

## SPA

`mount_spa` serves built frontend files for non-API paths when the static directory exists (`backend/app/api/frontend.py`). Those are not versioned JSON routes.
