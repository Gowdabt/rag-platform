# ADR 008: Authorization before retrieval

## Status

Accepted

## Context

The LLM will use any chunk placed in context. Prompt instructions cannot be trusted to hide unauthorized documents (especially in hospitals).

## Decision

Build an ACL filter from the caller’s tenant, workspaces, user id, teams, and roles **before** dense/sparse search.

Pass the same filter into `VectorStore.search` and `SparseIndex.search`. Drop unauthorized hits in the database/index, not after generation.

The LLM never decides access. Citation validation only allows `chunk_id`s from that already-filtered set.

## Consequences

- Vector payloads must include `tenant_id`, workspace, principals, classification.
- A missing `tenant_id` filter is a hard error (fail closed).
- Security tests (Phase 2+) are mandatory: cross-tenant and restricted-document cases.
