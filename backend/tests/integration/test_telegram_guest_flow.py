"""MySQL-backed Telegram idempotency, language, and inline-button journey."""

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
from hotel_bot.domain.conversation.models import (
    ContextEnvelope,
    SupportedLanguage,
)
from hotel_bot.domain.intent.classifier import (
    ALGORITHM_VERSION,
    NaiveBayesIntentClassifier,
)
from hotel_bot.domain.intent.enums import DatasetSplit, IntentCode
from hotel_bot.domain.intent.models import RoutingResult
from hotel_bot.domain.intent.routing import SafeIntentRouter
from hotel_bot.domain.llm.enums import AnswerBasis
from hotel_bot.domain.llm.models import (
    GroundedAnswer,
    OrchestrationResult,
)
from hotel_bot.domain.telegram.models import (
    TelegramGuestReply,
    TelegramInboundCallback,
    TelegramInboundMessage,
)
from hotel_bot.infrastructure.database import DatabaseManager
from hotel_bot.infrastructure.intent_dataset import load_intent_dataset
from hotel_bot.infrastructure.repositories.conversations import (
    SQLAlchemyConversationRepository,
)
from hotel_bot.infrastructure.repositories.intent_routing import (
    SQLAlchemyIntentClassificationRepository,
)
from hotel_bot.persistence import (
    ChannelUpdate,
    Conversation,
    Guest,
)

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        os.getenv("RUN_MYSQL_INTEGRATION") != "1",
        reason=(
            "set RUN_MYSQL_INTEGRATION=1 "
            "with the project MySQL container running"
        ),
    ),
]


PEPPER = "telegram-integration-pepper-00000001"
USER_ID = 987654321012


def mysql_settings() -> Settings:
    project_root = Path(__file__).resolve().parents[3]

    values = {
        key: value
        for line in (
            project_root / ".env"
        ).read_text(
            encoding="utf-8"
        ).splitlines()
        if (
            line
            and not line.lstrip().startswith("#")
            and "=" in line
        )
        for key, value in [
            line.split(
                "=",
                maxsplit=1,
            )
        ]
    }

    return Settings(
        APP_ENVIRONMENT="test",
        DB_HOST=values["DB_HOST"],
        DB_PORT=int(values["DB_PORT"]),
        DB_NAME=values["DB_NAME"],
        DB_USER=values["DB_USER"],
        DB_PASSWORD=SecretStr(
            values["DB_PASSWORD"]
        ),
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
        classifier_version=(
            f"{ALGORITHM_VERSION}"
            "+telegram-integration"
        )
    )

    model.fit(
        sample
        for sample in loaded.dataset.samples
        if sample.split is DatasetSplit.TRAIN
    )

    return SafeIntentRouter(model)


class RecordingOrchestrator:
    def __init__(self) -> None:
        self.calls: list[
            tuple[
                RoutingResult,
                bool,
                Mapping[str, object] | None,
            ]
        ] = []

    async def handle(
        self,
        context: ContextEnvelope,
        routing: RoutingResult,
        *,
        confirmed: bool = False,
        trusted_tool_arguments: (
            Mapping[str, object] | None
        ) = None,
    ) -> OrchestrationResult:
        self.calls.append(
            (
                routing,
                confirmed,
                trusted_tool_arguments,
            )
        )

        if (
            routing.requires_confirmation
            and not confirmed
        ):
            text = (
                "يرجى التأكيد."
                if context.state.language == "ar"
                else "Please confirm."
            )

            return OrchestrationResult(
                answer=GroundedAnswer(
                    language=context.state.language,
                    text=text,
                    basis=AnswerBasis.CONTROLLED,
                ),
                reason_code="confirmation_required",
            )

        if confirmed:
            tool_name = (
                "create_maintenance_request"
                if routing.prediction.intent
                is IntentCode.MAINTENANCE_REQUEST
                else "create_room_service_request"
            )
            return OrchestrationResult(
                answer=GroundedAnswer(
                    language=context.state.language,
                    text=(
                        "تم إنشاء الطلب."
                        if context.state.language == "ar"
                        else "The request was created."
                    ),
                    basis=AnswerBasis.TOOL,
                    tool_names=(
                        tool_name,
                    ),
                ),
                tool_executed=True,
                model_used=True,
                reason_code="validated_tool_answer",
            )

        text = (
            "أهلاً بك"
            if context.state.language == "ar"
            else "Welcome"
        )

        return OrchestrationResult(
            answer=GroundedAnswer(
                language=context.state.language,
                text=text,
                basis=AnswerBasis.CONTROLLED,
            ),
            reason_code="controlled_response",
        )


