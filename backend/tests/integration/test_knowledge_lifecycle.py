"""Real-MySQL approval, safe activation, retrieval, and failed-build isolation tests."""

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
from hotel_bot.domain.knowledge.enums import IndexStatus, SourceFormat
from hotel_bot.infrastructure.database import DatabaseManager
from hotel_bot.infrastructure.embeddings import HashingEmbeddingProvider
from hotel_bot.infrastructure.faiss_store import FaissIndexStore
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


def test_approved_revisions_activate_atomically_and_failed_build_keeps_active() -> None:
    async def exercise() -> None:
        database = DatabaseManager(mysql_settings())
        admin_id = uuid4()
        document_ids: list[UUID] = []
        index_ids: list[UUID] = []
        try:
            async with database.transaction() as session:
                session.add(
                    AdminUser(
                        id=admin_id,
                        email=f"knowledge-{admin_id.hex}@example.invalid",
                        username=f"knowledge-{admin_id.hex[:16]}",
                        password_hash="test-only-not-a-real-credential",
                        role=AdminRole.ADMIN,
                        status=AdminStatus.ACTIVE,
                    )
                )

            async with database.transaction() as session:
                service = KnowledgeManagementService(SQLAlchemyKnowledgeRepository(session))
                document, revision = await service.create_document(
                    admin_id=admin_id,
                    title="Airport transfer",
                    language="en",
                    source_format=SourceFormat.PLAIN_TEXT,
                    content=(
                        "Private transfers between Damascus International Airport and the "
                        "hotel can be arranged at least 24 hours in advance. The service is "
                        "chargeable and requires the flight number, arrival time, and "
                        "passenger count. The driver meets guests in the public arrivals hall."
                    ),
                )
                document_ids.append(document.id)
                await service.approve_revision(
                    admin_id=admin_id,
                    document_id=document.id,
                    revision_id=revision.id,
                )

            embedder = HashingEmbeddingProvider(dimension=384)
            with TemporaryDirectory() as temp_dir:
                store = FaissIndexStore(Path(temp_dir))
                async with database.transaction() as session:
                    index_service = KnowledgeIndexService(
                        SQLAlchemyKnowledgeRepository(session), max_chars=200, overlap_chars=30
                    )
                    plan = await index_service.prepare_build(admin_id=admin_id, embedder=embedder)
                    index_ids.append(plan.index.id)
                materialization = KnowledgeIndexService.materialize_build(
                    plan, embedder=embedder, store=store
                )
                async with database.transaction() as session:
                    active = await KnowledgeIndexService(
                        SQLAlchemyKnowledgeRepository(session)
                    ).activate_build(materialization, store=store)
                assert active.status is IndexStatus.ACTIVE

                async with database.session() as session:
                    result = await KnowledgeRetrievalService(
                        SQLAlchemyKnowledgeRepository(session),
                        embedder,
                        store,
                        minimum_score=0.05,
                    ).retrieve(
                        "Does the hotel offer airport pick-up services from Damascus "
                        "International Airport, and how far in advance do I need to book?"
                    )
                assert result.sufficient is True
                assert result.index_version_id == active.id
                airport_evidence = next(
                    item
                    for item in result.evidence
                    if item.title == "Airport transfer"
                    and "at least 24 hours in advance" in item.text
                )
                assert airport_evidence.document_id
                assert airport_evidence.revision_id

                async with database.transaction() as session:
                    failed_service = KnowledgeIndexService(
                        SQLAlchemyKnowledgeRepository(session), max_chars=200, overlap_chars=30
                    )
                    failed_plan = await failed_service.prepare_build(
                        admin_id=admin_id, embedder=embedder
                    )
                    index_ids.append(failed_plan.index.id)
                async with database.transaction() as session:
                    failed = await KnowledgeIndexService(
                        SQLAlchemyKnowledgeRepository(session)
                    ).fail_build(failed_plan.index.id, RuntimeError("simulated build failure"))
                assert failed.status is IndexStatus.FAILED

                async with database.session() as session:
                    still_active = await SQLAlchemyKnowledgeRepository(session).get_active_index()
                assert still_active is not None
                assert still_active[0].id == active.id
        finally:
            async with database.transaction() as session:
                if index_ids:
                    await session.execute(
                        delete(KnowledgeChunk).where(KnowledgeChunk.index_version_id.in_(index_ids))
                    )
                    await session.execute(
                        delete(IndexVersion).where(IndexVersion.id.in_(index_ids))
                    )
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
