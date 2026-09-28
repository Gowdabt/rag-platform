from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.config.catalog import KNOWN_PROVIDERS


class FrozenModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class PlatformMetaConfig(FrozenModel):
    name: str = "rag-platform"
    environment: str = "development"


class LLMConfig(FrozenModel):
    provider: str
    model: str
    temperature: float = 0.1
    max_tokens: int = 4000
    api_base: str | None = None
    api_key: str | None = None

    @field_validator("temperature")
    @classmethod
    def _temp(cls, v: float) -> float:
        if not 0 <= v <= 2:
            raise ValueError("llm.temperature must be between 0 and 2")
        return v

    @field_validator("max_tokens")
    @classmethod
    def _tokens(cls, v: int) -> int:
        if v < 1 or v > 128_000:
            raise ValueError("llm.max_tokens out of range")
        return v


class EmbeddingConfig(FrozenModel):
    provider: str
    model: str
    dimensions: int | None = None

    @field_validator("dimensions")
    @classmethod
    def _dims(cls, v: int | None) -> int | None:
        if v is not None and v < 1:
            raise ValueError("embedding.dimensions must be positive")
        return v


class ParserConfig(FrozenModel):
    provider: str = "builtin"


class ChunkingConfig(FrozenModel):
    strategy: str = "recursive"
    chunk_size: int = 800
    chunk_overlap: int = 120

    @model_validator(mode="after")
    def _overlap(self) -> ChunkingConfig:
        if self.chunk_size < 1:
            raise ValueError("chunking.chunk_size must be positive")
        if self.chunk_overlap < 0 or self.chunk_overlap >= self.chunk_size:
            raise ValueError("chunking.chunk_overlap must be >= 0 and < chunk_size")
        return self


class DenseRetrievalConfig(FrozenModel):
    top_k: int = 20


class SparseRetrievalConfig(FrozenModel):
    top_k: int = 20


class FusionConfig(FrozenModel):
    method: Literal["rrf", "weighted"] = "rrf"
    dense_weight: float = 0.5
    sparse_weight: float = 0.5


class RetrievalConfig(FrozenModel):
    strategy: str = "hybrid"
    top_k: int = 20
    dense: DenseRetrievalConfig = Field(default_factory=DenseRetrievalConfig)
    sparse: SparseRetrievalConfig = Field(default_factory=SparseRetrievalConfig)
    fusion: FusionConfig = Field(default_factory=FusionConfig)

    @field_validator("top_k")
    @classmethod
    def _topk(cls, v: int) -> int:
        if v < 1 or v > 100:
            raise ValueError("retrieval.top_k must be between 1 and 100")
        return v


class RerankerConfig(FrozenModel):
    provider: str = "identity"
    model: str | None = None
    top_k: int = 8


class VectorStoreConfig(FrozenModel):
    provider: str
    collection: str = "documents"
    url: str | None = None
    api_key: str | None = None


class SparseIndexConfig(FrozenModel):
    provider: str = "postgres_fts"


class DatabaseConfig(FrozenModel):
    provider: str = "postgres"
    url: str


class StorageConfig(FrozenModel):
    provider: str = "s3"
    bucket: str
    region: str = "us-east-1"
    endpoint_url: str | None = None
    access_key: str | None = None
    secret_key: str | None = None


class RedisConfig(FrozenModel):
    url: str


class OCRConfig(FrozenModel):
    enabled: bool = False
    provider: str = "tesseract"


class ConversationConfig(FrozenModel):
    enabled: bool = True
    max_history_messages: int = 20


class GenerationConfig(FrozenModel):
    require_citations: bool = True
    refuse_without_evidence: bool = True
    minimum_relevance_score: float = 0.72
    refusal_message: str = (
        "I couldn't find enough information in the available documents to answer that reliably."
    )
    system_instructions: str | None = None
    rag_enabled: bool = True


class MemoryConfig(FrozenModel):
    enabled: bool = False
    provider: str = "postgres"


class PrivacyConfig(FrozenModel):
    store_raw_documents: bool = True
    store_queries: bool = True
    store_llm_prompts: bool = False
    store_llm_responses: bool = True
    redact_pii: bool = False


class LimitsConfig(FrozenModel):
    monthly_budget_usd: float | None = None
    max_tokens_per_request: int = 10_000


