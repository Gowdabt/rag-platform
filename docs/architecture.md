# Architecture (as implemented)

This is the current codebase. ADRs in [adr/](adr/) still apply. A separate scheduler process and default Ollama embeddings from early design notes are **not** how local dev runs today.

## Style

**Modular monolith.** FastAPI API process + optional in-process asyncio jobs (or Taskiq later). React/Vite UI. PostgreSQL 17 + pgvector + FTS is the system of record.

There is **one** plugin system: `@register(kind, name)` in `backend/app/domain/registry.py`. Connectors, LLMs, embeddings, vector stores, sparse indexes, rerankers, storage, queues, chunkers, and parsers all use it.

No LangChain, LlamaIndex, or Haystack.

## Processes (local)

| Process | What actually runs |
| --- | --- |
| API (`make api`) | FastAPI on `:8000`. Auth, documents, connectors, chat, eval, admin. Ingestion jobs run in-process when `queue.provider=asyncio`. |
| UI (`make frontend`) | Vite on `:5173`. |
| Postgres | Homebrew/local Postgres with pgvector. |
| Ollama (optional) | Local LLM. Dev config uses `llm.provider=ollama` / `llama3.2`. Embeddings still `hashing` until you re-ingest. |

There is **no** separate scheduler process yet. Subscription `schedule` is stored; sync is triggered on subscribe and by **Sync now**.

## Layout

```
backend/app/
  api/v1/              HTTP routers
  application/         use cases (chat, ingest, connectors, eval, jobs)
  adapters/providers/  LLM, embedding, vector, sparse, reranker, storage, queue, chunker, parser, connector
  adapters/db/         SQLAlchemy models, RLS
  config/              YAML cascade
  domain/              ports + registry
  core/                JWT, crypto, errors, logging, request id
frontend/src/pages/    Chat, Documents, Sources, Admin
```

## Data plane

Every tenant-owned row has `tenant_id`. API sessions `SET LOCAL app.tenant_id`. RLS is enabled and forced. Application ACL (`_visible`) still filters documents before LLM context.

## Request path (chat)

Authenticate → tenant context + RLS → conversation + query rewrite → sparse/dense retrieve → **ACL filter** → rerank → relevance gate → LLM (system prompt treats SOURCES as untrusted data) → citation validation → persist answer, citations, retrieval event, usage.

Streaming uses the same prepare/ACL path, then `llm.stream()`.

## Source path

Catalog → authenticate (mock OAuth or none) → browse locations → subscribe to a **folder** → sync → ingest with stable `source_file_id` → chunk/embed/index.

See [CONNECTORS.md](CONNECTORS.md), [RAG_PIPELINE.md](RAG_PIPELINE.md), [SECURITY.md](SECURITY.md).
