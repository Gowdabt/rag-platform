# Deployment and infrastructure

## What exists

| Artifact | Path | Role |
| --- | --- | --- |
| API image | `docker/Dockerfile.api` | Python 3.12-slim, `pip install -e .`, `uvicorn app.main:app --host 0.0.0.0 --port 8000` |
| Frontend image | `docker/Dockerfile.frontend` | Vite dev/build image used by Compose (see that Dockerfile) |
| Compose | `docker/docker-compose.yml` | postgres, redis, minio, ollama, api, worker, frontend |
| CI | `.github/workflows/ci.yml` | lint, migrate, pytest; frontend `npm ci` and `npm run build` |
| Local scripts | `scripts/start.sh`, `scripts/stop.sh`, `scripts/restart.sh`, `scripts/bootstrap-local.sh` | Host processes |
| Config | `configs/base.yaml` plus `development.yaml` / `staging.yaml` / `production.yaml` | Layered settings |
| Example env | `.env.example` | Secret names, not committed secrets |

No Kubernetes, Helm, Terraform, or cloud account manifests are in the repository. No ingress or load balancer is defined. Compose publishes ports on the host directly.

## Local development (scripts/start.sh)

The script sources `scripts/_dev.sh`, loads repo-root `.env` if present, and forces `RAG_CONFIG_DIR` to `configs/`. It starts:

- API: `http://127.0.0.1:8000` via the backend virtualenv uvicorn.
- UI: `http://127.0.0.1:5173` (and localhost).

It does **not** start Postgres, Redis, or Ollama. There is no desktop app. The header comment states ingestion runs in-process because `queue.provider=asyncio`, so there is no separate worker. PIDs and logs go to `.run/` (gitignored). If port 8000 or 5173 is held by a process that is not this repo, the script exits.

`configs/development.yaml` sets:

- `platform.environment: development`
- `queue.provider: asyncio`
- `storage.provider: local_fs`, bucket `data/objects`
- `llm.provider: ollama`, model `llama3.2`, `api_base: http://127.0.0.1:11434`, temperature 0.3, max_tokens 1200
- `embedding.provider: ollama`, model `nomic-embed-text`, dimensions 768
- `reranker.provider: identity`, `retrieval.strategy: hybrid`, `top_k: 12`
- `email.provider: console`, `public_app_url: http://localhost:5173`
- `observability.log_level: DEBUG`

Base YAML still points `database.url` at `secret://env/DATABASE_URL` and `redis.url` at `secret://env/REDIS_URL`. `.env.example` uses `postgresql+asyncpg://rag:rag@localhost:5432/rag` and `redis://localhost:6379/0`. The user note that local Postgres is version 17 on port 5432 matches the example URL host and port. The server version is not pinned by the script. Compose pins `pgvector/pgvector:pg16`.

Frontend dev client uses `VITE_API_URL` or, in Vite dev, `http://127.0.0.1:8000` (`frontend/src/api/client.ts`).

## Docker Compose

```mermaid
flowchart TB
  subgraph host [Host ports]
    p5432[5432 Postgres]
    p6379[6379 Redis]
    p9000[9000 MinIO API]
    p9001[9001 MinIO console]
    p11434[11434 Ollama]
    p8000[8000 API]
    p5173[5173 frontend]
  end
  subgraph compose [docker-compose.yml]
    pg[postgres pgvector pg16]
    redis[redis 7 alpine]
    minio[minio]
    ollama[ollama]
    api[api uvicorn]
    worker[worker python -m app.workers.main]
    fe[frontend]
  end
  p5432 --> pg
  p6379 --> redis
  p9000 --> minio
  p11434 --> ollama
  p8000 --> api
  p5173 --> fe
  api --> pg
  api --> redis
  worker --> pg
  worker --> redis
  fe --> api
```

The Redis arrows are **network dependencies in Compose**, not application protocol usage. The API and worker containers receive `REDIS_URL` but application code does not open it. See [HLD.md](HLD.md).

API and worker environment (Compose):

