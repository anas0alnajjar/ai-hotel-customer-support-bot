"""MySQL-backed Telegram idempotency, language preference, and confirmation journey."""

import asyncio
import os
from collections.abc import Mapping
from pathlib import Path
from typing import cast

import pytest
from pydantic import SecretStr
from sqlalchemy import delete, select

from hotel_bot.application.conversations import ConversationService
from hotel_bot.application.guest_flows import HotelGuestProcessor
from hotel_bot.application.intent_routing import IntentRoutingService
from hotel_bot.application.llm import HybridOrchestrator
from hotel_bot.application.telegram import telegram_identity_hash
from hotel_bot.core.config import Settings
from hotel_bot.domain.conversation.models import ContextEnvelope, SupportedLanguage
from hotel_bot.domain.intent.classifier import ALGORITHM_VERSION, NaiveBayesIntentClassifier
from hotel_bot.domain.intent.enums import DatasetSplit
from hotel_bot.domain.intent.models import RoutingResult
from hotel_bot.domain.intent.routing import SafeIntentRouter
from hotel_bot.domain.llm.enums import AnswerBasis
from hotel_bot.domain.llm.models import GroundedAnswer, OrchestrationResult
from hotel_bot.domain.telegram.models import TelegramGuestReply, TelegramInboundMessage
from hotel_bot.infrastructure.database import DatabaseManager
from hotel_bot.infrastructure.intent_dataset import load_intent_dataset
from hotel_bot.infrastructure.repositories.conversations import SQLAlchemyConversationRepository
from hotel_bot.infrastructure.repositories.intent_routing import (
    SQLAlchemyIntentClassificationRepository,
)
from hotel_bot.persistence import ChannelUpdate, Conversation, Guest

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        os.getenv("RUN_MYSQL_INTEGRATION") != "1",
        reason="set RUN_MYSQL_INTEGRATION=1 with the project MySQL container running",
    ),
]

PEPPER = "telegram-integration-pepper-00000001"
USER_ID = 987654321012


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


def classifier() -> SafeIntentRouter:
    path = (
        Path(__file__).resolve().parents[2]
        / "src"
        / "hotel_bot"
        / "intent"
        / "data"
        / "intent-dataset-v1.json"
    )
    loaded = load_intent_dataset(path)
    model = NaiveBayesIntentClassifier(
        classifier_version=f"{ALGORITHM_VERSION}+telegram-integration"
    )
    model.fit(sample for sample in loaded.dataset.samples if sample.split is DatasetSplit.TRAIN)
    return SafeIntentRouter(model)


class RecordingOrchestrator:
    def __init__(self) -> None:
        self.calls: list[tuple[RoutingResult, bool, Mapping[str, object] | None]] = []

    async def handle(
        self,
        context: ContextEnvelope,
        routing: RoutingResult,
        *,
        confirmed: bool = False,
        trusted_tool_arguments: Mapping[str, object] | None = None,
    ) -> OrchestrationResult:
        self.calls.append((routing, confirmed, trusted_tool_arguments))
        if routing.requires_confirmation and not confirmed:
            text = "يرجى التأكيد." if context.state.language == "ar" else "Please confirm."
            return OrchestrationResult(
                answer=GroundedAnswer(
                    language=context.state.language,
                    text=text,
                    basis=AnswerBasis.CONTROLLED,
                ),
                reason_code="confirmation_required",
            )
        if confirmed:
            return OrchestrationResult(
                answer=GroundedAnswer(
                    language=context.state.language,
                    text="تم إنشاء الطلب.",
                    basis=AnswerBasis.TOOL,
                    tool_names=("create_room_service_request",),
                ),
                tool_executed=True,
                model_used=True,
                reason_code="validated_tool_answer",
            )
        text = "أهلاً بك" if context.state.language == "ar" else "Welcome"
        return OrchestrationResult(
            answer=GroundedAnswer(
                language=context.state.language,
                text=text,
                basis=AnswerBasis.CONTROLLED,
            ),
            reason_code="controlled_response",
        )


