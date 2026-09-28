# ADR 010: Entry-point plugin registry

## Status

Accepted

## Context

Adding an LLM, vector store, parser, or connector must not require rewriting core pipelines.

## Decision

A process-wide `ProviderRegistry` maps `(kind, name) → factory`.

In-tree providers use `@register("llm", "ollama")`. Out-of-tree packages use the `rag_platform.providers` setuptools entry point group.

`ProviderFactory.create(kind, name, config, ctx)` instantiates from the effective tenant/workspace config. No global singleton that ignores tenant.

Unknown kind/name: `UnknownProviderError`. Known name, no factory yet: `ProviderNotImplementedError` (not a silent stub that pretends to work).

## Consequences

- Core depends on ABCs in `app.domain.ports`.
- Phase 1 registers **zero** fake RAG providers.
- Phase 3 registers real Ollama, OpenAI-compatible, pgvector, Qdrant, Taskiq, S3, filesystem, and builtin parsers/chunkers.
