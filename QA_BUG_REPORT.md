# QA bug report

Bugs found in this pass, plus historically already-fixed items that remain covered by tests. Severity: **P0** security/data isolation, **P1** broken primary UX, **P2** permission UI / layout.

No LangChain rewrite. No `.env` or secrets committed.

---

## Fixed this pass

### BUG-2026-09-29-01 — Permission aliases granted supersets (P0)

- **Where:** `backend/app/core/permissions.py` `permissions_include`
- **Repro:** Custom role with only `users.create` → `PATCH /api/v1/users/{id}` `{status: disabled}` previously succeeded because `user:manage` aliased **to** `users.create` **and** checking `user:manage` treated any subset as a match. Same class: `ai.configuration.update` implied `config:write`; `folders.create` did **not** imply `document:write` (one-way in the old map), but `users.view` implied `user:manage`.
- **Root cause:** Bidirectional `PERMISSION_ALIASES` mixed **equivalents** (`document:read` ↔ `documents.view`) with **supersets** (`user:manage` ⊃ `users.create`).
- **Fix:** `PERMISSION_EQUIVALENTS` (bidirectional) + `PERMISSION_GRANTS` (one-way). `expand_permissions()` / `permissions_include()`. Super Admin `RequestContext.has` unchanged (platform codes only).
- **Tests:** `tests/unit/test_permissions.py`, `tests/security/test_authz_matrix.py::test_custom_users_create_cannot_disable_or_grant_read_all`

### BUG-2026-09-29-02 — Super Admin UI could open tenant pages (P0)

- **Where:** `frontend/src/App.tsx` `PermRoute`
- **Repro:** Super Admin signed in → navigate `/documents` or `/data`. Nav hid links, but `isSuperAdmin(user) \|\| hasAnyPermission(...)` still rendered tenant pages.
- **Root cause:** Super Admin treated as “allow all PermRoutes”. Product: Super Admin is platform-only and must not get tenant `document:read_all` or tenant document UX.
- **Fix:** Super Admin on `PermRoute` redirects to `/platform`. API already 401/403 without `tid` / tenant perms.
- **Tests:** `tests/unit/test_frontend_security.py::test_frontend_authz_contracts_match_api`; Playwright `tenant-admin.spec.ts` “super admin cannot open tenant document routes”; `test_authz_matrix.py::test_super_admin_is_denied_tenant_document_apis`

### BUG-2026-09-29-03 — Folder share from UI 422 (P1)

- **Where:** `frontend/src/api/client.ts` `foldersApi.share`; `FoldersPage` `onShare`; `FolderShareIn`
- **Repro:** Data → folder → Add access. UI sent `{type, permissions: {view: true, ...}}`. API required `{subject_type, actions: [...]}`.
- **Root cause:** Client/API contract drift.
- **Fix:** Client sends `subject_type` + `actions`. API accepts aliases `type` and `permissions` (object or list). Grant list UI reads `subject_type` / `actions`.
- **Tests:** `test_authz_matrix.py::test_folder_share_accepts_ui_payload_and_cross_tenant_idor`; frontend source contract

### BUG-2026-09-29-04 — Roles UI ignored `permission_codes` (P1)

- **Where:** `RolesPage.rolePermissionCodes`; `IdentityService` role JSON
- **Repro:** Open Roles. Counts showed 0. Edit Member + Save sent `permissions: []` and **wiped** the seeded Member/Viewer bundles (`is_system=False`).
- **Root cause:** API returned `permission_codes`; UI read `permissions` only.
- **Fix:** UI reads `permission_codes \|\| permissions`. API emits **both** keys. Saving empty codes on **Tenant Admin** is forbidden (BUG-05).
- **Tests:** authz matrix create-role asserts both keys; Playwright tenant admin “N permissions”; frontend contract

### BUG-2026-09-29-05 — System Tenant Admin permissions could be emptied (P0)

- **Where:** `IdentityService.update_role`
- **Repro:** `PUT /api/v1/roles/{tenant_admin_id}` `{permissions: []}` as Tenant Admin → 200, ACL bypass gone.
- **Root cause:** Rename blocked for system roles; permission replace was not.
- **Fix:** `ForbiddenError` if `is_system` or tenant-admin name when `permission_codes` is sent.
- **Tests:** `test_cannot_wipe_tenant_admin_role_or_grant_unowned_permission`

### BUG-2026-09-29-06 — Roles.update could grant `document:read_all` without having it (P0)

- **Where:** `IdentityService._set_role_permissions`
- **Repro:** Custom role with `roles.update` + `documents.view` → PUT own role including `document:read_all`.
- **Root cause:** Any known catalog code was attachable.
- **Fix:** Each code must pass `ctx.has(code)` (Tenant Admin has `ALL_PERMISSIONS`).
- **Tests:** same as BUG-05

