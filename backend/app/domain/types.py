from __future__ import annotations

from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field


class LLMMessage(BaseModel):
    role: Literal["system", "user", "assistant"]
    content: str


class TokenUsage(BaseModel):
    input_tokens: int = 0
    output_tokens: int = 0


class LLMGenerateRequest(BaseModel):
    messages: list[LLMMessage]
    temperature: float | None = None
    max_tokens: int | None = None


class LLMGenerateResult(BaseModel):
    text: str
    model: str
    provider: str
    usage: TokenUsage = Field(default_factory=TokenUsage)


class EmbeddingResult(BaseModel):
    vectors: list[list[float]]
    model: str
    provider: str
    dimensions: int
    version: str = "1"


class VectorFilter(BaseModel):
    tenant_id: UUID
    workspace_id: UUID | None = None
    document_ids: list[UUID] | None = None
    version_id: UUID | None = None
    principal_ids: list[str] = Field(default_factory=list)
    user_id: UUID | None = None
    team_names: list[str] = Field(default_factory=list)
    role_names: list[str] = Field(default_factory=list)
    read_all: bool = False
    classification: str | None = None
    embedding_provider: str | None = None
    embedding_model: str | None = None


class VectorRecord(BaseModel):
    chunk_id: UUID
    document_id: UUID
    version_id: UUID
    workspace_id: UUID
    tenant_id: UUID
    embedding: list[float]
    payload: dict = Field(default_factory=dict)


class VectorHit(BaseModel):
    chunk_id: UUID
    document_id: UUID
    version_id: UUID
    score: float
    payload: dict = Field(default_factory=dict)


class SparseDocument(BaseModel):
    chunk_id: UUID
    document_id: UUID
    version_id: UUID
    tenant_id: UUID
    workspace_id: UUID
    text: str
    payload: dict = Field(default_factory=dict)


class ParsedPage(BaseModel):
    page_number: int
    text: str
    headings: list[str] = Field(default_factory=list)


class ParsedDocument(BaseModel):
    text: str
    mime_type: str
    metadata: dict = Field(default_factory=dict)
    pages: list[ParsedPage] = Field(default_factory=list)


class Chunk(BaseModel):
    document_id: UUID
    document_version_id: UUID
    chunk_index: int
    text: str
    page: int | None = None
    section: str | None = None
    token_count: int | None = None
    metadata: dict = Field(default_factory=dict)
    chunk_id: UUID | None = None


class RerankCandidate(BaseModel):
    chunk_id: UUID
    text: str
    score: float
    payload: dict = Field(default_factory=dict)


class ConnectorCapabilities(BaseModel):
    browse: bool = True
    subscribe: bool = True
    incremental_sync: bool = True
    webhooks: bool = False
    local_watch: bool = False


class ConnectorDefinition(BaseModel):
    id: str
    name: str
    description: str = ""
    icon: str = "folder"
    authentication: Literal["none", "oauth2", "api_key", "service_account"] = "none"
    mock: bool = False
    capabilities: ConnectorCapabilities = Field(default_factory=ConnectorCapabilities)


class ConnectorLocation(BaseModel):
    id: str
    name: str
    type: Literal["folder", "bucket", "drive", "site"] = "folder"
    parent_id: str | None = None
    path: str = ""
    child_count: int = 0


class ConnectorAuthResult(BaseModel):
    access_token: str
    refresh_token: str | None = None
    expires_in: int = 3600
    scopes: list[str] = Field(default_factory=list)
    account_label: str | None = None


class ConnectorFile(BaseModel):
    source_file_id: str
    path: str
    name: str | None = None
    parent_id: str | None = None
    etag: str | None = None
    checksum: str | None = None
    revision: str | None = None
    modified_at: str | None = None
    mime_type: str | None = None
    size_bytes: int | None = None
    content: str | None = None


class DocumentChange(BaseModel):
    event_type: Literal[
        "DOCUMENT_CREATED",
        "DOCUMENT_UPDATED",
        "DOCUMENT_DELETED",
        "DOCUMENT_MOVED",
    ]
    file: ConnectorFile


class JobHandle(BaseModel):
    job_id: UUID
    queue_message_id: str | None = None


class MemoryRecord(BaseModel):
    memory_id: UUID
    user_id: UUID
    tenant_id: UUID
    content: str
    metadata: dict = Field(default_factory=dict)
