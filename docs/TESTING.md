# Testing

Three layers, one command surface from the repo root. Pytest is unchanged for unit and functional tests; Playwright covers the Super Admin UI.

| Command | What it runs |
| --- | --- |
| `make test-unit` | Fast pytest under `tests/unit` (`-m unit`) |
| `make test-ftest` | FastAPI + Postgres tests in `tests/security` and `tests/integration` (`-m ftest`) |
| `make test-ui` | Playwright smoke (`frontend` → `tests/ui`) |
| `make test` | All pytest (unit + ftest). Does not start a browser. |
| `make test-all` | `make test` then `make test-ui` |

## Layout

| Path | Intent | Marker |
| --- | --- | --- |
| `tests/unit/` | Registry, crypto, fusion, schema, frontend source contracts | `unit` |
| `tests/security/` | ACL, tenant isolation, SaaS platform HTTP | `ftest` / `integration` |
| `tests/integration/` | HTTP connector lifecycle against real Postgres | `ftest` / `integration` |
| `tests/ui/` | Pointer to Playwright specs (`frontend/e2e`, so Node can resolve `@playwright/test`) | (Playwright, not pytest) |
| `tests/e2e/` | Reserved; UI specs live in `tests/ui/` |
| `tests/evaluation/` | Placeholder (scoring lives under unit + `application/eval.py`) |

Markers are applied automatically from the path in `tests/conftest.py`.

## Run

From repo root, with `.env` loaded so `DATABASE_URL` and `JWT_SECRET` exist:

```bash
set -a && source .env && set +a
make test-unit
make test-ftest
make test            # full pytest
```

UI smoke needs the API + Vite (or Playwright will start them if the ports are free):

```bash
./scripts/start.sh   # optional if already running
cd frontend && npx playwright install chromium   # once
make test-ui
```

Playwright reads `PLATFORM_SUPERADMIN_EMAIL` / `PLATFORM_SUPERADMIN_PASSWORD` from the environment (and from repo-root `.env`). It never hardcodes those values. Skip UI if those vars are unset.

Integration tests **must** use `with TestClient(app) as client:` so FastAPI lifespan initializes the engine.

Lint: `make lint` → `ruff check backend/app tests`.

## What is covered now

- Mock connector registry, browse, auth_expired
- Rename/move identity in `sync_diff` (stable file id)
- Connector HTTP: signup → mock OAuth → browse → subscribe/sync → second sync skips
- Citation invented-id stripping
- ACL `_visible` for other users
- Prompt system-text contract
- Platform tenant create aliases (`company_name` / slugify), optional temp password, invite payload
- Playwright: Super Admin empty-tenant login, create tenant, column layout, invite URL
- Existing auth, fusion, extractive, hashing embed, lexical rerank tests

## Gaps (honest)

- GitHub Actions CI still runs pytest + frontend build, not Playwright
- No load tests
- Streaming is covered only indirectly (citation helpers + shared `_prepare`)
- Cross-tenant HTTP retrieval tests exist in tenant isolation module; keep extending them when adding APIs
- Member role `source:manage` is code-level; old DB role rows may lack the permission until re-seeded
