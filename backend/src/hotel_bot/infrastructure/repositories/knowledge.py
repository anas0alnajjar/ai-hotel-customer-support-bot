"""SQLAlchemy adapter for knowledge revisions and index lifecycle metadata."""

from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any, cast
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from hotel_bot.domain.knowledge.enums import IndexStatus, KnowledgeStatus, SourceFormat
from hotel_bot.domain.knowledge.errors import (
    KnowledgeAuthorizationError,
    KnowledgeValidationError,
)
from hotel_bot.domain.knowledge.models import (
    ChunkDraft,
    IndexArtifact,
    IndexVersionSnapshot,
    KnowledgeDocumentSnapshot,
    KnowledgeRevisionSnapshot,
    StoredChunk,
    SupportedLanguage,
)
from hotel_bot.persistence.enums import ActorType, AdminRole, AdminStatus
from hotel_bot.persistence.models import (
    AdminUser,
    AuditEvent,
    IndexVersion,
    KnowledgeChunk,
    KnowledgeDocument,
    KnowledgeRevision,
)


def utc_now_naive() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


class SQLAlchemyKnowledgeRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def _require_admin(self, admin_id: UUID) -> AdminUser:
        admin = await self._session.scalar(
            select(AdminUser).where(AdminUser.id == admin_id).with_for_update().limit(1)
        )
        if (
            admin is None
            or admin.status is not AdminStatus.ACTIVE
            or admin.role is not AdminRole.ADMIN
        ):
            raise KnowledgeAuthorizationError(
                "knowledge_admin_required", "an active administrator is required"
            )
        return admin

    async def _approved_revision_ids(self, document_id: UUID) -> set[UUID]:
        events = (
            await self._session.scalars(
                select(AuditEvent).where(
                    AuditEvent.resource_type == "knowledge_document",
                    AuditEvent.resource_id == document_id,
                    AuditEvent.action.in_(
                        (
                            "knowledge_revision_approved",
                            "knowledge_revision_reactivated",
                        )
                    ),
                )
            )
        ).all()
        approved: set[UUID] = set()
        for event in events:
            value = (event.metadata_redacted or {}).get("revision_id")
            try:
                approved.add(UUID(str(value)))
            except (TypeError, ValueError):
                continue
        return approved

    async def create_document(
        self,
        *,
        admin_id: UUID,
        title: str,
        language: SupportedLanguage,
        source_format: SourceFormat,
        content: str,
        checksum: str,
    ) -> tuple[KnowledgeDocumentSnapshot, KnowledgeRevisionSnapshot]:
        await self._require_admin(admin_id)
        document = KnowledgeDocument(
            title=title,
            language=language,
            source_format=source_format.value,
            status=KnowledgeStatus.DRAFT,
        )
        self._session.add(document)
        await self._session.flush()
        revision = KnowledgeRevision(
            document_id=document.id,
            content=content,
            checksum=checksum,
            version=1,
            created_by=admin_id,
        )
        self._session.add(revision)
        await self._session.flush()
        self._audit(
            admin_id,
            "knowledge_document_created",
            "knowledge_document",
            document.id,
            {"revision_id": str(revision.id), "version": 1, "language": language},
        )
        await self._session.flush()
        return self._map_document(document), self._map_revision(revision, document)

    async def add_revision(
        self,
        *,
        admin_id: UUID,
        document_id: UUID,
        title: str | None,
        content: str,
        checksum: str,
    ) -> KnowledgeRevisionSnapshot:
        await self._require_admin(admin_id)
        document = await self._session.scalar(
            select(KnowledgeDocument)
            .where(KnowledgeDocument.id == document_id)
            .with_for_update()
            .limit(1)
        )
        if document is None or document.status is KnowledgeStatus.ARCHIVED:
            raise KnowledgeValidationError(
                "knowledge_document_unavailable", "knowledge document is unavailable"
            )
        existing = await self._session.scalar(
            select(KnowledgeRevision).where(
                KnowledgeRevision.document_id == document_id,
                KnowledgeRevision.checksum == checksum,
            )
        )
        if existing is not None:
            return self._map_revision(existing, document)
        latest_version = await self._session.scalar(
            select(func.max(KnowledgeRevision.version)).where(
                KnowledgeRevision.document_id == document_id
            )
        )
        if title is not None:
            document.title = title
        revision = KnowledgeRevision(
            document_id=document_id,
            content=content,
            checksum=checksum,
            version=int(latest_version or 0) + 1,
            created_by=admin_id,
        )
        self._session.add(revision)
        await self._session.flush()
        self._audit(
            admin_id,
            "knowledge_revision_created",
            "knowledge_document",
            document_id,
            {"revision_id": str(revision.id), "version": revision.version},
        )
        await self._session.flush()
        return self._map_revision(revision, document)

    async def approve_revision(
        self, *, admin_id: UUID, document_id: UUID, revision_id: UUID
    ) -> KnowledgeDocumentSnapshot:
        await self._require_admin(admin_id)
        document = await self._session.scalar(
            select(KnowledgeDocument)
            .where(KnowledgeDocument.id == document_id)
            .with_for_update()
            .limit(1)
        )
        revision = await self._session.get(KnowledgeRevision, revision_id)
        if (
            document is None
            or revision is None
            or revision.document_id != document_id
            or document.status is KnowledgeStatus.ARCHIVED
        ):
            raise KnowledgeValidationError(
                "knowledge_revision_unavailable", "knowledge revision cannot be approved"
            )
        approved_revision_ids = await self._approved_revision_ids(document_id)
        previous_revision_id = document.current_revision_id
        document.current_revision_id = revision_id
        document.status = KnowledgeStatus.APPROVED
        self._audit(
            admin_id,
            (
                "knowledge_revision_reactivated"
                if revision_id in approved_revision_ids
                else "knowledge_revision_approved"
            ),
            "knowledge_document",
            document_id,
            {
                "revision_id": str(revision_id),
                "version": revision.version,
                "previous_revision_id": (
                    str(previous_revision_id) if previous_revision_id else None
                ),
            },
        )
        await self._session.flush()
        return self._map_document(document)

    async def edit_draft_revision(
        self,
        *,
        admin_id: UUID,
        document_id: UUID,
        revision_id: UUID,
        content: str,
        checksum: str,
    ) -> KnowledgeRevisionSnapshot:
        await self._require_admin(admin_id)
        document = await self._session.scalar(
            select(KnowledgeDocument)
            .where(KnowledgeDocument.id == document_id)
            .with_for_update()
            .limit(1)
        )
        revision = await self._session.scalar(
            select(KnowledgeRevision)
            .where(
                KnowledgeRevision.id == revision_id,
                KnowledgeRevision.document_id == document_id,
            )
            .with_for_update()
            .limit(1)
        )
        if (
            document is None
            or revision is None
            or document.status is KnowledgeStatus.ARCHIVED
            or revision_id == document.current_revision_id
            or revision_id in await self._approved_revision_ids(document_id)
        ):
            raise KnowledgeValidationError(
                "knowledge_revision_immutable",
                "approved and historical revisions cannot be edited",
            )
        duplicate = await self._session.scalar(
            select(KnowledgeRevision.id).where(
                KnowledgeRevision.document_id == document_id,
                KnowledgeRevision.checksum == checksum,
                KnowledgeRevision.id != revision_id,
            )
        )
        if duplicate is not None:
            raise KnowledgeValidationError(
                "knowledge_revision_duplicate",
                "draft content duplicates another revision",
            )
        revision.content = content
        revision.checksum = checksum
        self._audit(
            admin_id,
            "knowledge_revision_draft_edited",
            "knowledge_document",
            document_id,
            {"revision_id": str(revision_id), "version": revision.version},
        )
        await self._session.flush()
        return self._map_revision(revision, document)

    async def archive_document(
        self, *, admin_id: UUID, document_id: UUID
    ) -> KnowledgeDocumentSnapshot:
        await self._require_admin(admin_id)
        document = await self._session.scalar(
            select(KnowledgeDocument)
            .where(KnowledgeDocument.id == document_id)
            .with_for_update()
            .limit(1)
        )
        if document is None:
            raise KnowledgeValidationError(
                "knowledge_document_unavailable", "knowledge document is unavailable"
            )
        document.status = KnowledgeStatus.ARCHIVED
        self._audit(
            admin_id,
            "knowledge_document_archived",
            "knowledge_document",
            document_id,
            None,
        )
        await self._session.flush()
        return self._map_document(document)

    async def restore_document(
        self, *, admin_id: UUID, document_id: UUID
    ) -> KnowledgeDocumentSnapshot:
        await self._require_admin(admin_id)
        document = await self._session.scalar(
            select(KnowledgeDocument)
            .where(KnowledgeDocument.id == document_id)
            .with_for_update()
            .limit(1)
        )
        if document is None or document.status is not KnowledgeStatus.ARCHIVED:
            raise KnowledgeValidationError(
                "knowledge_document_not_archived",
                "only an archived knowledge document can be restored",
            )
        document.status = (
            KnowledgeStatus.APPROVED
            if document.current_revision_id is not None
            else KnowledgeStatus.DRAFT
        )
        self._audit(
            admin_id,
            "knowledge_document_restored",
            "knowledge_document",
            document_id,
            {
                "current_revision_id": (
                    str(document.current_revision_id) if document.current_revision_id else None
                )
            },
        )
        await self._session.flush()
        return self._map_document(document)

    async def retire_active_indexes(self, *, admin_id: UUID) -> None:
        await self._require_admin(admin_id)
        active = (
            await self._session.scalars(
                select(IndexVersion)
                .where(IndexVersion.status == IndexStatus.ACTIVE)
                .with_for_update()
            )
        ).all()
        for version in active:
            version.status = IndexStatus.RETIRED
            self._audit(
                admin_id,
                "knowledge_index_retired_no_eligible_documents",
                "index_version",
                version.id,
                None,
            )
        await self._session.flush()

    async def list_approved_revisions(self) -> tuple[KnowledgeRevisionSnapshot, ...]:
        rows = (
            await self._session.execute(
                select(KnowledgeRevision, KnowledgeDocument)
                .join(
                    KnowledgeDocument,
                    KnowledgeDocument.current_revision_id == KnowledgeRevision.id,
                )
                .where(KnowledgeDocument.status == KnowledgeStatus.APPROVED)
                .order_by(KnowledgeDocument.language, KnowledgeDocument.title)
            )
        ).all()
        return tuple(self._map_revision(revision, document) for revision, document in rows)

    async def create_index_build(
        self,
        *,
        admin_id: UUID,
        index_version_id: UUID,
        embedding_model: str,
        dimension: int,
        chunk_config: dict[str, object],
    ) -> IndexVersionSnapshot:
        await self._require_admin(admin_id)
        row = IndexVersion(
            id=index_version_id,
            embedding_model=embedding_model,
            dimension=dimension,
            chunk_config=chunk_config,
            checksum=None,
            document_count=0,
            chunk_count=0,
            status=IndexStatus.BUILDING,
            created_at=utc_now_naive(),
        )
        self._session.add(row)
        self._audit(
            admin_id,
            "knowledge_index_build_started",
            "index_version",
            index_version_id,
            {"embedding_model": embedding_model, "dimension": dimension},
        )
        await self._session.flush()
        return self._map_index(row)

    async def activate_index_build(
        self,
        *,
        index_version_id: UUID,
        artifact: IndexArtifact,
        chunks: Sequence[ChunkDraft],
        embedding_config_id: str,
        document_count: int,
    ) -> IndexVersionSnapshot:
        versions = (
            await self._session.scalars(
                select(IndexVersion).order_by(IndexVersion.id).with_for_update()
            )
        ).all()
        target = next((item for item in versions if item.id == index_version_id), None)
        if target is None or target.status is not IndexStatus.BUILDING:
            raise KnowledgeValidationError(
                "index_build_not_activatable", "index build is not in building state"
            )
        if artifact.dimension != target.dimension or artifact.vector_count != len(chunks):
            raise KnowledgeValidationError(
                "index_artifact_mismatch", "index artifact does not match build metadata"
            )
        eligible_revision_ids = set(
            await self._session.scalars(
                select(KnowledgeDocument.current_revision_id).where(
                    KnowledgeDocument.status == KnowledgeStatus.APPROVED,
                    KnowledgeDocument.current_revision_id.is_not(None),
                )
            )
        )
        materialized_revision_ids = {chunk.revision_id for chunk in chunks}
        if materialized_revision_ids != eligible_revision_ids:
            raise KnowledgeValidationError(
                "index_build_stale",
                "knowledge lifecycle changed while the index was being built",
            )
        for chunk in chunks:
            self._session.add(
                KnowledgeChunk(
                    revision_id=chunk.revision_id,
                    index_version_id=index_version_id,
                    chunk_index=chunk.chunk_index,
                    text=chunk.text,
                    metadata_json=chunk.metadata,
                    embedding_config_id=embedding_config_id,
                    faiss_vector_id=chunk.faiss_vector_id,
                )
            )
        now = utc_now_naive()
        for version in versions:
            if version.status is IndexStatus.ACTIVE:
                version.status = IndexStatus.RETIRED
        target.checksum = artifact.checksum
        target.artifact_path = artifact.relative_path
        target.document_count = document_count
        target.chunk_count = len(chunks)
        target.build_error = None
        target.status = IndexStatus.ACTIVE
        target.activated_at = now
        self._audit(
            None,
            "knowledge_index_activated",
            "index_version",
            index_version_id,
            {
                "checksum": artifact.checksum,
                "document_count": document_count,
                "chunk_count": len(chunks),
            },
        )
        await self._session.flush()
        return self._map_index(target)

    async def fail_index_build(
        self, *, index_version_id: UUID, error_summary: str
    ) -> IndexVersionSnapshot:
        row = await self._session.scalar(
            select(IndexVersion)
            .where(IndexVersion.id == index_version_id)
            .with_for_update()
            .limit(1)
        )
        if row is None or row.status is not IndexStatus.BUILDING:
            raise KnowledgeValidationError("index_build_not_found", "index build was not found")
        row.status = IndexStatus.FAILED
        row.build_error = error_summary[:1000]
        self._audit(
            None,
            "knowledge_index_build_failed",
            "index_version",
            index_version_id,
            {"error_type": error_summary.split(":", 1)[0]},
        )
        await self._session.flush()
        return self._map_index(row)

    async def get_active_index(
        self,
    ) -> tuple[IndexVersionSnapshot, tuple[StoredChunk, ...]] | None:
        index = await self._session.scalar(
            select(IndexVersion)
            .where(IndexVersion.status == IndexStatus.ACTIVE)
            .order_by(IndexVersion.activated_at.desc())
            .limit(1)
        )
        if index is None:
            return None
        rows = (
            await self._session.execute(
                select(KnowledgeChunk, KnowledgeDocument)
                .join(KnowledgeRevision, KnowledgeRevision.id == KnowledgeChunk.revision_id)
                .join(KnowledgeDocument, KnowledgeDocument.id == KnowledgeRevision.document_id)
                .where(
                    KnowledgeChunk.index_version_id == index.id,
                    KnowledgeDocument.status == KnowledgeStatus.APPROVED,
                    KnowledgeDocument.current_revision_id == KnowledgeRevision.id,
                )
                .order_by(KnowledgeChunk.faiss_vector_id)
            )
        ).all()
        chunks = tuple(self._map_chunk(chunk, document) for chunk, document in rows)
        return self._map_index(index), chunks

    def _audit(
        self,
        actor_id: UUID | None,
        action: str,
        resource_type: str,
        resource_id: UUID,
        metadata: dict[str, Any] | None,
    ) -> None:
        self._session.add(
            AuditEvent(
                actor_type=ActorType.ADMIN if actor_id else ActorType.SYSTEM,
                actor_id=actor_id,
                action=action,
                resource_type=resource_type,
                resource_id=resource_id,
                metadata_redacted=metadata,
                correlation_id=f"knowledge:{resource_id}",
            )
        )

    @staticmethod
    def _map_document(row: KnowledgeDocument) -> KnowledgeDocumentSnapshot:
        return KnowledgeDocumentSnapshot(
            id=row.id,
            title=row.title,
            language=cast(SupportedLanguage, row.language),
            source_format=SourceFormat(row.source_format),
            status=KnowledgeStatus(row.status),
            current_revision_id=row.current_revision_id,
        )

    @staticmethod
    def _map_revision(
        row: KnowledgeRevision, document: KnowledgeDocument
    ) -> KnowledgeRevisionSnapshot:
        return KnowledgeRevisionSnapshot(
            id=row.id,
            document_id=row.document_id,
            title=document.title,
            language=cast(SupportedLanguage, document.language),
            content=row.content,
            checksum=row.checksum,
            version=row.version,
        )

    @staticmethod
    def _map_index(row: IndexVersion) -> IndexVersionSnapshot:
        return IndexVersionSnapshot(
            id=row.id,
            embedding_model=row.embedding_model,
            dimension=row.dimension,
            chunk_config=row.chunk_config,
            checksum=row.checksum,
            artifact_path=row.artifact_path,
            document_count=row.document_count,
            chunk_count=row.chunk_count,
            status=IndexStatus(row.status),
            build_error=row.build_error,
            activated_at=row.activated_at,
            created_at=row.created_at,
        )

    @staticmethod
    def _map_chunk(row: KnowledgeChunk, document: KnowledgeDocument) -> StoredChunk:
        metadata = {
            **(row.metadata_json or {}),
            "document_id": str(document.id),
            "title": document.title,
            "language": document.language,
        }
        return StoredChunk(
            id=row.id,
            revision_id=row.revision_id,
            index_version_id=row.index_version_id,
            chunk_index=row.chunk_index,
            text=row.text,
            metadata=metadata,
            faiss_vector_id=row.faiss_vector_id,
        )
