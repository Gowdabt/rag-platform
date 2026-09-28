# Configuration (as implemented)

## Cascade

Base YAML → environment YAML (`configs/development.yaml`, etc.) → tenant/org/workspace overlays in `config_overlays` (denylist prevents overriding isolation/security keys). See ADR 009.

Load: `app.config.load.load_platform_settings`. Secrets via `env:` refs, not committed `.env`.

## Development defaults (`configs/development.yaml`)

| Key | Value | Notes |
| --- | --- | --- |
| `llm.provider` | `ollama` | `llama3.2`. Requires Ollama running. Extractive still registered. |
| `embedding.provider` | `hashing` | Dense retrieval skipped. Do not silently switch; re-ingest after a real embedder. |
| `reranker.provider` | `lexical` | |
| `retrieval.strategy` | `hybrid` | Effectively sparse while hashing. |
| `queue.provider` | `asyncio` | |
| `storage.provider` | `local_fs` | |

## Providers you can set without code changes

LLM: `extractive`, `ollama`, `openai`, `openai_compatible`, `vllm`

Embedding: `hashing`, `ollama`, `openai`, `openai_compatible`

Vector: `pgvector`

Sparse: `postgres_fts`

Reranker: `identity`, `lexical`

Storage: `local_fs`, `s3`

Queue: `asyncio`, `taskiq_redis`

Connectors: `mock_google_drive`, `mock_onedrive`, `mock_dropbox`, `mock_s3`, `mock_local_fs`

## Connector simulate flags

On a source’s `connector_config.simulate`: `auth_expired`, `rate_limit`, `network`, `partial_sync`.

## Encryption

`TOKEN_ENCRYPTION_KEY` (optional). Falls back to `JWT_SECRET` for `LocalTokenCipher`. Rotate by re-connecting sources (tokens would not decrypt).
