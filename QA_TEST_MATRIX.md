# QA test matrix

Source of truth: FastAPI + React/Vite as of this QA pass. Role **names** in tenants are data (`Tenant Admin`, `Member`, `Viewer`, custom). Platform elevation is `users.is_super_admin` (not a tenant role named `SUPER_ADMIN`).

## Actors

| Actor | How it exists | Default permissions (summary) |
| --- | --- | --- |
| Unauthenticated | No JWT | Public auth + health only |
| Super Admin | `is_super_admin`; empty Tenant ID on login | Platform only. JWT has no `tid`. `permissions=[]`. **Never** `document:read_all` |
| Tenant Admin | System role `Tenant Admin` (`is_system=True`); alias name `Admin` | `ALL_PERMISSIONS` including `document:read_all` and `source:admin` |
| Member | Seeded non-system role | Read/write own ACL docs, chat, sources, folder create/share. No `document:read_all`, no user/role admin |
| Viewer | Seeded non-system role | `document:read` / `documents.view`, chat, `config:read`. No write, no user admin |
| Custom tenant role | `POST /api/v1/roles` (`is_system=False`) | Caller-chosen codes; cannot grant codes the actor does not have; cannot name `Tenant Admin` / `Admin` |

## Public / auth surfaces

| ID | Surface | Method / route | Actors | Expected |
| --- | --- | --- | --- | --- |
| A1 | Live health | `GET /api/v1/health/live` | Unauth | 200 |
| A2 | Features | `GET /api/v1/auth/features` | Unauth | 200 `{public_signup}` |
| A3 | Signup | `POST /api/v1/auth/signup` | Unauth | 200 if `RAG_ALLOW_PUBLIC_SIGNUP`; else 403 |
| A4 | Tenant login | `POST /api/v1/auth/login` | Unauth | slug + email + password; 200 session |
| A5 | Super Admin login | `POST /api/v1/auth/login` | Unauth | empty slug; 200 `sa`; `tenant_id` null |
| A6 | Accept invite | `POST /api/v1/auth/accept-invite` UI `/invite` | Unauth | set password ≥10; 200 session |
| A7 | Forgot / reset | `POST /api/v1/auth/forgot-password` `/forgot-password`; `POST /api/v1/auth/reset-password` `/reset` | Unauth | slug required; mixed-case slug; invited user → active |
| A8 | Me | `GET /api/v1/auth/me` | JWT | 200; SA empty perms |
| A9 | Refresh / logout | `POST /api/v1/auth/refresh` `logout` | tokens | 200 / revoke |
| A10 | Switch tenant | `POST /api/v1/auth/switch-tenant` | JWT | 403 for Super Admin |
| A11 | Protected APIs | tenant + platform | Unauth | **401** |

## Super Admin (platform)

| ID | Surface | Method / route | Expected |
| --- | --- | --- | --- |
| S1 | UI home | `/` | Redirect `/platform` |
| S2 | Nav | Dashboard, Tenants, Platform Configuration, Audit Logs | No Chat/Documents/Data |
| S3 | Tenants list/create/get/patch | `/api/v1/platform/tenants` `GET/POST` `{id}` `GET/PATCH` UI `/platform/tenants` | 200; `company_name` alias; slugify; optional temp password; invite panel |
| S4 | AI catalog | `GET /api/v1/platform/ai-catalog` UI `/platform/config` | 200 |
| S5 | Platform audit | `GET /api/v1/platform/audit-logs` UI `/platform/audit` | 200; no document contents |
| S6 | Tenant APIs | documents, folders, users, roles, chat, config, ai-config, audit | **401 or 403**; not `document:read_all` |
| S7 | Direct UI | `/documents` `/data` | Redirect `/platform` (not PermRoute bypass) |

## Tenant Admin

