"""Known provider names. Registration of a factory is separate (see registry)."""

from __future__ import annotations

KNOWN_PROVIDERS: dict[str, frozenset[str]] = {
    "llm": frozenset(
        {
            "ollama",
            "openai",
            "anthropic",
            "azure_openai",
            "gemini",
            "vllm",
            "openai_compatible",
            "extractive",
        }
    ),
    "embedding": frozenset(
        {
            "ollama",
            "openai",
            "cohere",
            "voyage",
            "huggingface",
            "openai_compatible",
            "hashing",
        }
    ),
    "vector_store": frozenset(
        {
            "pgvector",
            "qdrant",
            "milvus",
            "weaviate",
            "pinecone",
            "opensearch",
            "chroma",
        }
    ),
    "sparse_index": frozenset({"postgres_fts", "opensearch"}),
    "reranker": frozenset({"identity", "lexical", "cohere", "cross_encoder", "bge", "llm"}),
    "parser": frozenset({"builtin", "unstructured", "tika"}),
    "chunker": frozenset(
        {
            "recursive",
            "fixed",
            "token",
            "sentence",
            "semantic",
            "markdown",
            "structure",
        }
    ),
    "connector": frozenset(
        {
            "local_fs",
            "s3",
            "upload",
            "google_drive",
            "onedrive",
            "sharepoint",
            "dropbox",
            "azure_blob",
            "mock_local_fs",
            "mock_google_drive",
            "mock_onedrive",
            "mock_dropbox",
            "mock_s3",
        }
    ),
    "storage": frozenset({"s3", "azure_blob", "local_fs"}),
    "queue": frozenset({"asyncio", "taskiq_redis", "celery_redis", "rabbitmq"}),
    "ocr": frozenset({"tesseract", "none"}),
    "memory": frozenset({"postgres", "none"}),
    "auth": frozenset({"password", "oidc"}),
}

PROVIDER_CONFIG_FIELDS: dict[str, str] = {
    "llm": "llm",
    "embedding": "embedding",
    "vector_store": "vector_store",
    "sparse_index": "sparse_index",
    "reranker": "reranker",
    "parser": "parser",
    "storage": "storage",
    "queue": "queue",
    "ocr": "ocr",
    "memory": "memory",
    "auth": "auth",
}
