"""Production-composed booking and room-service demo journeys over seeded MySQL."""

import asyncio
import os
import re
from pathlib import Path
from uuid import uuid4

import pytest
from pydantic import SecretStr
from sqlalchemy import delete, select

from hotel_bot.application.conversations import ConversationService
from hotel_bot.application.guest_flows import CALLBACK_CONFIRM, HotelGuestProcessor
from hotel_bot.application.hotel_operations import HotelOperationsService
from hotel_bot.application.hotel_tools import build_hotel_tool_registry
from hotel_bot.application.intent_routing import IntentRoutingService
from hotel_bot.application.llm import HybridOrchestrator
from hotel_bot.application.prompts import PromptFactory
from hotel_bot.application.telegram import telegram_identity_hash
from hotel_bot.application.tools import ControlledToolExecutor
from hotel_bot.core.config import Settings
from hotel_bot.domain.intent.classifier import ALGORITHM_VERSION, NaiveBayesIntentClassifier
from hotel_bot.domain.intent.enums import DatasetSplit
from hotel_bot.domain.intent.routing import SafeIntentRouter
from hotel_bot.domain.llm.errors import LLMUnavailableError
from hotel_bot.domain.telegram.models import TelegramInboundCallback, TelegramInboundMessage
from hotel_bot.infrastructure.database import DatabaseManager
from hotel_bot.infrastructure.intent_dataset import load_intent_dataset
from hotel_bot.infrastructure.repositories.conversations import (
    SQLAlchemyConversationRepository,
)
from hotel_bot.infrastructure.repositories.hotel_operations import (
    SQLAlchemyHotelOperationsRepository,
)
from hotel_bot.infrastructure.repositories.intent_routing import (
    SQLAlchemyIntentClassificationRepository,
)
from hotel_bot.infrastructure.repositories.tool_audit import SQLAlchemyToolAuditRepository
from hotel_bot.persistence import (
    ChannelUpdate,
    Conversation,
    Guest,
    Message,
    ServiceRequest,
    ToolExecution,
)

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        os.getenv("RUN_MYSQL_INTEGRATION") != "1",
        reason="set RUN_MYSQL_INTEGRATION=1 with the project MySQL container running",
    ),
]

PEPPER = "demo-acceptance-pepper-00000000000001"


class UnavailableLLM:
    async def generate(self, **_: object) -> None:
        raise LLMUnavailableError("test forces the validated tool fallback")


class UnusedRetrieval:
    async def retrieve(self, _: str) -> None:
        raise AssertionError("hotel actions must not invoke knowledge retrieval")


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


def production_router() -> SafeIntentRouter:
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
        classifier_version=f"{ALGORITHM_VERSION}+demo-acceptance"
    )
    classifier.fit(
        sample
        for sample in loaded.dataset.samples
        if sample.split is DatasetSplit.TRAIN
    )
    return SafeIntentRouter(classifier)


def inbound(user_id: int, update_id: int, text: str) -> TelegramInboundMessage:
    return TelegramInboundMessage(
        update_id=str(update_id),
        chat_id=user_id,
        user_id=user_id,
        message_id=update_id,
        text=text,
        language="ar",
        command="new" if text == "/new" else None,
    )


def callback(user_id: int, update_id: int) -> TelegramInboundCallback:
    return TelegramInboundCallback(
        update_id=str(update_id),
        callback_query_id=f"callback-{update_id}",
        chat_id=user_id,
        user_id=user_id,
        message_id=update_id,
        data=CALLBACK_CONFIRM,
        language="ar",
    )


