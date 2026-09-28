# Low-level design (as implemented)

## Connector contract

`DataSourceConnector` (`domain/ports/connector.py`):

- `connect` / `disconnect`
- `authorization_url` / `authenticate` / `refresh_authentication`
- `list_locations` / `browse`
- `list_files` / `get_file` / `get_metadata` / `detect_changes`
- `health_check`

Adapters: `backend/app/adapters/providers/connectors/mock.py`, registered as:

- `mock_google_drive` (oauth2)
- `mock_onedrive` (oauth2)
- `mock_dropbox` (oauth2)
- `mock_s3` (none)
- `mock_local_fs` (none)

Simulate failures with `connector_config.simulate`: `auth_expired` | `rate_limit` | `network` | `partial_sync`.

## Identity and diff

`application/sync_diff.py` compares previous vs current files by **provider file id**.

Outcomes: CREATED, UPDATED (revision/checksum), MOVED (same id, new path/name), DELETED.

Ingest for connectors uses `source_file_id=<provider id>`, `external_revision`, optional `subscription_id`.

Unique index: `uq_documents_source_file` on `(tenant_id, source_id, source_file_id)`.

## Sync execution

`ConnectorService.sync_subscription`:

1. Load subscription + source + decrypted credentials.
2. `list_files` (respect include_subfolders / filters).
3. Diff vs existing documents for that source.
4. Ingest new/updated bytes through `IngestionService.ingest_content`.
5. Mark deleted externals; do not drop versions.
6. Write `sync_runs` stats. Failed runs are **recorded**, not used to abort the HTTP transaction blindly.

Subscribe triggers an initial sync. Manual sync is `POST /api/v1/subscriptions/{id}/sync`. Idempotent retry: same checksum → skipped.

## OAuth (generic, mock)

1. `POST /connectors/oauth/start` stores `oauth_states` and returns an authorization URL.
2. UI reads `code` + `state` from that URL (mocks do not redirect to Google).
3. `POST /connectors/oauth/callback` exchanges code, encrypts tokens, creates `data_sources`.

Repeated/invalid callbacks fail closed (state single-use / expiry). Tokens are not logged.

## Chat prepare vs generate

`ChatService._prepare`: permission check → conversation → rewrite → retrieve → `_authorized_hits` → rerank.

`ask` then `_generate` (full `llm.generate`).

`stream_ask` then `llm.stream`, then `_citations_for`, then persist.

Citation rules (`_citations_for`):

- `[n]` must match a retrieved source index.
- Invented `[99]` is dropped.
- If the model used only invented ids, citations are empty.
- If the model used no markers, attach up to three retrieved sources (UI still shows evidence).

## Streaming transport

`POST /api/v1/chat/stream` → `text/event-stream` frames `data: {json}\n\n`.

Events: `retrieval.completed`, `generation.started`, `token`, `citations`, `generation.completed`, `error`.

The HTTP transaction stays open for the duration of generation (same session as the rest of the API).

## Schema additions (Alembic `003_connectors`)

Tables (RLS + tenant policy): `oauth_states`, `connector_credentials`, `source_subscriptions`, `sync_runs`.

`documents`: `subscription_id`, `external_revision`, `external_status`.
