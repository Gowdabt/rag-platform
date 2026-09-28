from __future__ import annotations

import os


def load_providers() -> None:
    from app.adapters.auth import password as _password  # noqa: F401
    from app.adapters.providers.chunkers import text as _chunkers  # noqa: F401
    from app.adapters.providers.connectors import dropbox as _dropbox  # noqa: F401
    from app.adapters.providers.connectors import google_drive as _gdrive  # noqa: F401
    from app.adapters.providers.connectors import local_fs as _local_fs  # noqa: F401
    from app.adapters.providers.connectors import microsoft as _ms  # noqa: F401
    from app.adapters.providers.connectors import s3 as _s3_conn  # noqa: F401
    from app.adapters.providers.embeddings import hashing as _hash  # noqa: F401
    from app.adapters.providers.embeddings import ollama as _emb  # noqa: F401
    from app.adapters.providers.llm import extractive as _ext  # noqa: F401
    from app.adapters.providers.llm import ollama as _ollama  # noqa: F401
    from app.adapters.providers.llm import openai_compatible as _oai  # noqa: F401
    from app.adapters.providers.memory import postgres as _mem  # noqa: F401
    from app.adapters.providers.parsers import builtin as _parser  # noqa: F401
    from app.adapters.providers.queues import asyncio_queue as _queue  # noqa: F401
    from app.adapters.providers.rerankers import identity as _rerank  # noqa: F401
    from app.adapters.providers.rerankers import lexical as _lexrank  # noqa: F401
    from app.adapters.providers.sparse_indexes import postgres_fts as _fts  # noqa: F401
    from app.adapters.providers.storage import local_fs as _fs  # noqa: F401
    from app.adapters.providers.storage import s3 as _s3  # noqa: F401
    from app.adapters.providers.vectorstores import pgvector_store as _pg  # noqa: F401

    if os.environ.get("RAG_CONNECTOR_MOCKS", "").lower() in {"1", "true", "yes"}:
        from app.adapters.providers.connectors import mock as _connectors  # noqa: F401