def message(
    update_id: int, text: str, *, language: SupportedLanguage = "en"
) -> TelegramInboundMessage:
    return TelegramInboundMessage(
        update_id=str(update_id),
        chat_id=USER_ID,
        user_id=USER_ID,
        message_id=update_id,
        text=text,
        language=language,
        command=("start" if text == "/start" else "language_ar" if text == "/ar" else None),
    )


async def remove_guest(manager: DatabaseManager) -> None:
    guest_hash = telegram_identity_hash(USER_ID, PEPPER)
    async with manager.transaction() as session:
        guest_id = await session.scalar(
            select(Guest.id).where(Guest.telegram_user_hash == guest_hash)
        )
        if guest_id is not None:
            await session.execute(delete(ChannelUpdate).where(ChannelUpdate.guest_id == guest_id))
            await session.execute(delete(Conversation).where(Conversation.guest_id == guest_id))
            await session.execute(delete(Guest).where(Guest.id == guest_id))


def test_mysql_guest_journey_is_idempotent_bilingual_and_confirmation_gated() -> None:
    async def exercise() -> None:
        manager = DatabaseManager(mysql_settings())
        model = classifier()
        orchestrator = RecordingOrchestrator()

        async def process(inbound: TelegramInboundMessage) -> TelegramGuestReply:
            async with manager.transaction() as session:
                processor = HotelGuestProcessor(
                    conversations=ConversationService(
                        SQLAlchemyConversationRepository(session),
                    ),
                    intents=IntentRoutingService(
                        SQLAlchemyIntentClassificationRepository(session), model
                    ),
                    orchestrator=cast(HybridOrchestrator, orchestrator),
                    identity_pepper=PEPPER,
                )
                return await processor.process(
                    inbound,
                    correlation_id=f"telegram-e2e-{inbound.update_id}",
                )

        try:
            await remove_guest(manager)
            started = await process(message(7001, "/start"))
            replayed = await process(message(7001, "/start"))
            switched = await process(message(7002, "/ar", language="en"))
            greeting = await process(message(7003, "Hello", language="en"))
            proposed = await process(
                message(7004, "Please send extra towels to room 101", language="en")
            )
            confirmed = await process(message(7005, "تأكيد", language="ar"))
            replayed_confirmation = await process(message(7005, "تأكيد", language="ar"))

            assert started.language == "en"
            assert replayed.duplicate is True
            assert replayed.text == started.text
            assert switched.language == "ar"
            assert greeting.language == "ar"
            assert greeting.text == "أهلاً بك"
            assert proposed.text == "يرجى التأكيد."
            assert confirmed.text == "تم إنشاء الطلب."
            assert replayed_confirmation.duplicate is True

            confirmation_call = orchestrator.calls[-1]
            assert confirmation_call[1] is True
            assert confirmation_call[2] is not None
            assert confirmation_call[2]["room_number"] == "101"
            assert confirmation_call[2]["category"] == "amenities"

            async with manager.session() as session:
                conversation = await session.scalar(
                    select(Conversation)
                    .join(Guest, Guest.id == Conversation.guest_id)
                    .where(
                        Guest.telegram_user_hash == telegram_identity_hash(USER_ID, PEPPER),
                        Conversation.status == "open",
                    )
                    .order_by(Conversation.started_at.desc())
                )
                assert conversation is not None
                assert conversation.language == "ar"
                assert conversation.context_state_json is not None
                assert conversation.context_state_json.get("active_workflow") is None
                update_count = len(
                    (
                        await session.scalars(
                            select(ChannelUpdate).where(
                                ChannelUpdate.guest_id == conversation.guest_id
                            )
                        )
                    ).all()
                )
                assert update_count == 5
        finally:
            await remove_guest(manager)
            await manager.dispose()

    asyncio.run(exercise())
