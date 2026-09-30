# RAG Platform

Self-hosted / SaaS **multi-tenant retrieval-augmented generation** platform. Tenants get isolated knowledge, chat with citations, folder ACL, connectors, and an optional tenant-level AI overlay. You can run it on one machine (Postgres + API + Vite) or operate it as a multi-tenant SaaS with a platform Super Admin.

**Stack:** FastAPI backend, React + Vite frontend, PostgreSQL + pgvector + Postgres FTS. Providers are swapped in YAML. **No LangChain**, LlamaIndex, or Haystack.

Development can run without Ollama (extractive LLM + hashing embeddings). Switch `llm` / `embedding` in `configs/development.yaml` to `ollama` (or a registered cloud provider) when you want real models.

## Roles and access

| Actor | How they sign in | What they can do |
| --- | --- | --- |
| **Super Admin** | Email + password, **no tenant slug** | Platform tenants, catalog, platform audit. Seeded from `PLATFORM_SUPERADMIN_EMAIL` / `PLATFORM_SUPERADMIN_PASSWORD` on API startup. |
| **Tenant Admin** | Tenant slug + email + password | Users, custom roles, folders, documents, connectors, tenant AI overlay, audit. |
| **Custom tenant roles** | Same tenant login | Permissions you assign (`documents.view`, `ai.chat`, `folders.share`, …). Built-in Admin / Member still exist. |

**Folder ACL is deny-by-default.** An empty document ACL denies read. Folder grants (`ResourcePermission`) inherit down the parent chain and are compiled onto documents in the subtree so retrieval SQL enforces them. Revoke/move recompiles; leftover empty ACL still denies non-owners.

Authorization is layered: JWT → PostgreSQL RLS (`SET LOCAL app.tenant_id`, `FORCE ROW LEVEL SECURITY`) → route permissions → document/folder ACL **before** rerank and LLM. The model is not an authorization layer.

Public self-serve signup is **off by default** (`RAG_ALLOW_PUBLIC_SIGNUP` unset/false). Enable it only for local demos.

## Retrieval and models

- **Hybrid search:** Postgres FTS (sparse) + pgvector (dense), fused with reciprocal rank fusion. Hashing embeddings skip dense search (dev/offline).
- **Ollama** is the default local LLM/embedding provider (`llama3.2` / `nomic-embed-text` in development YAML).
- **Registered providers** (YAML plugin registry): extractive, OpenAI, Anthropic, and others on the platform allow-list — tenant overlays cannot pick a model that is not catalogued.
- **Tenant AI overlay:** Tenant admins set provider/model/temperature/instructions within the platform catalog; secrets stay in env / secret refs, not in overlay YAML dumps.

Ingest path: upload or connector → mime validate → object storage (local CAS or S3) → parse → chunk → embed → FTS + pgvector. Identical bytes are content-addressed and reused per tenant.

## Connectors

| ID | Auth | Notes |
| --- | --- | --- |
| `local_fs` | none | Directory the **API host** can read (`CONNECTOR_FS_ROOTS`). Identity is inode, so renames stay the same document. |
| `s3` | keys / env | Live S3 or MinIO. |
| `google_drive` | OAuth2 | Drive API v3. |
| `onedrive` | OAuth2 | Microsoft Graph. |
| `sharepoint` | OAuth2 | Same Azure app / Graph client; libraries as drives. |
| `dropbox` | OAuth2 | List + download. |

OAuth client IDs/secrets belong in `.env` (never commit them). Redirect URI must match the UI origin (typically `http://127.0.0.1:5173/sources`). Tokens are encrypted at rest.

## Architecture

**Modular monolith:** one FastAPI process (auth, documents, connectors, chat, eval, admin). Ingestion jobs run in-process when `queue.provider=asyncio`. Vite UI is a separate process. Optional Electron desktop wrapper.

```
backend/app/
  api/v1/              HTTP routers
  application/         use cases (chat, ingest, identity, folders, ACL)
  adapters/providers/  LLM, embedding, vector, FTS, storage, connectors
  adapters/db/         SQLAlchemy + RLS
  config/              YAML cascade (base → env → overlay)
  domain/              ports + @register plugin registry
  core/                JWT, runtime fail-closed, flags
frontend/src/          Chat, Documents, Folders, Sources, Admin, Platform
```

Auth is JWT access + refresh. Every tenant-owned row has `tenant_id`. Chat: authenticate → RLS → retrieve → **ACL filter** → rerank → relevance gate → LLM (SOURCES treated as untrusted) → citations.

See [docs/architecture.md](docs/architecture.md), [docs/SECURITY.md](docs/SECURITY.md), [docs/CONNECTORS.md](docs/CONNECTORS.md), [docs/RAG_PIPELINE.md](docs/RAG_PIPELINE.md), and [docs/adr/](docs/adr/).

## Prerequisites

- Python **3.12+**
- Node.js **20+** (Vite frontend)
- PostgreSQL **16/17** with **pgvector** (and `citext` for local bootstrap)
- **Ollama** optional (local LLM/embeddings). Without it, use extractive + hashing in YAML.
- Redis / MinIO optional (defaults use in-process jobs and local filesystem storage)

macOS local Postgres: `brew install postgresql@17 pgvector`

## Setup