### BUG-2026-09-29-07 — Invite API ignored UI `roles` field (P2)

- **Where:** `InvitationIn`; `invitationsApi.create`; `UsersPage`
- **Repro:** UI sent `roles: string[]`; model only had `role_names`. `role_ids` still worked if UUIDs were selected.
- **Fix:** Alias `roles` → `role_names`; client sends `role_names`.
- **Tests:** authz matrix invitation with `"roles": ["Member"]`; frontend contract

### BUG-2026-09-29-08 — Frontend `hasAnyPermission` was exact-string only (P1)

- **Where:** `frontend/src/auth/access.ts`
- **Repro:** Custom role with only `documents.view` → Documents nav hidden while `GET /documents` (backend equivalent) would 200.
- **Fix:** Same equivalent/grant expansion as backend. Super Admin `hasPermission` only `platform.*`.
- **Tests:** frontend contract; nav used in Playwright tenant admin

### BUG-2026-09-29-09 — Mutating buttons shown without permission (P2)

- **Where:** Users / Roles / Folders / Documents pages
- **Repro:** `users.view` without `users.create` still saw Invite; Viewer-like surfaces showed Create/Upload.
- **Fix:** Gate Invite, Disable, Create Role, folder create/share/rename/delete, document upload via `hasAnyPermission` + owner for folders.
- **Tests:** source contracts; Playwright Tenant Admin still sees Invite

### BUG-2026-09-29-10 — Super Admin `GET /users` and `GET /roles` returned 200 [] (P1)

- **Where:** `list_users` / `list_roles`
- **Repro:** SA JWT, no `tid` → empty lists (looked like “no users”) instead of tenant required.
- **Fix:** `ctx.require_tenant()` → **401**.
- **Tests:** `test_super_admin_is_denied_tenant_document_apis`

### BUG-2026-09-29-11 — Mobile header swallowed nav clicks (P1)

- **Where:** `AppShell` `h-14` flex row
- **Repro:** Pixel 5 Playwright: Tenants link visible but `header` inner div intercepted pointer events.
- **Fix:** CSS grid: logo | user on first row, full-width nav second row; `sm:flex` single row desktop.
- **Tests:** `frontend/e2e/mobile-shell.spec.ts`

### BUG-2026-09-29-12 — Chat delete only on hover (P2)

- **Where:** `ChatPage` `opacity-0 group-hover:opacity-100`
- **Fix:** Always visible on small screens; hover-reveal from `md:`.
- **Tests:** layout in Playwright chat visit (tenant admin spec)

---

## Historical (already in tree before this pass; still covered)

| Item | Notes |
| --- | --- |
| `company_name` alias on create tenant | `PlatformTenantIn`; `test_platform_tenant_schema.py` |
| Slugify tenant ID | `slugify` + mixed-case login |
| Tailwind `table-row` mashed cells | `.data-row` grid; unit forbids `table-row` in TSX |
| Invite panel columns + URL | `tenant-invite-panel`; Playwright super-admin-tenant |
| Forgot password Continue + slug | `/reset?token=&slug=`; Playwright forgot-password |
| Invited user reset → active | `test_password_reset.py` |
| Empty ACL deny | `test_acl_before_llm.py`, tenant isolation |
| SA no `document:read_all` in `RequestContext.has` | `context.py` (pre-existing; HTTP coverage added this pass) |

---

## Leftover unit called out in the prompt

`tests/unit/test_real_connectors.py::test_local_fs_default_roots_include_project_data_sources` — **passes**. Product: default roots are project `data/sources`, not `~/Documents`/`~/Desktop` unless `isolation="host"`. Treated as a real contract, not skipped.

---

## Open / residual (not product bugs we chose to ship around)

| Item | Severity | Notes |
| --- | --- | --- |
| Live auth rate limit 10/min (`RAG_AUTH_RATE_LIMIT` default) | P2 ops | Parallel Playwright workers 429’d login. **Did not raise the product limit.** Playwright `workers: 1`. Pytest still sets 200/min via conftest. |
| GitHub Actions does not run Playwright | P2 | Documented in `docs/TESTING.md` |
| Real OAuth (Drive/MS/Dropbox) | n/a | No production third-party credentials. HTTP tests use mocks when `RAG_CONNECTOR_MOCKS=1` |
| Chat streaming | P3 | Covered indirectly (`_prepare`, citations); no dedicated stream E2E |
| `GET /roles` any authenticated tenant user | P3 | Needed for folder share-by-role; not a hidden-button-only gate |
| Viewer seed includes `config:read` | by design | Viewer can `GET /config`; not changed |
| `make` on this Mac | env | Xcode license (exit 69); used venv `pytest` / `ruff` / `npm` |
| Cursor IDE browser MCP | env | No tab available this session; UI verified via Playwright |
