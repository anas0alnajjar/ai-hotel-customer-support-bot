"""Application-lifetime administration support for tokens and safe FAISS rebuilds."""

import asyncio
import logging
from typing import Literal
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from hotel_bot.application.knowledge import KnowledgeIndexService
from hotel_bot.core.config import Settings
from hotel_bot.domain.admin.security import AdminAccessTokenCodec
from hotel_bot.domain.knowledge.models import IndexBuildPlan
from hotel_bot.infrastructure.database import DatabaseManager
from hotel_bot.infrastructure.embeddings import (
    HashingEmbeddingProvider,
    SentenceTransformerEmbeddingProvider,
)
from hotel_bot.infrastructure.faiss_store import FaissIndexStore
from hotel_bot.infrastructure.repositories.knowledge import SQLAlchemyKnowledgeRepository

logger = logging.getLogger(__name__)


class AdminApplicationRuntime:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        secret = (
            settings.admin_token_secret.get_secret_value() if settings.admin_token_secret else None
        )
        self.token_codec = (
            AdminAccessTokenCodec(
                secret,
                lifetime_minutes=settings.admin_access_token_minutes,
            )
            if secret
            else None
        )
        self._embedder = (
            HashingEmbeddingProvider(dimension=settings.embedding_dimension)
            if settings.embedding_provider == "hashing_test"
            else SentenceTransformerEmbeddingProvider(
                model_name=settings.embedding_model,
                revision=settings.embedding_model_revision,
                expected_dimension=settings.embedding_dimension,
                batch_size=settings.embedding_batch_size,
                cache_path=settings.embedding_cache_path,
            )
        )
        self._store = FaissIndexStore(settings.knowledge_index_path)

    @property
    def auth_configured(self) -> bool:
        return self.token_codec is not None

    @property
    def embedding_model_id(self) -> str:
        return self._embedder.model_id

    async def prepare_reindex(self, session: AsyncSession, *, admin_id: UUID) -> IndexBuildPlan:
        return await KnowledgeIndexService(
            SQLAlchemyKnowledgeRepository(session),
            max_chars=self._settings.knowledge_chunk_max_chars,
            overlap_chars=self._settings.knowledge_chunk_overlap_chars,
        ).prepare_build(admin_id=admin_id, embedder=self._embedder)

    async def prepare_knowledge_sync(
        self, session: AsyncSession, *, admin_id: UUID
    ) -> IndexBuildPlan | None:
        repository = SQLAlchemyKnowledgeRepository(session)
        if not await repository.list_approved_revisions():
            await repository.retire_active_indexes(admin_id=admin_id)
            return None
        return await KnowledgeIndexService(
            repository,
            max_chars=self._settings.knowledge_chunk_max_chars,
            overlap_chars=self._settings.knowledge_chunk_overlap_chars,
        ).prepare_build(admin_id=admin_id, embedder=self._embedder)

    async def complete_reindex(self, database: DatabaseManager, plan: IndexBuildPlan) -> None:
        try:
            materialization = await asyncio.to_thread(
                KnowledgeIndexService.materialize_build,
                plan,
                embedder=self._embedder,
                store=self._store,
            )
            async with database.transaction() as session:
                await KnowledgeIndexService(SQLAlchemyKnowledgeRepository(session)).activate_build(
                    materialization, store=self._store
                )
        except Exception as exc:
            logger.exception(
                "Administration knowledge reindex failed",
                extra={"index": str(plan.index.id)},
            )
            try:
                async with database.transaction() as session:
                    await KnowledgeIndexService(SQLAlchemyKnowledgeRepository(session)).fail_build(
                        plan.index.id, exc
                    )
            except Exception:
                logger.exception(
                    "Failed to record administration knowledge reindex failure",
                    extra={"index": str(plan.index.id)},
                )

    async def active_index_status(
        self, session: AsyncSession
    ) -> Literal["ok", "unavailable", "failed"]:
        active = await SQLAlchemyKnowledgeRepository(session).get_active_index()
        if active is None:
            return "unavailable"
        index, _chunks = active
        if index.artifact_path is None or index.checksum is None:
            return "failed"
        try:
            self._store.validate(
                relative_path=index.artifact_path,
                expected_checksum=index.checksum,
            )
        except Exception:
            return "failed"
        return "ok"
