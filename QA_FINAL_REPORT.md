# QA final report

Lead QA + bug-fix pass on rag-platform (FastAPI + React/Vite + Postgres/pgvector). No LangChain rewrite. No git commit (not requested). No `.env`/secrets committed.

## What was tested

- **Inventory:** All `/api/v1` routers, React routes in `App.tsx`, nav in `navLinksFor`, RBAC (`Tenant Admin` / `Member` / `Viewer` / custom), Super Admin flag, JWT+RLS, empty ACL deny, hybrid FTS+pgvector (code + existing tests).
- **Baseline then full:** unit, security/integration, ruff, `tsc -b && vite build`, Playwright.
- **AuthZ on the API** (not only hidden buttons): unauthenticated 401; Super Admin denied tenant document/chat/users/roles; Super Admin `me.permissions == []` and no `document:read_all`; Tenant Admin vs Member vs Viewer vs custom `users.create`; IDOR 404 across tenants; folder share UI payload; cannot wipe Tenant Admin role; cannot grant unowned perms.
- **UI:** Playwright desktop + Pixel 5; Super Admin tenant create/invite; forgot-password Continue+slug; Tenant Admin Users/Roles/Data/Chat; Super Admin redirected off `/documents` and `/data`.

## What was broken (root causes) and fixed

See `QA_BUG_REPORT.md`. Highest impact:

1. **Superset permission aliases** — `users.create` counted as `user:manage`.
2. **Super Admin PermRoute** — tenant pages by URL.
3. **Folder share JSON** — `type`/`permissions` vs `subject_type`/`actions`.
4. **Roles UI `permissions` vs API `permission_codes`** — silent wipe of Member/Viewer.
5. **PUT system role permissions** and **grant any catalog code**.
6. **Mobile header** intercepting nav clicks.

## Tests added

| File | What |
| --- | --- |
| `tests/unit/test_permissions.py` | Equivalents vs one-way grants; SA never `document:read_all` |
| `tests/security/test_authz_matrix.py` | Unauth 401; SA tenant deny; Viewer/Member; custom inviter; system role lock; UI share payload; user IDOR |
| `tests/unit/test_frontend_security.py` | PermRoute, share/invite/role field contracts |
| `frontend/e2e/tenant-admin.spec.ts` | SA no tenant routes; Tenant Admin Users/Roles/Data/Chat |
| `frontend/e2e/mobile-shell.spec.ts` | Pixel 5 nav + Tenants |
| `frontend/playwright.config.ts` | `workers: 1` so live auth 10/min is not a false fail |

Existing suites kept; **no tests weakened or skipped**. Leftover `test_local_fs_default_roots_include_project_data_sources` **passes**.

## UI / permission issues

Fixed: SA tenant URL bypass, share/roles/invite contracts, action gating, mashed document rows, mobile nav, chat delete on touch.

Residual: live OAuth not cred-tested; streaming not E2E; CI still pytest+build without Playwright (`docs/TESTING.md`).

## Remaining issues

- Default live **auth rate limit 10/min** — real control; E2E must stay serial against one API.
- `make` failed here (Xcode license **69**); commands below use venv/`npm` directly.
- Cursor browser MCP: no tab; Playwright used instead.
- Connector OAuth: mocks in pytest only if `RAG_CONNECTOR_MOCKS=1`.

## Exact commands and counts

`make` was unusable on this machine (`xcodebuild -license`). Equivalent:

```bash
cd /Users/hbt/HarshithGowda/Apps/rag-platform
set -a && . ./.env && set +a
PYTHONPATH=backend RAG_CONFIG_DIR=configs backend/.venv/bin/pytest tests/unit -q --tb=short -m unit
PYTHONPATH=backend RAG_CONFIG_DIR=configs backend/.venv/bin/pytest tests/security tests/integration -q --tb=short
PYTHONPATH=backend RAG_CONFIG_DIR=configs backend/.venv/bin/pytest tests -q --tb=short
backend/.venv/bin/ruff check backend/app tests
cd frontend && npm run test:ui
cd frontend && npm run build
```

Live E2E used `./scripts/restart.sh` (API **127.0.0.1:8000**, UI **127.0.0.1:5173**).

### Final counts

| Suite | Result |
| --- | --- |
| `pytest tests/unit -m unit` | **94 passed** (was 88; +5 permissions +1 frontend contract) |
| `pytest tests/security tests/integration` | **73 passed** (was 67; +6 authz matrix) |
| `pytest tests` | **167 passed**, 2 warnings |
| Playwright `npm run test:ui` | **5 passed** (1 worker, ~4.4s) |
| `ruff check backend/app tests` | **All checks passed** |
| `frontend` `tsc -b && vite build` | **success** (112 modules) |

Warnings only: Starlette TestClient deprecation; JWT HMAC key length in crypto unit test (pre-existing).
