"""Pinned Sentence Transformer + FAISS acceptance for the production airport route."""

import asyncio
import hashlib
import os
from datetime import UTC, datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from uuid import UUID, uuid4

import pytest
from pydantic import SecretStr
from sqlalchemy import delete, select, update

from hotel_bot.application.guest_flows import extract_parameters
from hotel_bot.application.hotel_operations import HotelOperationsService
from hotel_bot.application.hotel_tools import build_hotel_tool_registry
from hotel_bot.application.knowledge import (
    KnowledgeIndexService,
    KnowledgeManagementService,
    KnowledgeRetrievalService,
)
from hotel_bot.application.llm import AuditedLLMService, HybridOrchestrator
from hotel_bot.application.prompts import PromptFactory
from hotel_bot.application.tools import ControlledToolExecutor
from hotel_bot.core.config import Settings
from hotel_bot.domain.conversation.enums import MessageDirection
from hotel_bot.domain.conversation.models import (
    ContextEnvelope,
    ConversationState,
    MessageSnapshot,
)
from hotel_bot.domain.intent.classifier import ALGORITHM_VERSION, NaiveBayesIntentClassifier
from hotel_bot.domain.intent.enums import DatasetSplit, IntentCode, RoutingDecision
from hotel_bot.domain.intent.models import RoutingResult, SupportedLanguage
from hotel_bot.domain.intent.routing import SafeIntentRouter
from hotel_bot.domain.knowledge.enums import SourceFormat
from hotel_bot.domain.llm.enums import AnswerBasis
from hotel_bot.domain.llm.models import OrchestrationResult
from hotel_bot.infrastructure.database import DatabaseManager
from hotel_bot.infrastructure.embeddings import SentenceTransformerEmbeddingProvider
from hotel_bot.infrastructure.faiss_store import FaissIndexStore
from hotel_bot.infrastructure.gemini import GeminiAdapter
from hotel_bot.infrastructure.intent_dataset import load_intent_dataset
from hotel_bot.infrastructure.repositories.hotel_operations import (
    SQLAlchemyHotelOperationsRepository,
)
from hotel_bot.infrastructure.repositories.knowledge import SQLAlchemyKnowledgeRepository
from hotel_bot.infrastructure.repositories.llm_runs import SQLAlchemyLLMRunRepository
from hotel_bot.infrastructure.repositories.tool_audit import SQLAlchemyToolAuditRepository
from hotel_bot.knowledge.seeder import KnowledgeSeeder
from hotel_bot.persistence.enums import (
    AdminRole,
    AdminStatus,
    ConversationStatus,
)
from hotel_bot.persistence.models import (
    AdminUser,
    AuditEvent,
    Conversation,
    Guest,
    IndexVersion,
    KnowledgeChunk,
    KnowledgeDocument,
    KnowledgeRevision,
    LLMRun,
    Message,
    ToolExecution,
)
from hotel_bot.seed.loader import HotelSeeder

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        os.getenv("RUN_PRODUCTION_RAG") != "1",
        reason=(
            "set RUN_PRODUCTION_RAG=1 with MySQL and the pinned "
            "Sentence Transformer model cache available"
        ),
    ),
]

