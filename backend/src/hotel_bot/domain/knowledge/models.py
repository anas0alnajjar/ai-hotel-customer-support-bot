"""Provider-neutral knowledge, index, and retrieval contracts."""

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from hotel_bot.domain.knowledge.enums import IndexStatus, KnowledgeStatus, SourceFormat

SupportedLanguage = Literal["ar", "en"]


class KnowledgeDocumentSnapshot(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: UUID
    title: str
    language: SupportedLanguage
    source_format: SourceFormat
    status: KnowledgeStatus
    current_revision_id: UUID | None


class KnowledgeRevisionSnapshot(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: UUID
    document_id: UUID
    title: str
    language: SupportedLanguage
    content: str
    checksum: str
    version: int


class ChunkDraft(BaseModel):
    model_config = ConfigDict(frozen=True)

    revision_id: UUID
    chunk_index: int = Field(ge=0)
    text: str
    metadata: dict[str, Any]
    faiss_vector_id: int = Field(ge=0)


class StoredChunk(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: UUID
    revision_id: UUID
    index_version_id: UUID
    chunk_index: int
    text: str
    metadata: dict[str, Any]
    faiss_vector_id: int


class IndexVersionSnapshot(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: UUID
    embedding_model: str
    dimension: int
    chunk_config: dict[str, Any]
    checksum: str | None
    artifact_path: str | None
    document_count: int
    chunk_count: int
    status: IndexStatus
    build_error: str | None
    activated_at: datetime | None
    created_at: datetime


class IndexArtifact(BaseModel):
    model_config = ConfigDict(frozen=True)

    relative_path: str
    checksum: str
    dimension: int
    vector_count: int


class IndexBuildPlan(BaseModel):
    model_config = ConfigDict(frozen=True)

    index: IndexVersionSnapshot
    revisions: tuple[KnowledgeRevisionSnapshot, ...]
    chunks: tuple[ChunkDraft, ...]


class IndexBuildMaterialization(BaseModel):
    model_config = ConfigDict(frozen=True)

    plan: IndexBuildPlan
    artifact: IndexArtifact


class RetrievalEvidence(BaseModel):
    model_config = ConfigDict(frozen=True)

    chunk_id: UUID
    document_id: UUID
    revision_id: UUID
    title: str
    language: SupportedLanguage
    text: str
    score: float
    rank: int = Field(ge=1)


class RetrievalResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    query: str
    index_version_id: UUID | None
    evidence: tuple[RetrievalEvidence, ...]
    sufficient: bool
    reason_code: str
