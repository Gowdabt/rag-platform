# ADR 009: Config cascade with an unsafe-key denylist

## Status

Accepted

## Context

Tenants need different models and vector stores. Users may want temperature or `top_k`. Request overrides are convenient for evaluation — and dangerous if they can change provider, credentials, or tenant.

## Decision

Merge overlays in order: base YAML → environment YAML → tenant → organization → workspace → user → request.

**User** overlays may only set allowlisted keys (e.g. `llm.temperature`, `retrieval.top_k` within caps).

**Request** overlays are a stricter subset of that allowlist.

**Never** overridable at user/request: providers, credentials/secret refs, `tenant_id`, privacy, storage, residency, ACL, evaluation/debug dumps.

Invalid provider **names** fail at config validation. Registered-but-unimplemented names fail at factory create with `ProviderNotImplementedError`.

## Consequences

- Typed Pydantic models fail fast on shape errors.
- Secrets resolve from `secret://env/…` only at runtime.
- Evaluation can still pin a full pipeline via **workspace/tenant** overlays, not via the chat request body.
