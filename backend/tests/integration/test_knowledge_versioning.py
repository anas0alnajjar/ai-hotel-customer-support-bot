"""Real-MySQL document versioning, lifecycle, and FAISS synchronization contracts."""

import asyncio
import os
from pathlib import Path
from tempfile import TemporaryDirectory
from uuid import UUID, uuid4

import pytest
from pydantic import SecretStr
from sqlalchemy import delete, select

from hotel_bot.application.knowledge import (
    KnowledgeIndexService,
    KnowledgeManagementService,
    KnowledgeRetrievalService,
)
from hotel_bot.core.config import Settings
from hotel_bot.domain.knowledge.enums import SourceFormat
from hotel_bot.infrastructure.database import DatabaseManager
from hotel_bot.infrastructure.embeddings import HashingEmbeddingProvider
from hotel_bot.infrastructure.faiss_store import FaissIndexStore
from hotel_bot.infrastructure.repositories.admin import SQLAlchemyAdminRepository
from hotel_bot.infrastructure.repositories.knowledge import SQLAlchemyKnowledgeRepository
from hotel_bot.persistence.enums import AdminRole, AdminStatus
from hotel_bot.persistence.models import (
    AdminUser,
    AuditEvent,
    IndexVersion,
    KnowledgeChunk,
    KnowledgeDocument,
    KnowledgeRevision,
)

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        os.getenv("RUN_MYSQL_INTEGRATION") != "1",
        reason="set RUN_MYSQL_INTEGRATION=1 with the project MySQL container running",
    ),
]


def mysql_settings() -> Settings:
    project_root = Path(__file__).resolve().parents[3]
    values = {
        key: value
        for line in (project_root / ".env").read_text(encoding="utf-8").splitlines()
        if line and not line.lstrip().startswith("#") and "=" in line
        for key, value in [line.split("=", maxsplit=1)]
    }
    return Settings(
        APP_ENVIRONMENT="test",
        DB_HOST=values["DB_HOST"],
        DB_PORT=int(values["DB_PORT"]),
        DB_NAME=values["DB_NAME"],
        DB_USER=values["DB_USER"],
        DB_PASSWORD=SecretStr(values["DB_PASSWORD"]),
        _env_file=None,
    )  # type: ignore[call-arg]