class ModelRoutingConfig(FrozenModel):
    enabled: bool = False
    routes: dict[str, dict[str, Any]] = Field(default_factory=dict)


class OauthAppConfig(FrozenModel):
    client_id: str = ""
    client_secret: str = ""


class OauthConfig(FrozenModel):
    google: OauthAppConfig = Field(default_factory=OauthAppConfig)
    microsoft: OauthAppConfig = Field(default_factory=OauthAppConfig)
    dropbox: OauthAppConfig = Field(default_factory=OauthAppConfig)


class ConnectorsConfig(FrozenModel):
    fs_roots: list[str] = Field(default_factory=list)
    fs_isolation: Literal["user", "host"] = "user"


class AuthConfig(FrozenModel):
    provider: str = "password"
    jwt_secret: str
    access_ttl_seconds: int = 900
    refresh_ttl_seconds: int = 1_209_600


class HttpConfig(FrozenModel):
    cors_origins: list[str] = Field(
        default_factory=lambda: [
            "http://localhost:5173",
            "http://127.0.0.1:5173",
            "http://localhost:8000",
            "http://127.0.0.1:8000",
            "http://localhost:17800",
            "http://127.0.0.1:17800",
        ]
    )


class CatalogLLM(FrozenModel):
    provider: str
    model: str


class AICatalogConfig(FrozenModel):
    llm: list[CatalogLLM] = Field(default_factory=list)


class QueueConfig(FrozenModel):
    provider: str = "taskiq_redis"


class ObservabilityConfig(FrozenModel):
    log_level: str = "INFO"
    otel_enabled: bool = False


class PlatformSettings(FrozenModel):
    platform: PlatformMetaConfig
    llm: LLMConfig
    embedding: EmbeddingConfig
    parser: ParserConfig = Field(default_factory=ParserConfig)
    chunking: ChunkingConfig = Field(default_factory=ChunkingConfig)
    retrieval: RetrievalConfig = Field(default_factory=RetrievalConfig)
    reranker: RerankerConfig = Field(default_factory=RerankerConfig)
    vector_store: VectorStoreConfig
    sparse_index: SparseIndexConfig = Field(default_factory=SparseIndexConfig)
    database: DatabaseConfig
    storage: StorageConfig
    redis: RedisConfig
    ocr: OCRConfig = Field(default_factory=OCRConfig)
    conversation: ConversationConfig = Field(default_factory=ConversationConfig)
    generation: GenerationConfig = Field(default_factory=GenerationConfig)
    memory: MemoryConfig = Field(default_factory=MemoryConfig)
    privacy: PrivacyConfig = Field(default_factory=PrivacyConfig)
    limits: LimitsConfig = Field(default_factory=LimitsConfig)
    model_routing: ModelRoutingConfig = Field(default_factory=ModelRoutingConfig)
    auth: AuthConfig
    http: HttpConfig = Field(default_factory=HttpConfig)
    ai_catalog: AICatalogConfig = Field(default_factory=AICatalogConfig)
    oauth: OauthConfig = Field(default_factory=OauthConfig)
    connectors: ConnectorsConfig = Field(default_factory=ConnectorsConfig)
    queue: QueueConfig = Field(default_factory=QueueConfig)
    observability: ObservabilityConfig = Field(default_factory=ObservabilityConfig)

    @model_validator(mode="after")
    def _known_providers(self) -> PlatformSettings:
        checks: list[tuple[str, str]] = [
            ("llm", self.llm.provider),
            ("embedding", self.embedding.provider),
            ("vector_store", self.vector_store.provider),
            ("sparse_index", self.sparse_index.provider),
            ("reranker", self.reranker.provider),
            ("parser", self.parser.provider),
            ("chunker", self.chunking.strategy),
            ("storage", self.storage.provider),
            ("queue", self.queue.provider),
            ("memory", self.memory.provider),
            ("auth", self.auth.provider),
        ]
        if self.ocr.enabled:
            checks.append(("ocr", self.ocr.provider))
        for kind, name in checks:
            known = KNOWN_PROVIDERS.get(kind)
            if known is None:
                continue
            if name not in known:
                raise ValueError(
                    f"Unknown {kind} provider '{name}'. Known: {sorted(known)}"
                )
        return self
