"""Composition root for one Telegram update over application-owned interfaces."""

from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncSession

from hotel_bot.application.conversations import ConversationService
from hotel_bot.application.guest_flows import HotelGuestProcessor
from hotel_bot.application.hotel_operations import HotelOperationsService
from hotel_bot.application.hotel_tools import build_hotel_tool_registry
from hotel_bot.application.intent_routing import IntentRoutingService
from hotel_bot.application.knowledge import KnowledgeRetrievalService
from hotel_bot.application.llm import AuditedLLMService, HybridOrchestrator
from hotel_bot.application.prompts import PromptFactory
from hotel_bot.application.telegram import TelegramWebhookCoordinator
from hotel_bot.application.tools import ControlledToolExecutor
from hotel_bot.core.config import Settings
from hotel_bot.domain.intent.classifier import ALGORITHM_VERSION, NaiveBayesIntentClassifier
from hotel_bot.domain.intent.enums import DatasetSplit
from hotel_bot.domain.intent.routing import SafeIntentRouter
from hotel_bot.domain.telegram.errors import TelegramConfigurationError
from hotel_bot.domain.telegram.models import TelegramUpdate, TelegramWebhookResult
from hotel_bot.infrastructure.embeddings import (
    HashingEmbeddingProvider,
    SentenceTransformerEmbeddingProvider,
)
from hotel_bot.infrastructure.faiss_store import FaissIndexStore
from hotel_bot.infrastructure.gemini import GeminiAdapter
from hotel_bot.infrastructure.intent_dataset import load_intent_dataset
from hotel_bot.infrastructure.repositories.conversations import SQLAlchemyConversationRepository
from hotel_bot.infrastructure.repositories.hotel_operations import (
    SQLAlchemyHotelOperationsRepository,
)
from hotel_bot.infrastructure.repositories.intent_routing import (
    SQLAlchemyIntentClassificationRepository,
)
from hotel_bot.infrastructure.repositories.knowledge import SQLAlchemyKnowledgeRepository
from hotel_bot.infrastructure.repositories.llm_runs import SQLAlchemyLLMRunRepository
from hotel_bot.infrastructure.repositories.tool_audit import SQLAlchemyToolAuditRepository
from hotel_bot.infrastructure.telegram import TelegramBotAPIClient


class TelegramApplicationRuntime:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self.webhook_secret = (
            settings.telegram_webhook_secret.get_secret_value()
            if settings.telegram_webhook_secret
            else None
        )
        self._identity_pepper = (
            settings.telegram_identity_pepper.get_secret_value()
            if settings.telegram_identity_pepper
            else None
        )
        api_key = settings.gemini_api_key.get_secret_value() if settings.gemini_api_key else None
        bot_token = (
            settings.telegram_bot_token.get_secret_value() if settings.telegram_bot_token else None
        )
        self._gemini = (
            GeminiAdapter(
                api_key=api_key,
                model=settings.gemini_model,
                timeout_ms=settings.gemini_timeout_ms,
                retry_attempts=settings.gemini_retry_attempts,
            )
            if api_key
            else None
        )
        self._telegram = (
            TelegramBotAPIClient(
                bot_token=bot_token,
                base_url=settings.telegram_api_base_url,
                timeout_ms=settings.telegram_timeout_ms,
            )
            if bot_token
            else None
        )

        dataset_path = Path(__file__).parents[1] / "intent" / "data" / "intent-dataset-v1.json"
        loaded = load_intent_dataset(dataset_path)
        classifier_version = f"{ALGORITHM_VERSION}+{loaded.sha256[:12]}"
        classifier = NaiveBayesIntentClassifier(classifier_version=classifier_version)
        classifier.fit(
            sample for sample in loaded.dataset.samples if sample.split is DatasetSplit.TRAIN
        )
        self._router = SafeIntentRouter(
            classifier,
            general_confidence_threshold=settings.intent_general_confidence_threshold,
            action_confidence_threshold=settings.intent_action_confidence_threshold,
            confidence_margin_threshold=settings.intent_confidence_margin_threshold,
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
        self._vector_store = FaissIndexStore(settings.knowledge_index_path)

    @property
    def configured(self) -> bool:
        return all(
            (
                self.webhook_secret,
                self._identity_pepper,
                self._gemini,
                self._telegram,
            )
        )

    async def handle(
        self,
        session: AsyncSession,
        update: TelegramUpdate,
        *,
        correlation_id: str,
    ) -> TelegramWebhookResult:
        if (
            not self.configured
            or self._identity_pepper is None
            or self._gemini is None
            or self._telegram is None
        ):
            raise TelegramConfigurationError("Telegram runtime is not configured")
        conversation_repository = SQLAlchemyConversationRepository(session)
        conversations = ConversationService(
            conversation_repository,
            inactivity_minutes=self._settings.conversation_inactivity_minutes,
            context_turns=self._settings.conversation_context_turns,
            context_max_tokens=self._settings.conversation_context_max_tokens,
        )
        intents = IntentRoutingService(
            SQLAlchemyIntentClassificationRepository(session),
            self._router,
        )
        hotel = HotelOperationsService(SQLAlchemyHotelOperationsRepository(session))
        registry = build_hotel_tool_registry(
            hotel,
            read_timeout_ms=self._settings.tool_read_timeout_ms,
            write_timeout_ms=self._settings.tool_write_timeout_ms,
        )
        executor = ControlledToolExecutor(
            registry,
            SQLAlchemyToolAuditRepository(session),
            max_calls_per_turn=self._settings.tool_max_calls_per_turn,
        )
        retrieval = KnowledgeRetrievalService(
            SQLAlchemyKnowledgeRepository(session),
            self._embedder,
            self._vector_store,
            top_k=self._settings.retrieval_top_k,
            minimum_score=self._settings.retrieval_min_score,
        )
        llm = AuditedLLMService(self._gemini, SQLAlchemyLLMRunRepository(session))
        orchestrator = HybridOrchestrator(
            llm=llm,
            retrieval=retrieval,
            registry=registry,
            tool_executor=executor,
            prompt_factory=PromptFactory(max_output_tokens=self._settings.gemini_max_output_tokens),
            max_tokens_per_turn=self._settings.gemini_max_tokens_per_turn,
            max_cost_usd_per_turn=self._settings.gemini_max_estimated_cost_usd_per_turn,
            input_usd_per_million=self._settings.gemini_input_usd_per_million_tokens,
            output_usd_per_million=self._settings.gemini_output_usd_per_million_tokens,
        )
        processor = HotelGuestProcessor(
            conversations=conversations,
            intents=intents,
            orchestrator=orchestrator,
            identity_pepper=self._identity_pepper,
        )
        return await TelegramWebhookCoordinator(processor, self._telegram).handle(
            update,
            correlation_id=correlation_id,
        )

    async def close(self) -> None:
        if self._telegram is not None:
            await self._telegram.close()
        if self._gemini is not None:
            await self._gemini.close()