| ID | Surface | Method / route | Expected |
| --- | --- | --- | --- |
| T1 | Chat | `POST /api/v1/chat` `GET /conversations` UI `/` | 200; ACL retrieval |
| T2 | Data / folders | `/api/v1/folders` CRUD + share UI `/data` | 200; share `subject_type`+`actions` |
| T3 | Documents | `GET/POST /api/v1/documents` ACL UI `/documents` | 200; `document:read_all` bypasses empty ACL |
| T4 | Sources | `/api/v1/connectors*` UI `/sources` | `source:manage` / `source:admin` |
| T5 | Users | `GET/POST /users` invitations PATCH UI `/admin/users` | invite, disable |
| T6 | Roles | `/api/v1/roles` `/permissions` UI `/admin/roles` | list includes `permission_codes` **and** `permissions`; cannot wipe system role |
| T7 | AI config | `/api/v1/tenant/ai-config` UI `/admin/ai` | 200 |
| T8 | Audit / settings | `/audit-logs` `/config` `/admin` | 200 |
| T9 | Platform tenants | `POST /api/v1/platform/tenants` | **403** |

## Member / Viewer / custom

| ID | Surface | Member | Viewer | Custom `users.create` only |
| --- | --- | --- | --- | --- |
| M1 | Chat / documents list | 200 (ACL) | 200 (ACL) | 403 |
| M2 | Create folder | 200 | 403 | 403 |
| M3 | Upload document | 200 (own ACL) | 403 | 403 |
| M4 | List/invite users | 403 | 403 | invitations 200; `POST /users` (password invite) 403 |
| M5 | Disable users | 403 | 403 | 403 |
| M6 | Create role / grant `document:read_all` | 403 | 403 | 403 |
| M7 | Platform tenants | 403 | 403 | 403 |
| M8 | Unshared owner doc | 404 / omitted from list | same | n/a |
| M9 | Empty document ACL | deny unless `document:read_all` | deny | n/a |

## Isolation / IDOR

| ID | Case | Expected |
| --- | --- | --- |
| I1 | Tenant B GET Tenant A document/folder/conversation/connector | 404 (not 403-with-existence) |
| I2 | Tenant B PATCH Tenant A user / share folder | 404 |
| I3 | Tenant B PUT Tenant A role | 404 |
| I4 | Tenant B GET AI config | 200 but **not** Tenant A overlay |
| I5 | Chat with Tenant A `version_id` as Tenant B | no secret in answer |
| I6 | Intra-tenant Member vs unshared owner doc | 404 / not in list / chat miss |
| I7 | Share then revoke document ACL | access then 404 |
| I8 | RLS | `tenant_id = app.tenant_id`; FORCE RLS |

## UI contracts (desktop + ~Pixel 5)

| ID | Page | Checks |
| --- | --- | --- |
| U1 | Login | Tenant ID empty = Super Admin; Forgot password; no mashed cells |
| U2 | Tenants | `data-row` / `cols-tenant`; invite panel `invite-url` `/invite?token=` |
| U3 | Roles | permission count from `permission_codes`; Create gated |
| U4 | Users | Invite gated; `role_names` on API |
| U5 | Data | Create/share gated; share uses `subject_type`+`actions` |
| U6 | Documents | Upload gated; `data-row` |
| U7 | Chat | Conversations; delete visible on touch |
| U8 | Header | Nav clickable on mobile (not covered by fixed `h-14`) |

## Automation mapping

| Layer | Command | Covers |
| --- | --- | --- |
| Unit | `pytest tests/unit -m unit` | crypto, fusion, permissions expand, frontend source contracts, local_fs roots, platform schema |
| Ftest | `pytest tests/security tests/integration` | ACL, IDOR, SaaS, authz matrix, connectors (mocks if `RAG_CONNECTOR_MOCKS`) |
| UI | `cd frontend && npm run test:ui` | Super Admin tenant, forgot-password, tenant admin smoke, SA no tenant routes, Pixel 5 shell |
