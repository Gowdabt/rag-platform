# ADR 001: Modular monolith over microservices

## Status

Accepted

## Context

The platform must isolate tenants, run async ingestion, and swap AI providers. That can be done with many networked services or with one codebase and a few processes.

## Decision

Ship a **modular monolith**: one Python package, three processes (`api`, `worker`, `scheduler`). Provider swap is a registry + config change, not a new service.

Tenant isolation is enforced in the data plane (`tenant_id` + RLS), not by deploying one stack per tenant.

## Consequences

- Simpler operations for hospitals and local `docker compose up`.
- Transactions can span metadata, jobs, and ACL in one Postgres.
- Workers scale independently as extra replicas of the same image.
- If a component later needs independent scaling or language, extract behind the existing ports.