def test_document_versions_archive_restore_and_faiss_remain_consistent() -> None:
    async def exercise() -> None:
        database = DatabaseManager(mysql_settings())
        admin_id = uuid4()
        document_ids: list[UUID] = []
        index_ids: list[UUID] = []
        embedder = HashingEmbeddingProvider(dimension=96)
        try:
            async with database.transaction() as session:
                session.add(
                    AdminUser(
                        id=admin_id,
                        email=f"versioning-{admin_id.hex}@example.invalid",
                        username=f"versioning-{admin_id.hex[:16]}",
                        password_hash="offline-test-only-not-a-credential",
                        role=AdminRole.ADMIN,
                        status=AdminStatus.ACTIVE,
                    )
                )

            async with database.transaction() as session:
                management = KnowledgeManagementService(SQLAlchemyKnowledgeRepository(session))
                anchor, anchor_revision = await management.create_document(
                    admin_id=admin_id,
                    title="Versioning test anchor",
                    language="en",
                    source_format=SourceFormat.PLAIN_TEXT,
                    content=(
                        "The versioning test anchor describes the silver atrium clock and "
                        "keeps at least one approved document available during archive tests."
                    ),
                )
                target, version_one = await management.create_document(
                    admin_id=admin_id,
                    title="Mixed stay requirements",
                    language="ar",
                    source_format=SourceFormat.PLAIN_TEXT,
                    content=(
                        "تتطلب الإقامة المشتركة لشخصين غير متزوجين إبراز وثائق الهوية "
                        "المعتمدة عند تسجيل الوصول وفق سياسة الفندق المنشورة."
                    ),
                )
                document_ids.extend((anchor.id, target.id))
                await management.approve_revision(
                    admin_id=admin_id,
                    document_id=anchor.id,
                    revision_id=anchor_revision.id,
                )
                await management.approve_revision(
                    admin_id=admin_id,
                    document_id=target.id,
                    revision_id=version_one.id,
                )

            with TemporaryDirectory() as temp_dir:
                store = FaissIndexStore(Path(temp_dir))

                async def rebuild() -> tuple[UUID, tuple[UUID, ...]]:
                    async with database.transaction() as session:
                        service = KnowledgeIndexService(
                            SQLAlchemyKnowledgeRepository(session),
                            max_chars=260,
                            overlap_chars=30,
                        )
                        plan = await service.prepare_build(admin_id=admin_id, embedder=embedder)
                        index_ids.append(plan.index.id)
                    materialized = KnowledgeIndexService.materialize_build(
                        plan, embedder=embedder, store=store
                    )
                    async with database.transaction() as session:
                        await KnowledgeIndexService(
                            SQLAlchemyKnowledgeRepository(session)
                        ).activate_build(materialized, store=store)
                    return plan.index.id, tuple(item.revision_id for item in plan.chunks)

                _first_index, first_revisions = await rebuild()
                assert version_one.id in first_revisions

                original_content = version_one.content
                original_checksum = version_one.checksum
                async with database.transaction() as session:
                    management = KnowledgeManagementService(
                        SQLAlchemyKnowledgeRepository(session)
                    )
                    version_two = await management.update_document(
                        admin_id=admin_id,
                        document_id=target.id,
                        content=(
                            "تتطلب الإقامة المشتركة وثائق الهوية الأصلية، ويجب حضور "
                            "الضيفين معاً عند تسجيل الوصول لإتمام التحقق."
                        ),
                    )
                assert version_two.document_id == target.id
                assert version_two.version == 2

                async with database.session() as session:
                    persisted_v1 = await session.get(KnowledgeRevision, version_one.id)
                    assert persisted_v1 is not None
                    assert persisted_v1.content == original_content
                    assert persisted_v1.checksum == original_checksum

                async with database.transaction() as session:
                    draft_plan = await KnowledgeIndexService(
                        SQLAlchemyKnowledgeRepository(session),
                        max_chars=260,
                        overlap_chars=30,
                    ).prepare_build(admin_id=admin_id, embedder=embedder)
                    index_ids.append(draft_plan.index.id)
                    await KnowledgeIndexService(
                        SQLAlchemyKnowledgeRepository(session)
                    ).fail_build(draft_plan.index.id, RuntimeError("draft exclusion probe"))
                draft_revision_ids = {item.revision_id for item in draft_plan.chunks}
                assert version_one.id in draft_revision_ids
                assert version_two.id not in draft_revision_ids

                async with database.transaction() as session:
                    management = KnowledgeManagementService(
                        SQLAlchemyKnowledgeRepository(session)
                    )
                    edited_v2 = await management.edit_draft_revision(
                        admin_id=admin_id,
                        document_id=target.id,
                        revision_id=version_two.id,
                        content=(
                            "تتطلب الإقامة المشتركة وثائق الهوية الأصلية، ويجب حضور "
                            "الضيفين معاً عند تسجيل الوصول. لا تحدد المعلومات المعتمدة عقوبة."
                        ),
                    )
                    await management.approve_revision(
                        admin_id=admin_id,
                        document_id=target.id,
                        revision_id=edited_v2.id,
                    )

                second_index, second_revisions = await rebuild()
                assert version_two.id in second_revisions
                assert version_one.id not in second_revisions
                async with database.session() as session:
                    target_chunk_revisions = set(
                        await session.scalars(
                            select(KnowledgeChunk.revision_id)
                            .join(
                                KnowledgeRevision,
                                KnowledgeRevision.id == KnowledgeChunk.revision_id,
                            )
                            .where(
                                KnowledgeChunk.index_version_id == second_index,
                                KnowledgeRevision.document_id == target.id,
                            )
                        )
                    )
                    detail = await SQLAlchemyAdminRepository(session).get_knowledge(target.id)
                assert target_chunk_revisions == {version_two.id}
                assert detail.retrieval_eligible is True
                assert detail.faiss_sync_status == "synchronized"
                assert {item.status for item in detail.revisions} == {"approved", "historical"}

                async with database.transaction() as session:
                    await KnowledgeManagementService(
                        SQLAlchemyKnowledgeRepository(session)
                    ).archive_document(admin_id=admin_id, document_id=target.id)
                async with database.session() as session:
                    archived_active = await SQLAlchemyKnowledgeRepository(session).get_active_index()
                    archived_detail = await SQLAlchemyAdminRepository(session).get_knowledge(target.id)
                assert archived_active is not None
                assert all(
                    UUID(str(chunk.metadata["document_id"])) != target.id
                    for chunk in archived_active[1]
                )
                assert archived_detail.retrieval_eligible is False
                assert archived_detail.faiss_sync_status == "needs_rebuild"

                archive_index, archive_revisions = await rebuild()
                assert version_one.id not in archive_revisions
                assert version_two.id not in archive_revisions
                async with database.session() as session:
                    archived_vectors = await session.scalar(
                        select(KnowledgeChunk.id)
                        .join(KnowledgeRevision, KnowledgeRevision.id == KnowledgeChunk.revision_id)
                        .where(
                            KnowledgeChunk.index_version_id == archive_index,
                            KnowledgeRevision.document_id == target.id,
                        )
                        .limit(1)
                    )
                    archived_detail = await SQLAlchemyAdminRepository(session).get_knowledge(target.id)
                assert archived_vectors is None
                assert archived_detail.faiss_sync_status == "synchronized"

                async with database.transaction() as session:
                    restored = await KnowledgeManagementService(
                        SQLAlchemyKnowledgeRepository(session)
                    ).restore_document(admin_id=admin_id, document_id=target.id)
                assert restored.id == target.id
                assert restored.current_revision_id == version_two.id
                async with database.session() as session:
                    restored_detail = await SQLAlchemyAdminRepository(session).get_knowledge(target.id)
                assert {item.id for item in restored_detail.revisions} == {
                    version_one.id,
                    version_two.id,
                }
                assert restored_detail.retrieval_eligible is False
                assert restored_detail.faiss_sync_status == "needs_rebuild"

                _restore_index, restored_revisions = await rebuild()
                assert version_two.id in restored_revisions
                async with database.session() as session:
                    restored_detail = await SQLAlchemyAdminRepository(session).get_knowledge(target.id)
                assert restored_detail.retrieval_eligible is True

                async with database.transaction() as session:
                    reactivated = await KnowledgeManagementService(
                        SQLAlchemyKnowledgeRepository(session)
                    ).approve_revision(
                        admin_id=admin_id,
                        document_id=target.id,
                        revision_id=version_one.id,
                    )
                assert reactivated.current_revision_id == version_one.id
                _reactivated_index, reactivated_revisions = await rebuild()
                assert version_one.id in reactivated_revisions
                assert version_two.id not in reactivated_revisions

                async with database.transaction() as session:
                    management = KnowledgeManagementService(
                        SQLAlchemyKnowledgeRepository(session)
                    )
                    future, future_revision = await management.create_document(
                        admin_id=admin_id,
                        title="Indigo lantern quiet-hours protocol",
                        language="en",
                        source_format=SourceFormat.PLAIN_TEXT,
                        content=(
                            "The indigo lantern quiet-hours protocol allows lobby lantern "
                            "loans after 22:00. Every indigo lantern must be returned before "
                            "06:00 at the concierge desk."
                        ),
                    )
                    document_ids.append(future.id)
                    await management.approve_revision(
                        admin_id=admin_id,
                        document_id=future.id,
                        revision_id=future_revision.id,
                    )
                _future_index, future_revisions = await rebuild()
                assert future_revision.id in future_revisions
                async with database.session() as session:
                    retrieval = KnowledgeRetrievalService(
                        SQLAlchemyKnowledgeRepository(session),
                        embedder,
                        store,
                        minimum_score=0.05,
                    )
                    first_question = await retrieval.retrieve(
                        "Can I borrow an indigo lantern late at night?"
                    )
                    second_question = await retrieval.retrieve(
                        "Where must an indigo lantern be returned before morning?"
                    )
                for result in (first_question, second_question):
                    matched = next(
                        evidence for evidence in result.evidence
                        if evidence.document_id == future.id
                    )
                    assert matched.revision_id == future_revision.id
                    assert matched.revision_version == 1
                    assert matched.metadata["document_id"] == str(future.id)
                    assert matched.metadata["revision_version"] == 1
        finally:
            async with database.transaction() as session:
                if index_ids:
                    await session.execute(
                        delete(KnowledgeChunk).where(KnowledgeChunk.index_version_id.in_(index_ids))
                    )
                    await session.execute(delete(IndexVersion).where(IndexVersion.id.in_(index_ids)))
                if document_ids:
                    revision_ids = (
                        await session.scalars(
                            select(KnowledgeRevision.id).where(
                                KnowledgeRevision.document_id.in_(document_ids)
                            )
                        )
                    ).all()
                    await session.execute(
                        delete(KnowledgeDocument).where(KnowledgeDocument.id.in_(document_ids))
                    )
                    if revision_ids:
                        await session.execute(
                            delete(KnowledgeRevision).where(KnowledgeRevision.id.in_(revision_ids))
                        )
                await session.execute(delete(AuditEvent).where(AuditEvent.actor_id == admin_id))
                await session.execute(delete(AdminUser).where(AdminUser.id == admin_id))
            await database.dispose()

    asyncio.run(exercise())
