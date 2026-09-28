# Security (as implemented)

## Authentication

JWT access tokens (Bearer) + refresh tokens. Signup creates tenant, org, workspace, Admin membership.

## Authorization chain

1. JWT → `RequestContext` (tenant, user, workspace, permissions, teams).
2. PostgreSQL RLS: `SET LOCAL app.tenant_id` on tenant-owned tables, policy `FORCE ROW LEVEL SECURITY`.
3. Route permissions (`require_permission`).
4. Document ACL `_visible` (allowed users/groups, `document:read`).
5. Chat: `_authorized_hits` **before** rerank and LLM, including streaming.

The model is not an authorization layer.

## Connectors / OAuth

- Tokens encrypted (`LocalTokenCipher`). Not plaintext in `connector_credentials`.
- OAuth `state` is unique, stored, expiry-checked.
- Catalog/browse/sync require a logged-in tenant context.
- Mock OAuth never talks to Google/Microsoft.

## Secrets

- `.env` / secret refs in YAML. Admin `GET /config` redacts keys matching secret/password/api_key and secret-ref values.
- Do not log access tokens, refresh tokens, client secrets, or authorization codes (adapters must not print them).

## Prompt injection

Documents are data. The chat system prompt instructs the model to ignore role-change / secret-exfil instructions inside SOURCES. Tests in `tests/security/test_prompt_injection.py` lock the contract. This is defense-in-depth, not a guarantee against every model.

## What is not claimed

- KMS/Vault/Key Vault backends
- Full source-level ACL beyond copying subscription ACL onto new documents
- Network isolation between tenants beyond RLS + app filters
