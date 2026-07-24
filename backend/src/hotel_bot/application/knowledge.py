"""Knowledge revision, index-build, and safe retrieval use cases."""

import hashlib
import json
from collections.abc import Mapping, Sequence
from typing import Protocol, cast
from uuid import UUID, uuid4

from hotel_bot.domain.knowledge.chunking import chunk_text, validate_content
from hotel_bot.domain.knowledge.enums import SourceFormat
from hotel_bot.domain.knowledge.errors import IndexUnavailableError, KnowledgeValidationError
from hotel_bot.domain.knowledge.models import (
    ChunkDraft,
    IndexArtifact,
    IndexBuildMaterialization,
    IndexBuildPlan,
    IndexVersionSnapshot,
    KnowledgeDocumentSnapshot,
    KnowledgeRevisionSnapshot,
    RetrievalEvidence,
    RetrievalResult,
    StoredChunk,
    SupportedLanguage,
)


class EmbeddingProvider(Protocol):
    @property
    def model_id(self) -> str: ...

    @property
    def dimension(self) -> int: ...

    def embed_documents(self, texts: Sequence[str]) -> list[list[float]]: ...

    def embed_query(self, text: str) -> list[float]: ...


class VectorIndexStore(Protocol):
    def build(
        self,
        *,
        index_version_id: UUID,
        embedding_model: str,
        vectors: Sequence[Sequence[float]],
        chunk_keys: Sequence[str],
    ) -> IndexArtifact: ...

    def search(
        self,
        *,
        relative_path: str,
        expected_checksum: str,
        query_vector: Sequence[float],
        top_k: int,
    ) -> tuple[tuple[int, float], ...]: ...

    def validate(self, *, relative_path: str, expected_checksum: str) -> IndexArtifact: ...


class KnowledgeRepository(Protocol):
    async def create_document(
        self,
        *,
        admin_id: UUID,
        title: str,
        language: SupportedLanguage,
        source_format: SourceFormat,
        content: str,
        checksum: str,
    ) -> tuple[KnowledgeDocumentSnapshot, KnowledgeRevisionSnapshot]: ...

    async def add_revision(
        self,
        *,
        admin_id: UUID,
        document_id: UUID,
        title: str | None,
        content: str,
        checksum: str,
    ) -> KnowledgeRevisionSnapshot: ...

    async def approve_revision(
        self, *, admin_id: UUID, document_id: UUID, revision_id: UUID
    ) -> KnowledgeDocumentSnapshot: ...

    async def archive_document(
        self, *, admin_id: UUID, document_id: UUID
    ) -> KnowledgeDocumentSnapshot: ...

    async def list_approved_revisions(self) -> tuple[KnowledgeRevisionSnapshot, ...]: ...

    async def create_index_build(
        self,
        *,
        admin_id: UUID,
        index_version_id: UUID,
        embedding_model: str,
        dimension: int,
        chunk_config: dict[str, object],
    ) -> IndexVersionSnapshot: ...

    async def activate_index_build(
        self,
        *,
        index_version_id: UUID,
        artifact: IndexArtifact,
        chunks: Sequence[ChunkDraft],
        embedding_config_id: str,
        document_count: int,
    ) -> IndexVersionSnapshot: ...

    async def fail_index_build(
        self, *, index_version_id: UUID, error_summary: str
    ) -> IndexVersionSnapshot: ...

    async def get_active_index(
        self,
    ) -> tuple[IndexVersionSnapshot, tuple[StoredChunk, ...]] | None: ...


def _language(value: str) -> SupportedLanguage:
    normalized = value.strip().lower()
    if normalized not in {"ar", "en"}:
        raise KnowledgeValidationError("unsupported_language", "language must be 'ar' or 'en'")
    return cast(SupportedLanguage, normalized)


def _title(value: str) -> str:
    normalized = " ".join(value.split())
    if not 3 <= len(normalized) <= 255:
        raise KnowledgeValidationError(
            "invalid_knowledge_title", "knowledge title must contain 3 to 255 characters"
        )
    return normalized


