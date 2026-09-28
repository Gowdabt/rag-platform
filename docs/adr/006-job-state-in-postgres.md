# ADR 006: Job state in Postgres, not the broker

## Status

Accepted

## Context

Ingestion needs retries, exponential backoff, cancellation, progress, dead-letter, and idempotency. Broker-native job state is hard to query from the admin UI and easy to lose on Redis flush.

## Decision

`ingestion_jobs` is the system of record. The `JobQueue` (Taskiq + Redis first) is transport.

Workers update job rows as they move through `queued → processing → … → completed` or `dead_letter`.

Idempotency key: `(tenant_id, source_id, source_file_id, content_hash, embedding_profile_id)`.

## Consequences

- Admin dashboards read Postgres, not Redis internals.
- Redis can be wiped without lying about job history (in-flight work is re-enqueued from `queued`/`processing` with care).
- Queue providers remain swappable (RabbitMQ later) because the API does not depend on broker semantics.
