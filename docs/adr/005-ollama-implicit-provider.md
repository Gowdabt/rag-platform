# ADR 005: Ollama is the implicit AI provider

## Status

Accepted

## Context

Healthcare and enterprise tenants must not send documents to external APIs unless they choose to. Developers should run the happy path without cloud keys.

## Decision

`configs/development.yaml` (and platform defaults) use:

- `llm.provider: ollama`
- `embedding.provider: ollama`

Selecting OpenAI, Azure, Anthropic, Gemini, Voyage, Cohere, etc. requires an explicit overlay and secret refs. The application must not “fall back” to a cloud provider if Ollama is down.

## Consequences

- Compose includes Ollama; README documents which models to pull (`nomic-embed-text`, `llama3.1` or equivalent).
- External providers are registered plugins, not implicit defaults.
- Production still starts with local/self-hosted models until a tenant overlay says otherwise.
