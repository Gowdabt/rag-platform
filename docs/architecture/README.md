# Architecture documentation

This directory describes the **implemented** RAG platform as of the working tree inspected for this write-up. It is not a target architecture.

Older documents under `docs/` (especially `docs/HLD.md` and `docs/schema.md`) disagree with the code in places. Where they disagree, these files follow the code and call out the conflict.

| Document | What it answers |
| --- | --- |
| [HLD.md](HLD.md) | Context, components, deployment shape, scalability, reliability, observability, technology inventory, repository map |
| [LLD.md](LLD.md) | Modules, classes, business rules, state machines, async, config, errors, cache, locks, failure behavior |
| [API.md](API.md) | HTTP routes, authn/authz, validation, pagination, error body |
| [DATABASE.md](DATABASE.md) | Tables, keys, indexes, RLS, migrations, ER diagrams |
| [SEQUENCES.md](SEQUENCES.md) | Sequence diagrams and the sequence index |
| [FLOWS.md](FLOWS.md) | Business and data-flow diagrams |
| [DEPLOYMENT.md](DEPLOYMENT.md) | Local process, Docker Compose, CI, config hierarchy, secrets |
| [SECURITY.md](SECURITY.md) | Authentication, authorization, tenant isolation, document ACL, headers |
| [DECISIONS.md](DECISIONS.md) | Decisions visible in code or ADRs, including where an ADR and the code diverge |
| [IMPROVEMENTS.md](IMPROVEMENTS.md) | Recommended changes only. Not current behavior |

## How to read a claim

- **Existing.** Behavior traced in source, migrations, or tests.
- **Inferred.** A reasonable reading when the code does not state intent. Marked inline.
- **Missing / unclear.** Called out as such. Not filled in.
- **Recommended.** Only in [IMPROVEMENTS.md](IMPROVEMENTS.md).

If a design choice has no statement in code or repository docs, the text is exactly: "Rationale not evident from repository."

## Appendix

### Diagram index

| Diagram | File |
| --- | --- |
| System context | [HLD.md](HLD.md) |
| High-level architecture | [HLD.md](HLD.md) |
| Component diagram | [HLD.md](HLD.md) |
| Deployment (local and Compose) | [DEPLOYMENT.md](DEPLOYMENT.md) |
| Signup/login, upload, chat, sync, ACL data flows | [FLOWS.md](FLOWS.md) |
| Sequence diagram index | [SEQUENCES.md](SEQUENCES.md) |
| Class diagrams (identity, ingest, chat, providers) | [LLD.md](LLD.md) |
| ER diagrams | [DATABASE.md](DATABASE.md) |
| State machines (version, job, sync, source) | [LLD.md](LLD.md) |
| Authn and authz flows | [SECURITY.md](SECURITY.md) and [SEQUENCES.md](SEQUENCES.md) |

### API index

All routes are under `/api/v1`. The full table is [API.md](API.md). Routers are registered in `backend/app/main.py` `create_app()`.

### Database index

Alembic chain `001` → `009` under `backend/alembic/versions/`. Table catalog is [DATABASE.md](DATABASE.md). ORM models are `backend/app/adapters/db/models.py`.

### Important configuration

Cascade, environment variables, and secret refs: [DEPLOYMENT.md](DEPLOYMENT.md). Model: `backend/app/config/models.py`. Files: `configs/base.yaml`, `configs/development.yaml`, `configs/staging.yaml`, `configs/production.yaml`.

### Glossary

| Term | Meaning in this repository |
| --- | --- |
| Tenant | Row in `tenants`. Isolation boundary for documents, roles, and RLS. |
| Tenant Admin | System role name in `SYSTEM_ROLES` (`backend/app/application/rbac.py`). Legacy name `Admin` is treated as the same role by `TENANT_ADMIN_NAMES`. |
| Member / Viewer | Non-system default roles seeded with each tenant. |
| Super admin | `users.is_super_admin`. Platform operator. Not a tenant role. `RequestContext.has()` grants only `platform.*` permissions. |
| Document ACL | JSON on `documents.acl`: owner, `visibility` (`private` or `tenant`), allow/deny lists for users, groups (team names), and roles. |
| `document:read_all` | Permission that bypasses document ACL. Still in the permission catalog. Removed from the Tenant Admin role seed and, by migration `009`, from existing Tenant Admin / Admin role rows. |
| Content address | SHA-256 of file bytes. Shared `content_objects` row per `(tenant_id, content_hash)`. |
| Pipeline fingerprint | Hash of parser, chunker, and embedding settings (`pipeline_fingerprint` in `backend/app/application/content_address.py`). Same bytes and fingerprint share one indexed canonical version. |
| Logical chunk | Retrieval joins chunks stored on a canonical version onto every active document version that derives from it (`LOGICAL_CHUNK_FROM`). |
| Ingestion job | Row in `ingestion_jobs`. Status is the job record. There is no separate message broker in the running code. |
| Authz epoch | `tenants.authz_epoch` + `users.authz_epoch`. Included in process-local chat cache keys. |
| Overlay | Tenant JSON in `config_overlays`, merged onto YAML by `get_tenant_settings`. Denylist in `backend/app/config/merge.py`. |

## Open questions

Collected in [HLD.md](HLD.md#open-questions).