ENGLISH_QUERY = (
    "Does the hotel offer airport pick-up services from Damascus International "
    "Airport, and how far in advance do I need to book?"
)
ARABIC_QUERY = "هل يوفر الفندق خدمة نقل من مطار دمشق وكم يلزم الحجز مسبقاً؟"
POLICY_TITLE = "قبول حجز الغرف المختلطة"
POLICY_CONTENT = (
    "يسمح الفندق بحجز غرفة مشتركة لرجل وامرأة فقط عند إبراز وثيقة زواج رسمية "
    "سارية عند تسجيل الوصول. يجب أن تتطابق أسماء النزلاء مع وثيقة الزواج "
    "وهويات النزلاء. لا تحدد المعلومات المعتمدة عقوبة أو غرامة أو إجراءً عند "
    "عدم تقديم الوثيقة."
)
POLICY_QUERIES = (
    "أنا وخطيبتي بدنا غرفة وحدة، شو المطلوب؟",
    "هل تسمحون بحجز غرفة لشاب وفتاة غير متزوجين؟",
    "هل يلزم إبراز وثيقة زواج لحجز غرفة مشتركة؟",
    "شو العقوبة إذا حجزنا بدون وثيقة زواج؟",
)
FUTURE_TITLE = "إعارة مستلزمات الطقس للنزلاء"
FUTURE_CONTENT = (
    "يمكن للنزيل استعارة مظلة من مكتب خدمة الضيوف بين الساعة السادسة صباحاً "
    "والعاشرة مساءً. يلزم إبراز بطاقة الغرفة، وتُعاد المظلة قبل تسجيل المغادرة."
)
FUTURE_QUERIES = (
    "إذا كان الجو ماطراً، من أين أحصل على شيء يحميني من المطر ومتى؟",
    "هل أستطيع أخذ مظلة خارج الفندق وما الذي يجب أن أبرزه؟",
)
AVAILABILITY_QUERY = "أريد غرفة من 2026-08-10 إلى 2026-08-12 لشخصين"
BOOKING_QUERY = "أريد متابعة الحجز BKG-2026-0001"
GEMINI_FREE_TIER_PACING_SECONDS = 31


def settings() -> Settings:
    project_root = Path(__file__).resolve().parents[3]
    env_path = project_root / ".env"
    values = {
        key: value
        for line in (
            env_path.read_text(encoding="utf-8").splitlines()
            if env_path.is_file()
            else ()
        )
        if line and not line.lstrip().startswith("#") and "=" in line
        for key, value in [line.split("=", maxsplit=1)]
    }
    return Settings(
        APP_ENVIRONMENT="test",
        DB_HOST=os.getenv("DB_HOST", values.get("DB_HOST", "127.0.0.1")),
        DB_PORT=int(os.getenv("DB_PORT", values.get("DB_PORT", "3307"))),
        DB_NAME=os.getenv("DB_NAME", values.get("DB_NAME", "hotel_bot")),
        DB_USER=os.getenv("DB_USER", values.get("DB_USER", "hotel_bot")),
        DB_PASSWORD=SecretStr(
            os.getenv(
                "DB_PASSWORD",
                values.get("DB_PASSWORD", "hotel_bot_local_password"),
            )
        ),
        EMBEDDING_PROVIDER="sentence_transformers",
        EMBEDDING_CACHE_PATH=os.getenv(
            "EMBEDDING_CACHE_PATH",
            values.get("EMBEDDING_CACHE_PATH", "backend/data/models"),
        ),
        GEMINI_API_KEY=SecretStr(
            os.getenv("GEMINI_API_KEY", values.get("GEMINI_API_KEY", ""))
        ),
        GEMINI_MODEL=os.getenv(
            "GEMINI_MODEL",
            values.get("GEMINI_MODEL", "gemini-3.5-flash"),
        ),
        _env_file=None,
    )  # type: ignore[call-arg]


def router() -> SafeIntentRouter:
    path = (
        Path(__file__).resolve().parents[2]
        / "src"
        / "hotel_bot"
        / "intent"
        / "data"
        / "intent-dataset-v1.json"
    )
    loaded = load_intent_dataset(path)
    classifier = NaiveBayesIntentClassifier(
        classifier_version=f"{ALGORITHM_VERSION}+production-rag"
    )
    classifier.fit(
        sample
        for sample in loaded.dataset.samples
        if sample.split is DatasetSplit.TRAIN
    )
    return SafeIntentRouter(classifier)