def message(
    update_id: int,
    text: str,
    *,
    language: SupportedLanguage = "en",
) -> TelegramInboundMessage:
    if text == "/start":
        command = "start"
    elif text == "/ar":
        command = "language_ar"
    elif text == "/en":
        command = "language_en"
    else:
        command = None

    return TelegramInboundMessage(
        update_id=str(update_id),
        chat_id=USER_ID,
        user_id=USER_ID,
        message_id=update_id,
        text=text,
        language=language,
        command=command,
    )


def callback(
    update_id: int,
    data: str,
    *,
    language: SupportedLanguage = "ar",
    message_id: int = 9001,
) -> TelegramInboundCallback:
    return TelegramInboundCallback(
        update_id=str(update_id),
        callback_query_id=(
            f"callback-query-{update_id}"
        ),
        chat_id=USER_ID,
        user_id=USER_ID,
        message_id=message_id,
        data=data,
        language=language,
    )


async def remove_guest(
    manager: DatabaseManager,
) -> None:
    guest_hash = telegram_identity_hash(
        USER_ID,
        PEPPER,
    )

    async with manager.transaction() as session:
        guest_id = await session.scalar(
            select(
                Guest.id
            ).where(
                Guest.telegram_user_hash
                == guest_hash
            )
        )

        if guest_id is not None:
            await session.execute(
                delete(
                    ChannelUpdate
                ).where(
                    ChannelUpdate.guest_id
                    == guest_id
                )
            )

            await session.execute(
                delete(
                    Conversation
                ).where(
                    Conversation.guest_id
                    == guest_id
                )
            )

            await session.execute(
                delete(
                    Guest
                ).where(
                    Guest.id
                    == guest_id
                )
            )


