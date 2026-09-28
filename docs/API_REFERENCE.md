# API reference (as implemented)

Base: `http://127.0.0.1:8000`. JSON unless noted. Bearer access token except health/auth signup/login.

OpenAPI: `http://127.0.0.1:8000/docs`.

## Health

- `GET /health`
- `GET /ready`

## Auth

- `POST /api/v1/auth/signup` `{email, password, tenant_name}`
- `POST /api/v1/auth/login` `{email, password}`
- `POST /api/v1/auth/refresh`
- `GET /api/v1/auth/me`

## Documents

- `GET /api/v1/documents`
- `POST /api/v1/documents` multipart `file`, optional `workspace_id`
- `GET /api/v1/documents/{id}/versions`

## Connectors / sources

- `GET /api/v1/connectors/catalog`
- `GET /api/v1/connectors`
- `POST /api/v1/connectors` `{connector_type, name?}` (non-OAuth mocks)
- `DELETE /api/v1/connectors/{id}`
- `POST /api/v1/connectors/oauth/start` `{connector_type, redirect_uri?}`
- `POST /api/v1/connectors/oauth/callback` `{code, state}`
- `GET /api/v1/connectors/{id}/locations`
- `GET /api/v1/connectors/{id}/locations/{location_id}/children`
- `POST /api/v1/connectors/{id}/subscriptions` `{location_id, location_name, include_subfolders?, file_filters?, schedule?}`
- `GET /api/v1/subscriptions/{id}`
- `PATCH /api/v1/subscriptions/{id}` `{status?, schedule?, ...}` (`paused` / `active`)
- `DELETE /api/v1/subscriptions/{id}`
- `POST /api/v1/subscriptions/{id}/sync`
- `GET /api/v1/subscriptions/{id}/sync-history`

Mutations require `source:manage`. Catalog/list need a valid session (`document:read` for catalog).

## Chat

- `POST /api/v1/chat` `{question, conversation_id?, workspace_id?}`
- `POST /api/v1/chat/stream` same body, SSE `data: {event,...}`
- `GET /api/v1/conversations`
- `GET /api/v1/conversations/{id}`
- `POST /api/v1/messages/{id}/feedback` `{rating, reason?}`

Stream events: `retrieval.completed`, `generation.started`, `token`, `citations`, `generation.completed`, `error`.

## Eval

- `GET /api/v1/eval/datasets`
- `POST /api/v1/eval/datasets`
- `POST /api/v1/eval/datasets/{id}/items`
- `POST /api/v1/eval/datasets/{id}/runs`

## Admin / identity

- `GET /api/v1/admin/stats`
- `GET /api/v1/jobs`
- `GET /api/v1/audit-logs`
- `GET /api/v1/usage`
- `GET /api/v1/config` (redacted)
- `PUT /api/v1/config` (denylist enforced)
- Users/teams under `/api/v1/users`, `/api/v1/teams` as implemented in `identity.py` / `admin.py`
