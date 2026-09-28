# Testing

## Layout

| Path | Intent |
| --- | --- |
| `tests/unit/` | Registry, crypto, fusion, chunk/parse, connectors, citations, eval scoring, schema strings |
| `tests/security/` | ACL visibility, prompt-injection contract, tenant isolation |
| `tests/integration/` | HTTP connector lifecycle against real Postgres |
| `tests/e2e/` | Placeholder package (no browser suite yet) |
| `tests/evaluation/` | Placeholder package (scoring lives under unit + `application/eval.py`) |

## Run

From repo root, with `.env` loaded so `DATABASE_URL` and `JWT_SECRET` exist:

```bash
set -a && source .env && set +a
PYTHONPATH=backend RAG_CONFIG_DIR=configs backend/.venv/bin/pytest tests -q
```

Or `make test` (same pytest invocation; still needs env if integration tests hit Postgres).

Integration tests **must** use `with TestClient(app) as client:` so FastAPI lifespan initializes the engine.

Lint: `make lint` → `ruff check backend/app tests`.

## What is covered now

- Mock connector registry, browse, auth_expired
- Rename/move identity in `sync_diff` (stable file id)
- Connector HTTP: signup → mock OAuth → browse → subscribe/sync → second sync skips
- Citation invented-id stripping
- ACL `_visible` for other users
- Prompt system-text contract
- Existing auth, fusion, extractive, hashing embed, lexical rerank tests

## Gaps (honest)

- No Playwright/Cypress e2e
- No load tests
- Streaming is covered only indirectly (citation helpers + shared `_prepare`)
- Cross-tenant HTTP retrieval tests exist in tenant isolation module; keep extending them when adding APIs
- Member role `source:manage` is code-level; old DB role rows may lack the permission until re-seeded
