# ADR 002: No LangChain, LlamaIndex, or Haystack

## Status

Accepted

## Context

Orchestration frameworks give prompt templates and retriever classes. This platform needs tenant isolation, document versions, ACL-before-retrieval, config cascade, and citations that are validated against retrieved chunks.

## Decision

**Do not depend on LangChain, LlamaIndex, or Haystack** — not as the pipeline, and not as a hidden adapter.

Own parse → chunk → embed → retrieve → fuse → rerank → generate → cite.

Talk to vendors through first-party SDKs (`ollama`, `openai`, `anthropic`, `qdrant-client`, …) behind `app.domain.ports`.

## Consequences

- More code in-tree for retries, batching, and streaming.
- No framework lock-in when adding a provider.
- Authorization stays in our retrieval layer instead of inside a vendor retriever.