- `RAG_ENV=development` so `configs/development.yaml` overrides base.
- `DATABASE_URL=postgresql+asyncpg://rag:rag@postgres:5432/rag`
- `DATABASE_URL_SYNC=postgresql+psycopg://rag:rag@postgres:5432/rag`
- `REDIS_URL=redis://redis:6379/0`
- S3 endpoint `http://minio:9000`, keys `ragminio` / `ragminio_secret`, bucket `rag-documents`
- `JWT_SECRET=local-dev-only-not-for-production`
- `OLLAMA_BASE_URL=http://ollama:11434`

Development YAML **replaces** `llm.api_base` with `http://127.0.0.1:11434`, so the Compose `OLLAMA_BASE_URL` does not affect the LLM base when `RAG_ENV=development`. `OllamaEmbedding` ignores both and always uses `http://127.0.0.1:11434` (`backend/app/adapters/providers/embeddings/ollama.py`). Development YAML also sets `storage.provider: local_fs`, so the MinIO environment variables are unused unless an overlay or a different env YAML selects `s3`.

The worker command is `python -m app.workers.main`. That process sets the in-process job handler and blocks on a stop event. `AsyncioJobQueue.enqueue` does not call the handler. Jobs created by the API are processed inside the API request. The worker container does not consume a queue.

Postgres healthcheck: `pg_isready -U rag -d rag`. Redis: `redis-cli ping`. API `depends_on` those healthy services. Frontend depends on API with no health condition.

Volumes: `postgres_data`, `minio_data`, `ollama_data`. Configs are mounted read-only at `/configs`.

JWT in Compose is `local-dev-only-not-for-production` (shorter than 32 characters and contains a placeholder pattern). `enforce_runtime_safety` **warns** outside production and **raises** in production. Compose sets `RAG_ENV=development`, so the process is allowed to start with that secret.

## CI

Job `lint-test` on `ubuntu-latest`:

- Service `pgvector/pgvector:pg16` on 5432, user/db `rag`/`rag`.
- Python 3.12, `pip install -e ".[dev]"` in `backend/`.
- `ruff check backend/app tests`
- `alembic upgrade head` from `backend/`
- `PYTHONPATH=backend RAG_CONFIG_DIR=configs pytest tests -q --tb=short`
- Env: `RAG_ENV=development`, `JWT_SECRET` a 32+ byte CI value, `RAG_ALLOW_PUBLIC_SIGNUP=1`, `RAG_DB_NULL_POOL=1`
- CI does **not** start Redis, MinIO, or Ollama.

Job `frontend`: Node 20, `npm ci`, `npm run build` in `frontend/`.

No deploy job, no image publish step.

## Web client

The UI is the Vite app. A production build with an empty `VITE_API_URL` calls the API on the same origin (`frontend/src/api/client.ts`). CORS defaults are the Vite dev origin and the API origin (`HttpConfig`).

## Config hierarchy

Load path (`backend/app/config/load.py`):

1. `load_dotenv()` then the first `.env` found walking parents of the config module. Existing environment variables are not overridden (`override=False`).
2. `RAG_CONFIG_DIR` if it contains `base.yaml`, else a parent `configs/` directory.
3. Deep-merge `base.yaml` with `{RAG_ENV}.yaml` (`RAG_ENV` default `development`).
4. Optional overlays passed to `load_platform_settings`.
5. `PlatformSettings` validation. Unknown provider names in `KNOWN_PROVIDERS` fail validation. Missing adapter registration fails later at `registry.get`.

Per request, `get_tenant_settings` merges `config_overlays` where `scope_type=tenant` for the caller’s tenant. Parse failures return the unmerged settings.

`PUT /api/v1/config` checks `assert_overlay_allowed(..., "tenant")` then merges into the overlay and increments `version`.

`PUT /api/v1/tenant/ai-config` writes a narrower AI payload via `put_ai_config` (`backend/app/application/tenant_ai.py`).

### Secret refs

`secret://env/VAR` in YAML. Base file uses this for `DATABASE_URL`, `OLLAMA_BASE_URL`, S3 settings, `REDIS_URL`, `JWT_SECRET`. Resolution is explicit (`resolve_secrets`). Application startup uses `resolve=False`. JWT resolution happens at token issue/decode. Database URL resolution happens in `init_engine`.

### Environment variables that change behavior