def test_seeded_booking_and_room_service_journeys_do_not_loop() -> None:
    async def exercise() -> None:
        settings = mysql_settings()
        database = DatabaseManager(settings)
        router = production_router()
        user_ids = (880000001, 880000002, 880000003)
        base = int(uuid4().int % 1_000_000_000)
        tracking_codes: list[str] = []
        hashes = [
            telegram_identity_hash(user_id, PEPPER)
            for user_id in user_ids
        ]

        async def remove_test_guests() -> None:
            async with database.transaction() as session:
                guest_ids = (
                    await session.scalars(
                        select(Guest.id).where(
                            Guest.telegram_user_hash.in_(hashes)
                        )
                    )
                ).all()
                if not guest_ids:
                    return
                await session.execute(
                    delete(ServiceRequest).where(
                        ServiceRequest.requested_by_guest_id.in_(guest_ids)
                    )
                )
                await session.execute(
                    delete(ChannelUpdate).where(
                        ChannelUpdate.guest_id.in_(guest_ids)
                    )
                )
                await session.execute(
                    delete(Conversation).where(
                        Conversation.guest_id.in_(guest_ids)
                    )
                )
                await session.execute(
                    delete(Guest).where(Guest.id.in_(guest_ids))
                )

        async def processor(session: object) -> HotelGuestProcessor:
            from sqlalchemy.ext.asyncio import AsyncSession

            assert isinstance(session, AsyncSession)
            conversation_repository = SQLAlchemyConversationRepository(session)
            hotel = HotelOperationsService(SQLAlchemyHotelOperationsRepository(session))
            registry = build_hotel_tool_registry(hotel)
            return HotelGuestProcessor(
                conversations=ConversationService(conversation_repository),
                intents=IntentRoutingService(
                    SQLAlchemyIntentClassificationRepository(session),
                    router,
                ),
                orchestrator=HybridOrchestrator(
                    llm=UnavailableLLM(),  # type: ignore[arg-type]
                    retrieval=UnusedRetrieval(),  # type: ignore[arg-type]
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
                ),
                identity_pepper=PEPPER,
            )

        async def send(user_id: int, update_id: int, text: str) -> str:
            async with database.transaction() as session:
                guest = await processor(session)
                reply = await guest.process(
                    inbound(user_id, update_id, text),
                    correlation_id=f"demo-{user_id}-{update_id}",
                )
                return reply.text

        async def confirm(user_id: int, update_id: int) -> str:
            async with database.transaction() as session:
                guest = await processor(session)
                reply = await guest.process_callback(
                    callback(user_id, update_id),
                    correlation_id=f"demo-{user_id}-{update_id}",
                )
                return reply.text

        try:
            await remove_test_guests()
            booking_user = user_ids[0]
            await send(booking_user, base + 1, "/new")
            assert "مرجع" in await send(booking_user, base + 2, "بدي تابع حجزي")
            assert "التحقق" in await send(
                booking_user,
                base + 3,
                "BKG-2026-0001",
            )
            invalid = await send(booking_user, base + 4, "9999")
            assert "تعذر التحقق" in invalid
            valid = await send(booking_user, base + 5, "0101")
            assert "confirmed" in valid
            assert "BKG-2026-0001" in valid

            one_message_user = user_ids[1]
            await send(one_message_user, base + 10, "/new")
            confirmation = await send(
                one_message_user,
                base + 11,
                "أريد وجبة فطور لغرفتي 101",
            )
            assert "يرجى تأكيد إنشاء الطلب" in confirmation
            assert "أريد وجبة فطور لغرفتي" in confirmation
            created = await confirm(one_message_user, base + 12)
            tracking_codes.extend(re.findall(r"SR-[A-Z0-9-]+", created))
            assert tracking_codes

            multi_user = user_ids[2]
            await send(multi_user, base + 20, "/new")
            assert "الغرفة" in await send(
                multi_user,
                base + 21,
                "خدمة الغرف",
            )
            category_question = await send(multi_user, base + 22, "101")
            assert "نوع الخدمة" in category_question
            multi_confirmation = await send(
                multi_user,
                base + 23,
                "أريد ماء وقهوة",
            )
            assert "يرجى تأكيد إنشاء الطلب" in multi_confirmation
            multi_created = await confirm(multi_user, base + 24)
            tracking_codes.extend(re.findall(r"SR-[A-Z0-9-]+", multi_created))
            assert len(tracking_codes) == 2

            async with database.session() as session:
                requests = (
                    await session.scalars(
                        select(ServiceRequest).where(
                            ServiceRequest.tracking_code.in_(tracking_codes)
                        )
                    )
                ).all()
                assert len(requests) == 2
                executions = (
                    await session.scalars(
                        select(ToolExecution).where(
                            ToolExecution.correlation_id.like("demo-%")
                        )
                    )
                ).all()
                assert sum(
                    item.result_status == "succeeded"
                    for item in executions
                ) >= 3
                assert any(
                    item.error_code
                    == "booking_not_found_or_verification_failed"
                    for item in executions
                )
                sensitive_messages = (
                    await session.scalars(
                        select(Message.text).where(
                            Message.correlation_id.like("demo-%"),
                            Message.text.in_(("0101", "9999")),
                        )
                    )
                ).all()
                assert sensitive_messages == []
        finally:
            async with database.transaction() as session:
                if tracking_codes:
                    await session.execute(
                        delete(ServiceRequest).where(
                            ServiceRequest.tracking_code.in_(tracking_codes)
                        )
                    )
                guest_ids = (
                    await session.scalars(
                        select(Guest.id).where(
                            Guest.telegram_user_hash.in_(hashes)
                        )
                    )
                ).all()
                if guest_ids:
                    await session.execute(
                        delete(ChannelUpdate).where(
                            ChannelUpdate.guest_id.in_(guest_ids)
                        )
                    )
                    await session.execute(
                        delete(Conversation).where(
                            Conversation.guest_id.in_(guest_ids)
                        )
                    )
                    await session.execute(
                        delete(Guest).where(Guest.id.in_(guest_ids))
                    )
            await database.dispose()

    asyncio.run(exercise())