def test_dynamic_knowledge_routing_uses_real_router_lifecycle_faiss_and_gemini() -> None:
    async def exercise() -> None:
        config = settings()
        database = DatabaseManager(config)
        admin_id = uuid4()
        index_id: UUID | None = None
        previous_active: tuple[UUID, ...] = ()
        document_ids: list[UUID] = []
        trace_ids: list[tuple[UUID, UUID, UUID]] = []
        gemini: GeminiAdapter | None = None
        try:
            async with database.transaction() as session:
                session.add(
                    AdminUser(
                        id=admin_id,
                        email=f"rag-{admin_id.hex}@example.invalid",
                        username=f"rag_{admin_id.hex[:16]}",
                        password_hash="test-only-not-a-real-credential",
                        role=AdminRole.ADMIN,
                        status=AdminStatus.ACTIVE,
                    )
                )
                await KnowledgeSeeder(session).seed()
                await HotelSeeder(session).seed()
                previous_active = tuple(
                    await session.scalars(
                        select(IndexVersion.id).where(
                            IndexVersion.status == "active"
                        )
                    )
                )

            async with database.transaction() as session:
                management = KnowledgeManagementService(
                    SQLAlchemyKnowledgeRepository(session)
                )
                for title, content in (
                    (POLICY_TITLE, POLICY_CONTENT),
                    (FUTURE_TITLE, FUTURE_CONTENT),
                ):
                    document, revision = await management.create_document(
                        admin_id=admin_id,
                        title=title,
                        language="ar",
                        source_format=SourceFormat.PLAIN_TEXT,
                        content=content,
                    )
                    document_ids.append(document.id)
                    await management.approve_revision(
                        admin_id=admin_id,
                        document_id=document.id,
                        revision_id=revision.id,
                    )

            embedder = SentenceTransformerEmbeddingProvider(
                model_name=config.embedding_model,
                revision=config.embedding_model_revision,
                expected_dimension=config.embedding_dimension,
                batch_size=config.embedding_batch_size,
                cache_path=config.embedding_cache_path,
            )
            if config.gemini_api_key is None:
                pytest.fail("GEMINI_API_KEY is required for production RAG acceptance")
            gemini = GeminiAdapter(
                api_key=config.gemini_api_key.get_secret_value(),
                model=config.gemini_model,
                timeout_ms=config.gemini_timeout_ms,
                retry_attempts=config.gemini_retry_attempts,
            )
            with TemporaryDirectory() as temporary_directory:
                store = FaissIndexStore(Path(temporary_directory))
                async with database.transaction() as session:
                    service = KnowledgeIndexService(
                        SQLAlchemyKnowledgeRepository(session),
                        max_chars=config.knowledge_chunk_max_chars,
                        overlap_chars=config.knowledge_chunk_overlap_chars,
                    )
                    plan = await service.prepare_build(
                        admin_id=admin_id,
                        embedder=embedder,
                    )
                    index_id = plan.index.id
                materialized = KnowledgeIndexService.materialize_build(
                    plan,
                    embedder=embedder,
                    store=store,
                )
                async with database.transaction() as session:
                    await KnowledgeIndexService(
                        SQLAlchemyKnowledgeRepository(session)
                    ).activate_build(materialized, store=store)

                production_router = router()
                async def run_message(
                    query: str,
                    *,
                    language: SupportedLanguage,
                    expected_titles: set[str] | None = None,
                    expected_evidence_markers: tuple[str, ...] = (),
                    parameters: dict[str, object] | None = None,
                ) -> tuple[RoutingResult, OrchestrationResult]:
                    expects_knowledge = (
                        expected_titles is not None
                        or bool(expected_evidence_markers)
                    )
                    routing = production_router.route(
                        query,
                        language,
                        parameters=parameters,
                    )
                    guest_id = uuid4()
                    conversation_id = uuid4()
                    message_id = uuid4()
                    trace_ids.append((guest_id, conversation_id, message_id))
                    correlation_id = f"production-rag-{message_id.hex}"
                    async with database.transaction() as session:
                        session.add(
                            Guest(
                                id=guest_id,
                                telegram_user_hash=hashlib.sha256(
                                    f"production-rag:{guest_id}".encode()
                                ).hexdigest(),
                                preferred_language=language,
                            )
                        )
                        await session.flush()
                        session.add(
                            Conversation(
                                id=conversation_id,
                                guest_id=guest_id,
                                channel="integration_test",
                                status=ConversationStatus.OPEN,
                                language=language,
                            )
                        )
                        await session.flush()
                        session.add(
                            Message(
                                id=message_id,
                                conversation_id=conversation_id,
                                sequence_number=1,
                                direction=MessageDirection.INBOUND,
                                text=query,
                                language=language,
                                correlation_id=correlation_id,
                            )
                        )
                        await session.flush()
                        retrieval = KnowledgeRetrievalService(
                            SQLAlchemyKnowledgeRepository(session),
                            embedder,
                            store,
                            top_k=config.retrieval_top_k,
                            minimum_score=config.retrieval_min_score,
                        )
                        registry = build_hotel_tool_registry(
                            HotelOperationsService(
                                SQLAlchemyHotelOperationsRepository(session)
                            )
                        )
                        orchestrator = HybridOrchestrator(
                            llm=AuditedLLMService(
                                gemini,
                                SQLAlchemyLLMRunRepository(session),
                            ),
                            retrieval=retrieval,
                            registry=registry,
                            tool_executor=ControlledToolExecutor(
                                registry,
                                SQLAlchemyToolAuditRepository(session),
                            ),
                            prompt_factory=PromptFactory(),
                            max_tokens_per_turn=10_000,
                            max_cost_usd_per_turn=1.0,
                            input_usd_per_million=0.0,
                            output_usd_per_million=0.0,
                        )
                        context = ContextEnvelope(
                            state=ConversationState(language=language),
                            current_message=MessageSnapshot(
                                id=message_id,
                                conversation_id=conversation_id,
                                sequence_number=1,
                                direction=MessageDirection.INBOUND,
                                text=query,
                                language=language,
                                correlation_id=correlation_id,
                                created_at=datetime.now(UTC).replace(
                                    tzinfo=None
                                ),
                            ),
                            turns=(),
                            evidence=(),
                            summary=None,
                            estimated_tokens=40,
                            truncated=False,
                        )
                        answer = await orchestrator.handle(
                            context,
                            routing,
                            trusted_tool_arguments=parameters,
                        )
                        if expects_knowledge:
                            cited_chunk_ids = tuple(
                                UUID(item)
                                for item in answer.answer.evidence_ids
                            )
                            assert answer.answer.basis is AnswerBasis.KNOWLEDGE
                            assert answer.answer.escalation is False
                            assert answer.tool_executed is False
                            assert cited_chunk_ids
                            cited_chunks = (
                                await session.scalars(
                                    select(KnowledgeChunk).where(
                                        KnowledgeChunk.id.in_(cited_chunk_ids)
                                    )
                                )
                            ).all()
                            assert any(
                                (
                                    expected_titles is not None
                                    and str(
                                        (
                                            chunk.metadata_json
                                            or {}
                                        ).get("title")
                                    )
                                    in expected_titles
                                )
                                or (
                                    expected_evidence_markers
                                    and all(
                                        marker in chunk.text
                                        for marker in (
                                            expected_evidence_markers
                                        )
                                    )
                                )
                                for chunk in cited_chunks
                            ), [
                                (
                                    (chunk.metadata_json or {}).get("title"),
                                    chunk.text,
                                )
                                for chunk in cited_chunks
                            ]
                        llm_runs = (
                            await session.scalars(
                                select(LLMRun).where(
                                    LLMRun.message_id == message_id
                                )
                            )
                        ).all()
                        assert llm_runs
                        assert all(item.status == "succeeded" for item in llm_runs)
                        assert all(
                            item.provider == "google_gemini"
                            for item in llm_runs
                        )
                        tool_count = await session.scalar(
                            select(ToolExecution.id)
                            .where(
                                ToolExecution.correlation_id == correlation_id
                            )
                            .limit(1)
                        )
                        if expects_knowledge:
                            assert tool_count is None
                        else:
                            assert tool_count is not None
                    await asyncio.sleep(GEMINI_FREE_TIER_PACING_SECONDS)
                    return routing, answer

                policy_answers = []
                for query in POLICY_QUERIES:
                    routing, answer = await run_message(
                        query,
                        language="ar",
                        expected_titles={POLICY_TITLE},
                        expected_evidence_markers=("وثيقة زواج",),
                    )
                    assert routing.prediction.intent is IntentCode.HOTEL_INFO
                    assert routing.decision is RoutingDecision.KNOWLEDGE_CANDIDATE
                    assert answer.answer.language == "ar"
                    assert "وثيقة زواج" in answer.answer.text
                    policy_answers.append(answer.answer.text)

                penalty_answer = policy_answers[-1]
                assert any(
                    marker in penalty_answer
                    for marker in (
                        "لا تحدد",
                        "لم تحدد",
                        "غير محدد",
                        "غير مذكور",
                        "لا تذكر",
                    )
                )
                assert all(
                    unsupported not in penalty_answer
                    for unsupported in (
                        "الشرطة",
                        "السجن",
                        "إلغاء الحجز",
                    )
                )

                airport_routing, airport_answer = await run_message(
                    ARABIC_QUERY,
                    language="ar",
                    expected_titles={
                        "Airport transfer",
                        "النقل من وإلى المطار",
                    },
                )
                assert airport_routing.decision is RoutingDecision.KNOWLEDGE_CANDIDATE
                assert airport_answer.answer.language == "ar"
                assert any(
                    marker in airport_answer.answer.text
                    for marker in ("24", "٢٤", "أربع وعشرين")
                )

                for query in FUTURE_QUERIES:
                    future_routing, future_answer = await run_message(
                        query,
                        language="ar",
                        expected_titles={FUTURE_TITLE},
                    )
                    assert future_routing.prediction.intent is IntentCode.HOTEL_INFO
                    assert (
                        future_routing.decision
                        is RoutingDecision.KNOWLEDGE_CANDIDATE
                    )
                    assert future_answer.answer.language == "ar"
                    assert any(
                        marker in future_answer.answer.text
                        for marker in (
                            "بطاقة الغرفة",
                            "مكتب خدمة الضيوف",
                            "السادسة",
                        )
                    )

                availability_parameters = extract_parameters(
                    AVAILABILITY_QUERY,
                    ConversationState(language="ar"),
                    idempotency_seed="production-availability",
                )
                availability_routing, availability_answer = await run_message(
                    AVAILABILITY_QUERY,
                    language="ar",
                    parameters={
                        key: availability_parameters[key]
                        for key in (
                            "check_in",
                            "check_out",
                            "adults",
                            "children",
                        )
                    },
                )
                assert (
                    availability_routing.prediction.intent
                    is IntentCode.ROOM_AVAILABILITY
                )
                assert (
                    availability_routing.decision
                    is RoutingDecision.ACTION_CANDIDATE
                )
                assert availability_answer.tool_executed is True
                assert availability_answer.answer.basis is AnswerBasis.TOOL

                booking_parameters = extract_parameters(
                    BOOKING_QUERY,
                    ConversationState(language="ar"),
                    idempotency_seed="production-booking",
                )
                booking_routing = production_router.route(
                    BOOKING_QUERY,
                    "ar",
                    parameters=booking_parameters,
                )
                assert booking_routing.prediction.intent is IntentCode.BOOKING_LOOKUP
                assert booking_routing.decision is RoutingDecision.CLARIFY
        finally:
            if gemini is not None:
                await gemini.close()
            async with database.transaction() as session:
                message_ids = [item[2] for item in trace_ids]
                conversation_ids = [item[1] for item in trace_ids]
                guest_ids = [item[0] for item in trace_ids]
                if message_ids:
                    await session.execute(
                        delete(LLMRun).where(LLMRun.message_id.in_(message_ids))
                    )
                    await session.execute(
                        delete(ToolExecution).where(
                            ToolExecution.message_id.in_(message_ids)
                        )
                    )
                    await session.execute(
                        delete(Message).where(Message.id.in_(message_ids))
                    )
                    await session.execute(
                        delete(Conversation).where(
                            Conversation.id.in_(conversation_ids)
                        )
                    )
                    await session.execute(
                        delete(Guest).where(Guest.id.in_(guest_ids))
                    )
                if index_id is not None:
                    await session.execute(
                        delete(KnowledgeChunk).where(
                            KnowledgeChunk.index_version_id == index_id
                        )
                    )
                    await session.execute(
                        delete(IndexVersion).where(IndexVersion.id == index_id)
                    )
                if previous_active:
                    await session.execute(
                        update(IndexVersion)
                        .where(IndexVersion.id.in_(previous_active))
                        .values(status="active")
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
                        delete(KnowledgeDocument).where(
                            KnowledgeDocument.id.in_(document_ids)
                        )
                    )
                    if revision_ids:
                        await session.execute(
                            delete(KnowledgeRevision).where(
                                KnowledgeRevision.id.in_(revision_ids)
                            )
                        )
                await session.execute(
                    delete(AuditEvent).where(AuditEvent.actor_id == admin_id)
                )
                await session.execute(
                    delete(AdminUser).where(AdminUser.id == admin_id)
                )
            await database.dispose()

    asyncio.run(exercise())