| Variable | Effect | Default if unset |
| --- | --- | --- |
| `RAG_ENV` | Which YAML layer loads | `development` |
| `RAG_CONFIG_DIR` | Config directory | discovered `configs/` |
| `DATABASE_URL` | Async SQLAlchemy URL when YAML uses `secret://env/DATABASE_URL` | required to resolve |
| `DATABASE_URL_SYNC` | Alembic / psycopg | `.env.example` only; app engine uses `database.url` |
| `JWT_SECRET` | HS256 key | required; production refuses short or placeholder values |
| `RAG_ALLOW_PUBLIC_SIGNUP` | Enables `POST /auth/signup`; production refuses the process if set | off |
| `RAG_AUTH_RATE_LIMIT` | Auth route cap | 10 |
| `RAG_AUTH_RATE_WINDOW` | Auth window seconds | 60 |
| `RAG_DB_NULL_POOL` | NullPool when `1` | off (on under pytest) |
| `RAG_RATE_LIMIT_DB` | Force DB rate-limit counters under pytest | off during tests |
| `EMAIL_PROVIDER`, `SMTP_*`, `RESEND_API_KEY`, `PUBLIC_APP_URL`, `EMAIL_FROM_*` | Mail; production checks in `email_config_unsafe` | console in development YAML |
| `PLATFORM_SUPERADMIN_EMAIL`, `PLATFORM_SUPERADMIN_PASSWORD` | Seed super admin | `.env.example` placeholders |
| `RAG_CONNECTOR_MOCKS` | Include `mock_*` connectors in the catalog | off |
| `CONNECTOR_FS_ROOTS` | Local filesystem connector roots | empty in example |
| `GOOGLE_OAUTH_CLIENT_ID/SECRET`, `MICROSOFT_OAUTH_*`, `DROPBOX_OAUTH_*` | OAuth apps | unset |
| `OPENAI_API_KEY` | Used by `OpenAIEmbedding` if set | unset |
| `OLLAMA_BASE_URL` | Resolves `llm.api_base` when the YAML value is still `secret://env/OLLAMA_BASE_URL` | development YAML hardcodes the LLM base instead |
| `VITE_API_URL` | Frontend API origin | dev default `http://127.0.0.1:8000` |
| `RAG_EXPOSE_INVITE_TOKENS` | `expose_dev_tokens` even in production | off |

Feature flags in code are these environment booleans (`backend/app/core/flags.py`), not a flag service. `generation.rag_enabled` is a tenant AI setting, not an env flag.

### Production YAML

`configs/production.yaml` sets `platform.environment: production`, email provider `smtp`, example from-address and `https://example.com`, `otel_enabled: true`, and **localhost CORS origins** copied from development. `enforce_runtime_safety` will refuse boot if JWT is weak, public signup is on, CORS contains `*`, email is console, from-address is localhost, or `PUBLIC_APP_URL` contains localhost. The file’s `public_app_url: https://example.com` is a placeholder. Rationale for shipping localhost CORS in the production file: "Rationale not evident from repository."

Staging YAML only sets environment name, log level INFO, and `otel_enabled: true`. It inherits base queue `taskiq_redis` and base storage `s3`. That queue name still constructs `AsyncioJobQueue`.

## Process model

```mermaid
flowchart LR
  subgraph local [scripts/start.sh]
    u[uvicorn :8000]
    v[vite :5173]
  end
  u -->|in-process process_job| u
  u -->|scheduler_loop| u
  v -->|HTTP| u
```

```mermaid
flowchart LR
  subgraph containers [Compose]
    api[api]
    w[worker idle wait]
  end
  api -->|in-process process_job| api
  api -->|scheduler_loop| api
  w -->|no dequeue| w
```

## Health

| Path | Auth | Behavior |
| --- | --- | --- |
| `GET /api/v1/health/live` | none | `{"status":"ok"}` |
| `GET /api/v1/health/ready` | none | `SELECT 1` or 503 |
| `GET /api/v1/health` | none | Provider names plus Ollama tag probe; `degraded` if unreachable |

Ready does not check Ollama, Redis, or object storage.

## Logging

stdout JSON via structlog. No file shipper, no metric endpoint. `x-request-id` correlation is described in [SECURITY.md](SECURITY.md) and [LLD.md](LLD.md).