def _checksum(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


class KnowledgeManagementService:
    def __init__(self, repository: KnowledgeRepository) -> None:
        self._repository = repository

    async def create_document(
        self,
        *,
        admin_id: UUID,
        title: str,
        language: str,
        source_format: SourceFormat,
        content: str,
    ) -> tuple[KnowledgeDocumentSnapshot, KnowledgeRevisionSnapshot]:
        normalized_content = validate_content(content)
        return await self._repository.create_document(
            admin_id=admin_id,
            title=_title(title),
            language=_language(language),
            source_format=source_format,
            content=normalized_content,
            checksum=_checksum(normalized_content),
        )

    async def update_document(
        self,
        *,
        admin_id: UUID,
        document_id: UUID,
        content: str,
        title: str | None = None,
    ) -> KnowledgeRevisionSnapshot:
        normalized_content = validate_content(content)
        return await self._repository.add_revision(
            admin_id=admin_id,
            document_id=document_id,
            title=_title(title) if title is not None else None,
            content=normalized_content,
            checksum=_checksum(normalized_content),
        )

    async def approve_revision(
        self, *, admin_id: UUID, document_id: UUID, revision_id: UUID
    ) -> KnowledgeDocumentSnapshot:
        return await self._repository.approve_revision(
            admin_id=admin_id, document_id=document_id, revision_id=revision_id
        )

    async def archive_document(
        self, *, admin_id: UUID, document_id: UUID
    ) -> KnowledgeDocumentSnapshot:
        return await self._repository.archive_document(admin_id=admin_id, document_id=document_id)


class KnowledgeIndexService:
    def __init__(
        self,
        repository: KnowledgeRepository,
        *,
        max_chars: int = 800,
        overlap_chars: int = 120,
    ) -> None:
        self._repository = repository
        self._max_chars = max_chars
        self._overlap_chars = overlap_chars

    async def prepare_build(self, *, admin_id: UUID, embedder: EmbeddingProvider) -> IndexBuildPlan:
        revisions = await self._repository.list_approved_revisions()
        if not revisions:
            raise KnowledgeValidationError(
                "no_approved_knowledge", "at least one approved revision is required"
            )
        chunk_config: dict[str, object] = {
            "strategy": "bounded_character_v1",
            "max_chars": self._max_chars,
            "overlap_chars": self._overlap_chars,
        }
        index_id = uuid4()
        index = await self._repository.create_index_build(
            admin_id=admin_id,
            index_version_id=index_id,
            embedding_model=embedder.model_id,
            dimension=embedder.dimension,
            chunk_config=chunk_config,
        )
        chunks: list[ChunkDraft] = []
        for revision in revisions:
            for chunk_index, text in enumerate(
                chunk_text(
                    revision.content,
                    max_chars=self._max_chars,
                    overlap_chars=self._overlap_chars,
                )
            ):
                chunks.append(
                    ChunkDraft(
                        revision_id=revision.id,
                        chunk_index=chunk_index,
                        text=text,
                        metadata={
                            "document_id": str(revision.document_id),
                            "title": revision.title,
                            "language": revision.language,
                            "revision_version": revision.version,
                        },
                        faiss_vector_id=len(chunks),
                    )
                )
        return IndexBuildPlan(index=index, revisions=revisions, chunks=tuple(chunks))

    @staticmethod
    def materialize_build(
        plan: IndexBuildPlan,
        *,
        embedder: EmbeddingProvider,
        store: VectorIndexStore,
    ) -> IndexBuildMaterialization:
        if plan.index.embedding_model != embedder.model_id:
            raise KnowledgeValidationError(
                "embedding_model_mismatch", "build plan and embedding provider do not match"
            )
        vectors = embedder.embed_documents([chunk.text for chunk in plan.chunks])
        artifact = store.build(
            index_version_id=plan.index.id,
            embedding_model=embedder.model_id,
            vectors=vectors,
            chunk_keys=[f"{item.revision_id}:{item.chunk_index}" for item in plan.chunks],
        )
        return IndexBuildMaterialization(plan=plan, artifact=artifact)

    async def activate_build(
        self,
        materialization: IndexBuildMaterialization,
        *,
        store: VectorIndexStore,
    ) -> IndexVersionSnapshot:
        plan = materialization.plan
        validated_artifact = store.validate(
            relative_path=materialization.artifact.relative_path,
            expected_checksum=materialization.artifact.checksum,
        )
        if validated_artifact != materialization.artifact:
            raise KnowledgeValidationError(
                "index_artifact_mismatch", "validated index artifact metadata changed"
            )
        config_payload = json.dumps(
            {
                "embedding_model": plan.index.embedding_model,
                "dimension": plan.index.dimension,
                "chunk_config": plan.index.chunk_config,
            },
            separators=(",", ":"),
            sort_keys=True,
        )
        embedding_config_id = hashlib.sha256(config_payload.encode()).hexdigest()[:32]
        return await self._repository.activate_index_build(
            index_version_id=plan.index.id,
            artifact=validated_artifact,
            chunks=plan.chunks,
            embedding_config_id=embedding_config_id,
            document_count=len({item.document_id for item in plan.revisions}),
        )

    async def fail_build(self, index_version_id: UUID, error: Exception) -> IndexVersionSnapshot:
        summary = f"{type(error).__name__}: {error}"[:1000]
        return await self._repository.fail_index_build(
            index_version_id=index_version_id, error_summary=summary
        )


class KnowledgeRetrievalService:
    def __init__(
        self,
        repository: KnowledgeRepository,
        embedder: EmbeddingProvider,
        store: VectorIndexStore,
        *,
        top_k: int = 5,
        minimum_score: float = 0.35,
    ) -> None:
        self._repository = repository
        self._embedder = embedder
        self._store = store
        self._top_k = top_k
        self._minimum_score = minimum_score

    async def retrieve(self, query: str) -> RetrievalResult:
        normalized_query = " ".join(query.split())
        if len(normalized_query) < 2:
            raise KnowledgeValidationError("invalid_query", "retrieval query is too short")
        active = await self._repository.get_active_index()
        if active is None:
            return RetrievalResult(
                query=normalized_query,
                index_version_id=None,
                evidence=(),
                sufficient=False,
                reason_code="active_index_unavailable",
            )
        index, chunks = active
        if not index.artifact_path or not index.checksum:
            raise IndexUnavailableError(
                "active_index_incomplete", "active index metadata is incomplete"
            )
        if (
            index.embedding_model != self._embedder.model_id
            or index.dimension != self._embedder.dimension
        ):
            raise IndexUnavailableError(
                "active_index_embedding_mismatch",
                "active index and runtime embedding configuration do not match",
            )
        by_vector_id: Mapping[int, StoredChunk] = {chunk.faiss_vector_id: chunk for chunk in chunks}
        hits = self._store.search(
            relative_path=index.artifact_path,
            expected_checksum=index.checksum,
            query_vector=self._embedder.embed_query(normalized_query),
            top_k=min(index.chunk_count, self._top_k * 3),
        )
        evidence: list[RetrievalEvidence] = []
        for vector_id, score in hits:
            chunk = by_vector_id.get(vector_id)
            if chunk is None or score < self._minimum_score:
                continue
            evidence.append(
                RetrievalEvidence(
                    chunk_id=chunk.id,
                    document_id=UUID(str(chunk.metadata["document_id"])),
                    revision_id=chunk.revision_id,
                    title=str(chunk.metadata["title"]),
                    language=cast(SupportedLanguage, chunk.metadata["language"]),
                    text=chunk.text,
                    score=score,
                    rank=len(evidence) + 1,
                )
            )
            if len(evidence) == self._top_k:
                break
        return RetrievalResult(
            query=normalized_query,
            index_version_id=index.id,
            evidence=tuple(evidence),
            sufficient=bool(evidence),
            reason_code="evidence_found" if evidence else "insufficient_evidence",
        )
