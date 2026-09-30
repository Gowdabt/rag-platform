# QA UI report

Verified with Playwright Chromium (desktop) plus **Pixel 5** viewport (`frontend/e2e/mobile-shell.spec.ts`). Cursor IDE browser MCP had **no tab** this session (`browser_navigate` / `browser_tabs` empty), so live click-through in that browser was not available. Dev servers: `./scripts/restart.sh` → API `127.0.0.1:8000`, Vite `127.0.0.1:5173`.

## Pages exercised

| Route | Desktop | Mobile (~393×851) | Result |
| --- | --- | --- | --- |
| `/` login | Yes | Yes (Pixel 5 login + shell) | Tenant ID, email, password, Forgot password, Super Admin empty slug copy |
| `/forgot-password` → `/reset` | Yes | — | Continue + `token` + `slug`; sign-in after reset |
| `/invite` | Indirect (API + panel URL) | — | Invite URL shape `/invite?token=` |
| `/platform` | SA redirect | SA | Dashboard nav |
| `/platform/tenants` | Create tenant, invite panel, row columns | Nav + heading + Create Tenant | No mashed company+slug |
| `/platform/config`, `/platform/audit` | Nav present | Nav present | Not deep-filled this pass |
| `/` Chat (Tenant Admin) | Conversations heading | Header/nav pattern | Sidebar stacks `flex-col` below `md` |
| `/data` | Create folder “QA Folder” | — | Create gated for no-perm users in UI |
| `/documents` | SA redirect away | — | Upload gated without write |
| `/admin/users` | Invite user visible for Tenant Admin | — | Invite hidden without `users.create` |
| `/admin/roles` | Tenant Admin + permission counts | — | `permission_codes` now populate counts |
| `/sources`, `/admin/ai`, `/admin`, `/admin/audit` | Nav for Tenant Admin | — | Not full OAuth/live LLM |

## Layout / a11y / permission UI

| Finding | Status |
| --- | --- |
| Tailwind `table-row` mashed tenant cells | **Fixed previously**; still forbidden in unit tests; `.data-row` grid |
| Documents used a nested CSS grid instead of `.data-row` | **Fixed** this pass |
| Wide tables on phone | **Mitigated:** `.panel` `overflow-x-auto`; column mins at `max-width: 640px` |
| Header `h-14` overlapped nav on Pixel 5 (clicks intercepted) | **Fixed** AppShell grid |
| Chat delete `opacity-0` until hover | **Fixed** for `< md` |
| Super Admin could render Chat/Documents via URL | **Fixed** PermRoute |
| Invite / Create Role / Upload always shown | **Fixed** permission gates |
| Folder share form vs API | **Fixed** |
| Role permission count 0 | **Fixed** |
| Log out control | `getByRole('button', { name: 'Log out' })` used in E2E |
| Contrast / type | Existing tokens (`on-variant`, `btn-primary`); no new WCAG audit |

## Permission vs hidden buttons

Authorization was **not** trusted to hidden buttons:

- Super Admin tenant document APIs **401/403** (`test_authz_matrix`).
- Viewer/Member **403** on users/platform.
- Custom `users.create` **403** on disable, password-invite `POST /users`, documents, chat, `document:read_all` role create.
- Cross-tenant folder share / user patch **404**.
- Unauthenticated protected routes **401**.

UI gates match those APIs for Invite, role create/edit/delete, folder mutate, document upload.

## Residual UI notes

- Tenant Admin nav has many links; they wrap on a second header row on small screens (intentional after the click-blocker fix).
- Sources OAuth still needs a registered app; not driven with real third-party creds.
- Chat quality depends on Ollama; Playwright only opened the Chat chrome, not a grounded answer.