def test_mysql_guest_journey_supports_inline_confirmation_and_cancellation() -> None:
    async def exercise() -> None:
        manager = DatabaseManager(
            mysql_settings()
        )

        model = classifier()
        orchestrator = RecordingOrchestrator()

        async def process_message(
            inbound: TelegramInboundMessage,
        ) -> TelegramGuestReply:
            async with manager.transaction() as session:
                processor = HotelGuestProcessor(
                    conversations=ConversationService(
                        SQLAlchemyConversationRepository(
                            session
                        ),
                    ),
                    intents=IntentRoutingService(
                        SQLAlchemyIntentClassificationRepository(
                            session
                        ),
                        model,
                    ),
                    orchestrator=cast(
                        HybridOrchestrator,
                        orchestrator,
                    ),
                    identity_pepper=PEPPER,
                )

                return await processor.process(
                    inbound,
                    correlation_id=(
                        f"telegram-e2e-"
                        f"{inbound.update_id}"
                    ),
                )

        async def process_callback(
            inbound: TelegramInboundCallback,
        ) -> TelegramGuestReply:
            async with manager.transaction() as session:
                processor = HotelGuestProcessor(
                    conversations=ConversationService(
                        SQLAlchemyConversationRepository(
                            session
                        ),
                    ),
                    intents=IntentRoutingService(
                        SQLAlchemyIntentClassificationRepository(
                            session
                        ),
                        model,
                    ),
                    orchestrator=cast(
                        HybridOrchestrator,
                        orchestrator,
                    ),
                    identity_pepper=PEPPER,
                )

                return await processor.process_callback(
                    inbound,
                    correlation_id=(
                        f"telegram-callback-e2e-"
                        f"{inbound.update_id}"
                    ),
                )

        try:
            await remove_guest(manager)

            started = await process_message(
                message(
                    7001,
                    "/start",
                )
            )

            replayed_start = await process_message(
                message(
                    7001,
                    "/start",
                )
            )

            switched = await process_message(
                message(
                    7002,
                    "/ar",
                    language="en",
                )
            )

            greeting = await process_message(
                message(
                    7003,
                    "Hello",
                    language="en",
                )
            )

            proposed = await process_message(
                message(
                    7004,
                    (
                        "Please send extra towels "
                        "to room 101"
                    ),
                    language="en",
                )
            )

            confirmed = await process_callback(
                callback(
                    7005,
                    "workflow:confirm",
                    language="ar",
                    message_id=9001,
                )
            )

            replayed_confirmation = (
                await process_callback(
                    callback(
                        7005,
                        "workflow:confirm",
                        language="ar",
                        message_id=9001,
                    )
                )
            )

            second_proposed = await process_message(
                message(
                    7006,
                    (
                        "Please send extra blankets "
                        "to room 304"
                    ),
                    language="en",
                )
            )

            cancelled = await process_callback(
                callback(
                    7007,
                    "workflow:cancel",
                    language="ar",
                    message_id=9002,
                )
            )

            replayed_cancellation = (
                await process_callback(
                    callback(
                        7007,
                        "workflow:cancel",
                        language="ar",
                        message_id=9002,
                    )
                )
            )

            assert started.language == "en"

            assert replayed_start.duplicate is True
            assert replayed_start.text == started.text

            assert switched.language == "ar"

            assert greeting.language == "ar"
            assert greeting.text == "أهلاً بك"

            assert proposed.language == "ar"
            assert proposed.reply_markup is not None

            assert (
                "يرجى تأكيد إنشاء الطلب"
                in proposed.text
            )

            assert (
                "رقم الغرفة: 101"
                in proposed.text
            )

            proposed_buttons = (
                proposed.reply_markup.inline_keyboard[0]
            )

            assert (
                proposed_buttons[0].callback_data
                == "workflow:confirm"
            )

            assert (
                proposed_buttons[1].callback_data
                == "workflow:cancel"
            )

            assert confirmed.language == "ar"
            assert confirmed.text == "تم إنشاء الطلب."
            assert confirmed.reply_markup is None

            assert (
                replayed_confirmation.duplicate
                is True
            )

            assert (
                replayed_confirmation.text
                == confirmed.text
            )

            confirmation_calls = [
                call
                for call in orchestrator.calls
                if call[1] is True
            ]

            assert len(confirmation_calls) == 1

            confirmation_call = confirmation_calls[0]

            assert confirmation_call[2] is not None

            assert (
                confirmation_call[2]["room_number"]
                == "101"
            )

            assert (
                confirmation_call[2]["category"]
                == "amenities"
            )

            assert second_proposed.reply_markup is not None

            assert (
                "رقم الغرفة: 304"
                in second_proposed.text
            )

            assert cancelled.language == "ar"
            assert cancelled.text == "تم إلغاء العملية."
            assert cancelled.reply_markup is None

            assert (
                replayed_cancellation.duplicate
                is True
            )

            assert (
                replayed_cancellation.text
                == cancelled.text
            )

            confirmation_calls_after_cancel = [
                call
                for call in orchestrator.calls
                if call[1] is True
            ]

            assert (
                len(
                    confirmation_calls_after_cancel
                )
                == 1
            )

            maintenance_proposed = await process_message(
                message(
                    7008,
                    "المكيف في الغرفة 304 لا يعمل، أريد فتح طلب صيانة.",
                    language="ar",
                )
            )

            maintenance_confirmed = await process_callback(
                callback(
                    7009,
                    "workflow:confirm",
                    language="ar",
                    message_id=9003,
                )
            )

            assert maintenance_proposed.reply_markup is not None
            assert maintenance_confirmed.text == "تم إنشاء الطلب."

            maintenance_calls = [
                call
                for call in orchestrator.calls
                if (
                    call[1] is True
                    and call[0].prediction.intent
                    is IntentCode.MAINTENANCE_REQUEST
                )
            ]

            assert len(maintenance_calls) == 1
            assert maintenance_calls[0][2] is not None
            assert maintenance_calls[0][2]["room_number"] == "304"
            assert maintenance_calls[0][2]["category"] == "hvac"

            async with manager.session() as session:
                conversation = await session.scalar(
                    select(
                        Conversation
                    )
                    .join(
                        Guest,
                        Guest.id
                        == Conversation.guest_id,
                    )
                    .where(
                        Guest.telegram_user_hash
                        == telegram_identity_hash(
                            USER_ID,
                            PEPPER,
                        ),
                        Conversation.status
                        == "open",
                    )
                    .order_by(
                        Conversation.started_at.desc()
                    )
                )

                assert conversation is not None
                assert conversation.language == "ar"

                assert (
                    conversation.context_state_json
                    is not None
                )

                assert (
                    conversation.context_state_json.get(
                        "active_workflow"
                    )
                    is None
                )

                updates = (
                    await session.scalars(
                        select(
                            ChannelUpdate
                        ).where(
                            ChannelUpdate.guest_id
                            == conversation.guest_id
                        )
                    )
                ).all()

                assert len(updates) == 9

        finally:
            await remove_guest(manager)
            await manager.dispose()

    asyncio.run(exercise())
