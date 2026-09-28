# ADR 011: Content-addressed files, shared derived indexes

## Status

Accepted

## Context

A document is a **named file** (path, ACL, source id). Production corpora often contain the same bytes under many names (`policy.md`, `policy copy.md`, Drive duplicates). Storing parse/chunk/embedding per filename multiplies object storage, `document_chunks`, and vectors with no retrieval benefit.

Dedup must not collapse **logical** identity: citations still name the file the user has, ACLs stay per file, and a content change on one copy is a new version of that copy only.

Hashes are **tenant-scoped**. Cross-tenant CAS would leak existence of a blob via hash.

## Decision

Separate three layers:

1. **Logical document** — `documents` + `document_versions`. Name, source_file_id, ACL, version history.
2. **Content object** — `content_objects` keyed by `(tenant_id, sha256(bytes))`. One blob in object storage (`{tenant}/cas/{hash}`).
3. **Derived index** — chunks and embeddings owned by the **first completed version** of that hash + parse/chunk/embed fingerprint. Later files set `derived_from_version_id` and do not parse, chunk, or embed again.

`pipeline_fingerprint` is `sha256(parser|chunker|size|overlap|embedder|model|dims)`. A chunker or embedding model change is a new derived index, not a silent reuse of old vectors.

Retrieval joins canonical chunks onto every **active** logical version that is the canonical row or derives from it. Hits carry the logical `document_id` so citations and ACL stay correct.

Same **source_file_id** + same hash still means “unchanged file” (no new version). Same hash + **different** file means a new logical document pointing at shared content.

## Consequences

- Storage and embed cost grow with distinct byte strings × pipeline fingerprint, not with filename copies.
- Two files with the same bytes remain two documents in the UI and can both be cited.
- Tenant isolation is preserved; we never share blobs across tenants.
- Garbage-collect a `content_object` when `ref_count` reaches 0 (future job). Versions stay immutable.
