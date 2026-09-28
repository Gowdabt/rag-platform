# Operations (as implemented)

## Local run

```bash
make bootstrap    # Postgres + migrate
make api          # :8000 — source .env in the shell (JWT_SECRET, DATABASE_URL)
make frontend     # :5173
```

Migrate only: `make migrate` → `alembic upgrade head` with `RAG_CONFIG_DIR=../configs`.

Health: `GET /health`, `GET /ready`.

## Jobs

Ingestion uses `queue.provider=asyncio` in development: the API process runs jobs. `taskiq_redis` adapter exists for a real worker; local compose may include Redis.

Admin: `GET /api/v1/jobs`, documents, audit logs, usage, redacted config.

## Connectors / sync

No cron. Operators (or the UI **Sync now**) call `POST /api/v1/subscriptions/{id}/sync`.

Watch `sync_runs` and source `last_error`. Auth expiry returns `CONNECTOR_AUTH_EXPIRED`.

## Observability

- `RequestIdMiddleware` — correlation id on requests
- Structured logging via `configure_logging`
- `retrieval_events` and `usage_events` tables
- Rate limit middleware (180 req / 60s)

There is **no** Prometheus histogram set (p50/p95/p99) in-process yet. Latency is stored per chat `retrieval_events.latency_ms`.

Do not emit high-cardinality labels (raw questions, token values, file bytes).

## Backups

Postgres is the source of truth. Object blobs live under `storage.bucket` (`data/objects` locally). Backup both.

## Feature flags

Config overlays + YAML. No separate flag service.