```bash
git clone <repo-url>
cd rag-platform
cp .env.example .env
# Edit .env: JWT_SECRET (32+ chars, not a placeholder), DATABASE_URL,
# PLATFORM_SUPERADMIN_EMAIL, PLATFORM_SUPERADMIN_PASSWORD
```

Python venv + API deps:

```bash
cd backend
python3.12 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
cd ..
```

Database and migrations:

```bash
make bootstrap        # Homebrew Postgres 17, create db, alembic upgrade head
# or, if Postgres is already up:
cd backend && RAG_CONFIG_DIR=../configs .venv/bin/alembic upgrade head
```

Run API and UI from the repo root:

```bash
./scripts/start.sh    # API http://127.0.0.1:8000 + Vite http://127.0.0.1:5173
./scripts/stop.sh
./scripts/restart.sh  # stop then start
```

Same targets: `make start`, `make stop`, `make restart`. PIDs and logs go in `.run/` (gitignored). Sources `.env` if present, uses `backend/.venv`, and sets `RAG_CONFIG_DIR` to `configs/`. Ingestion jobs run in the API process locally (no separate worker). Electron is not started.

Foreground alternative (two terminals): `make api` then `make frontend` (after `cd frontend && npm install`).

**Super Admin env vars** (set in `.env`, never commit): `PLATFORM_SUPERADMIN_EMAIL`, `PLATFORM_SUPERADMIN_PASSWORD`. The user is seeded when the API starts.

Frontend: `cd frontend && npm install` then `make frontend`.

Desktop (optional): `make desktop` (Postgres must already be running).

Docker is optional: `docker compose -f docker/docker-compose.yml up postgres -d` then `make migrate`.

## Login

| Who | Tenant slug | Email | Password |
| --- | --- | --- | --- |
| Super Admin | **leave empty** | platform email from env | platform password from env |
| Tenant user | **required** (company slug) | membership email | password |

Public signup is **off** unless `RAG_ALLOW_PUBLIC_SIGNUP=1`. When it is off, Super Admin creates tenants; Tenant Admins invite users.

Open http://localhost:5173 (or http://127.0.0.1:5173). API: http://127.0.0.1:8000 — health `GET /api/v1/health/live` and `/api/v1/health/ready`.

## Tests

Three layers from the repo root (venv installed; `.env` loaded for tests that hit Postgres):

```bash
make test-unit       # tests/unit
make test-ftest      # tests/security + tests/integration (needs Postgres)
make test-ui         # Playwright smoke against Vite + API
make test            # all pytest
make test-all        # pytest + Playwright
```

Equivalent pytest:

```bash
PYTHONPATH=backend RAG_CONFIG_DIR=configs backend/.venv/bin/pytest tests -q --tb=short
```

UI tests read Super Admin credentials from `PLATFORM_SUPERADMIN_*` in `.env` (never commit them). Install the browser once: `cd frontend && npx playwright install chromium`.

Lint: `make lint`. Frontend build: `cd frontend && npm ci && npm run build`. CI runs pytest and the frontend build on GitHub Actions (Playwright is local / `make test-ui`).

## Security notes

- **Do not commit secrets.** `.env`, OAuth client secrets, JWT signing keys, cloud API keys, and MCP tokens stay local. Commit `.env.example` placeholders only.
- **Production is fail-closed.** `enforce_runtime_safety` refuses to start if the JWT secret is missing/short/placeholder, public signup is on, CORS is `*`, or email is still `console` / missing SMTP/Resend settings.
- **Password reset does not return tokens.** `POST /api/v1/auth/forgot-password` always returns a generic `{ "ok": true }`. The reset URL is sent only by the configured email provider.

## Email

Transactional mail (password reset, tenant welcome, invitations, password-changed) goes through `EmailService` → a registered `EmailProvider`. Business logic never imports SMTP/Resend.

| Provider | When |
| --- | --- |
| `console` | Local/dev/tests. Captures mail in-process. **Forbidden in production.** |
| `smtp` | Self-hosted production (stdlib SMTP). |
| `resend` | HTTPS API (`RESEND_API_KEY`). Pattern for other HTTP vendors. |

Set `EMAIL_PROVIDER` and `PUBLIC_APP_URL` (the UI origin used in links). SMTP needs `SMTP_HOST` (and usually username/password). Do not commit real keys. Tenant Admin **Copy invite** still re-issues a link as an authenticated fallback.
- Connector tokens are encrypted. Admin config endpoints redact secret-shaped keys.
- Empty ACL = deny. Retrieval never sends unauthorized chunks to the LLM.
- Prompt-injection tests treat document text as untrusted data; that is defense-in-depth, not a formal sandbox.

## Dual remotes (GitHub + gitcore)

This project is mirrored on **two private remotes**. Commit **once**, then push **both**.

| Remote | Host | URL |
| --- | --- | --- |
| `github` | github.com | https://github.com/Gowdabt/rag-platform (**private**) |
| `soma` | git.soma.salesforce.com | https://git.soma.salesforce.com/hbt/rag-platform (**private**) |
| `all` | both (push URLs) | `git push all main` |

gitcore.soma.salesforce.com does not allow repositories under a user account (enterprise policy; the only visible org is Salesforce Core). The Salesforce copy lives on **git.soma** under `hbt`, which is the git-soma host.

```bash
git push github main
git push soma main
# or both:
git push all main
```

Both repositories must stay **private**. Do not force-push. Do not commit `.env`.
