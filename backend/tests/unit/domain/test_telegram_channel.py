"""Telegram parsing, identity privacy, callbacks, and delivery contracts."""

import asyncio
import json

import httpx
import pytest

from hotel_bot.application.telegram import (
    TelegramWebhookCoordinator,
    parse_telegram_callback,
    parse_telegram_update,
    telegram_identity_hash,
)
from hotel_bot.domain.telegram.errors import TelegramDeliveryError
from hotel_bot.domain.telegram.models import (
    TelegramGuestReply,
    TelegramInboundCallback,
    TelegramInboundMessage,
    TelegramInlineKeyboardButton,
    TelegramInlineKeyboardMarkup,
    TelegramSentMessage,
    TelegramUpdate,
)
from hotel_bot.infrastructure.telegram import TelegramBotAPIClient

USER_ID = 123456789012
CHAT_ID = 123456789012


def update_payload(
    *,
    update_id: int = 1001,
    text: str | None = "/start",
    language_code: str | None = "ar",
    chat_type: str = "private",
    is_bot: bool = False,
) -> TelegramUpdate:
    return TelegramUpdate.model_validate(
        {
            "update_id": update_id,
            "message": {
                "message_id": 50,
                "from": {
                    "id": USER_ID,
                    "is_bot": is_bot,
                    "language_code": language_code,
                    "username": "must_not_be_stored",
                },
                "chat": {
                    "id": CHAT_ID,
                    "type": chat_type,
                },
                "date": 1784635200,
                "text": text,
            },
        }
    )


def callback_update_payload(
    *,
    update_id: int = 2001,
    callback_query_id: str = "callback-query-001",
    callback_data: str | None = "workflow:confirm",
    language_code: str | None = "ar",
    chat_type: str = "private",
    is_bot: bool = False,
    include_message: bool = True,
) -> TelegramUpdate:
    callback_query: dict[str, object] = {
        "id": callback_query_id,
        "from": {
            "id": USER_ID,
            "is_bot": is_bot,
            "language_code": language_code,
            "username": "must_not_be_stored",
        },
        "data": callback_data,
    }

    if include_message:
        callback_query["message"] = {
            "message_id": 75,
            "from": {
                "id": 999999999,
                "is_bot": True,
                "language_code": "en",
            },
            "chat": {
                "id": CHAT_ID,
                "type": chat_type,
            },
            "date": 1784635300,
            "text": "Please confirm",
        }

    return TelegramUpdate.model_validate(
        {
            "update_id": update_id,
            "callback_query": callback_query,
        }
    )


def confirmation_markup() -> TelegramInlineKeyboardMarkup:
    return TelegramInlineKeyboardMarkup(
        inline_keyboard=(
            (
                TelegramInlineKeyboardButton(
                    text="✅ تأكيد الطلب",
                    callback_data="workflow:confirm",
                ),
                TelegramInlineKeyboardButton(
                    text="❌ إلغاء",
                    callback_data="workflow:cancel",
                ),
            ),
        )
    )


def test_parser_accepts_private_text_and_normalizes_language_and_command() -> None:
    parsed = parse_telegram_update(
        update_payload(
            text="/help@hotel_bot",
            language_code="ar-SY",
        )
    )

    assert parsed is not None
    assert parsed.update_id == "1001"
    assert parsed.command == "help"
    assert parsed.language == "ar"
    assert parsed.user_id == USER_ID
    assert parsed.chat_id == CHAT_ID


def test_parser_falls_back_to_text_language_and_ignores_unsupported_updates() -> None:
    english = parse_telegram_update(
        update_payload(
            text="Hello",
            language_code=None,
        )
    )

    arabic = parse_telegram_update(
        update_payload(
            text="مرحبا",
            language_code="fr",
        )
    )

    assert english is not None
    assert english.language == "en"

    assert arabic is not None
    assert arabic.language == "ar"

    assert parse_telegram_update(
        update_payload(chat_type="group")
    ) is None

    assert parse_telegram_update(
        update_payload(is_bot=True)
    ) is None

    assert parse_telegram_update(
        update_payload(text=None)
    ) is None


def test_parser_prefers_clear_message_script_over_telegram_profile_language() -> None:
    english = parse_telegram_update(
        update_payload(
            text=(
                "Does the hotel offer airport pick-up services from Damascus "
                "International Airport, and how far in advance do I need to book?"
            ),
            language_code="ar",
        )
    )
    arabic = parse_telegram_update(
        update_payload(
            text="هل تتوفر خدمة نقل من المطار؟",
            language_code="en",
        )
    )

    assert english is not None
    assert english.language == "en"
    assert arabic is not None
    assert arabic.language == "ar"


def test_callback_parser_accepts_private_inline_button() -> None:
    parsed = parse_telegram_callback(
        callback_update_payload(
            callback_data="workflow:confirm",
            language_code="ar-SY",
        )
    )

    assert parsed is not None
    assert parsed.update_id == "2001"
    assert parsed.callback_query_id == "callback-query-001"
    assert parsed.data == "workflow:confirm"
    assert parsed.language == "ar"
    assert parsed.user_id == USER_ID
    assert parsed.chat_id == CHAT_ID
    assert parsed.message_id == 75


def test_callback_parser_ignores_invalid_or_unsupported_callbacks() -> None:
    assert parse_telegram_callback(
        callback_update_payload(
            callback_data=None,
        )
    ) is None

    assert parse_telegram_callback(
        callback_update_payload(
            chat_type="group",
        )
    ) is None

    assert parse_telegram_callback(
        callback_update_payload(
            is_bot=True,
        )
    ) is None

    assert parse_telegram_callback(
        callback_update_payload(
            include_message=False,
        )
    ) is None


def test_identity_uses_keyed_hmac_not_plain_user_id_hash() -> None:
    first = telegram_identity_hash(
        USER_ID,
        "a" * 32,
    )

    repeated = telegram_identity_hash(
        USER_ID,
        "a" * 32,
    )

    rotated = telegram_identity_hash(
        USER_ID,
        "b" * 32,
    )

    assert first == repeated
    assert first != rotated
    assert str(USER_ID) not in first
    assert len(first) == 64


class FakeProcessor:
    def __init__(
        self,
        *,
        duplicate: bool = False,
        callback_duplicate: bool = False,
        include_markup: bool = False,
    ) -> None:
        self.duplicate = duplicate
        self.callback_duplicate = callback_duplicate
        self.include_markup = include_markup

        self.message_calls: list[
            tuple[TelegramInboundMessage, str]
        ] = []

        self.callback_calls: list[
            tuple[TelegramInboundCallback, str]
        ] = []

    async def process(
        self,
        message: TelegramInboundMessage,
        *,
        correlation_id: str,
    ) -> TelegramGuestReply:
        self.message_calls.append(
            (
                message,
                correlation_id,
            )
        )

        return TelegramGuestReply(
            text="أهلاً بك",
            language="ar",
            duplicate=self.duplicate,
        )

    async def process_callback(
        self,
        callback: TelegramInboundCallback,
        *,
        correlation_id: str,
    ) -> TelegramGuestReply:
        self.callback_calls.append(
            (
                callback,
                correlation_id,
            )
        )

        return TelegramGuestReply(
            text="تم إنشاء الطلب.",
            language="ar",
            duplicate=self.callback_duplicate,
            reply_markup=(
                confirmation_markup()
                if self.include_markup
                else None
            ),
        )


class FakeSender:
    def __init__(
        self,
        *,
        fail: bool = False,
        callback_fail: bool = False,
    ) -> None:
        self.fail = fail
        self.callback_fail = callback_fail

        self.sent: list[
            tuple[
                int,
                str,
                TelegramInlineKeyboardMarkup | None,
            ]
        ] = []

        self.answered_callbacks: list[
            tuple[str, str | None, bool]
        ] = []

    async def send_message(
        self,
        *,
        chat_id: int,
        text: str,
        reply_markup: TelegramInlineKeyboardMarkup | None = None,
    ) -> TelegramSentMessage:
        if self.fail:
            raise TelegramDeliveryError("offline")

        self.sent.append(
            (
                chat_id,
                text,
                reply_markup,
            )
        )

        return TelegramSentMessage(
            message_id=77,
            chat_id=chat_id,
        )

    async def answer_callback_query(
        self,
        *,
        callback_query_id: str,
        text: str | None = None,
        show_alert: bool = False,
    ) -> None:
        if self.callback_fail:
            raise TelegramDeliveryError(
                "callback answer failed"
            )

        self.answered_callbacks.append(
            (
                callback_query_id,
                text,
                show_alert,
            )
        )


def test_coordinator_sends_once_and_skips_duplicate_delivery() -> None:
    sender = FakeSender()

    first_processor = FakeProcessor()

    duplicate_processor = FakeProcessor(
        duplicate=True,
    )

    first = TelegramWebhookCoordinator(
        first_processor,
        sender,
    )

    duplicate = TelegramWebhookCoordinator(
        duplicate_processor,
        sender,
    )

    processed = asyncio.run(
        first.handle(
            update_payload(),
            correlation_id="telegram-test-1",
        )
    )

    replay = asyncio.run(
        duplicate.handle(
            update_payload(),
            correlation_id="telegram-test-1",
        )
    )

    assert processed.status == "processed"
    assert replay.status == "duplicate"

    assert sender.sent == [
        (
            CHAT_ID,
            "أهلاً بك",
            None,
        )
    ]

    assert len(first_processor.message_calls) == 1
    assert len(duplicate_processor.message_calls) == 1


def test_coordinator_processes_callback_and_answers_telegram_query() -> None:
    processor = FakeProcessor(
        include_markup=True,
    )

    sender = FakeSender()

    coordinator = TelegramWebhookCoordinator(
        processor,
        sender,
    )

    result = asyncio.run(
        coordinator.handle(
            callback_update_payload(),
            correlation_id="telegram-callback-test-1",
        )
    )

    assert result.status == "processed"

    assert sender.answered_callbacks == [
        (
            "callback-query-001",
            None,
            False,
        )
    ]

    assert len(processor.callback_calls) == 1

    callback, correlation_id = (
        processor.callback_calls[0]
    )

    assert callback.data == "workflow:confirm"
    assert correlation_id == "telegram-callback-test-1"

    assert sender.sent == [
        (
            CHAT_ID,
            "تم إنشاء الطلب.",
            confirmation_markup(),
        )
    ]


def test_coordinator_skips_callback_reply_delivery_when_duplicate() -> None:
    processor = FakeProcessor(
        callback_duplicate=True,
    )

    sender = FakeSender()

    coordinator = TelegramWebhookCoordinator(
        processor,
        sender,
    )

    result = asyncio.run(
        coordinator.handle(
            callback_update_payload(),
            correlation_id="telegram-callback-test-duplicate",
        )
    )

    assert result.status == "duplicate"

    assert sender.answered_callbacks == [
        (
            "callback-query-001",
            None,
            False,
        )
    ]

    assert sender.sent == []


def test_delivery_failure_propagates_for_webhook_retry() -> None:
    coordinator = TelegramWebhookCoordinator(
        FakeProcessor(),
        FakeSender(fail=True),
    )

    with pytest.raises(TelegramDeliveryError):
        asyncio.run(
            coordinator.handle(
                update_payload(),
                correlation_id="telegram-test-2",
            )
        )


def test_callback_answer_failure_propagates_for_webhook_retry() -> None:
    coordinator = TelegramWebhookCoordinator(
        FakeProcessor(),
        FakeSender(callback_fail=True),
    )

    with pytest.raises(TelegramDeliveryError):
        asyncio.run(
            coordinator.handle(
                callback_update_payload(),
                correlation_id="telegram-callback-test-2",
            )
        )


def test_bot_api_client_registers_message_and_callback_webhook_with_secret() -> None:
    requests: list[httpx.Request] = []

    async def handler(
        request: httpx.Request,
    ) -> httpx.Response:
        requests.append(request)

        return httpx.Response(
            200,
            json={
                "ok": True,
                "result": True,
            },
        )

    async def exercise() -> None:
        client = TelegramBotAPIClient(
            bot_token="123456789:test-bot-token-value",
            transport=httpx.MockTransport(handler),
        )

        try:
            await client.set_webhook(
                url=(
                    "https://hotel.example"
                    "/api/v1/telegram/webhook"
                ),
                secret_token="safe_webhook_secret_123",
                max_connections=12,
            )
        finally:
            await client.close()

    asyncio.run(exercise())

    assert len(requests) == 1

    body = json.loads(
        requests[0].content
    )

    assert requests[0].url.path.endswith(
        "/setWebhook"
    )

    assert body == {
        "url": (
            "https://hotel.example"
            "/api/v1/telegram/webhook"
        ),
        "secret_token": "safe_webhook_secret_123",
        "allowed_updates": [
            "message",
            "callback_query",
        ],
        "max_connections": 12,
        "drop_pending_updates": False,
    }


def test_bot_api_client_serializes_inline_keyboard() -> None:
    requests: list[httpx.Request] = []

    async def handler(
        request: httpx.Request,
    ) -> httpx.Response:
        requests.append(request)

        return httpx.Response(
            200,
            json={
                "ok": True,
                "result": {
                    "message_id": 77,
                    "chat": {
                        "id": CHAT_ID,
                    },
                },
            },
        )

    async def exercise() -> TelegramSentMessage:
        client = TelegramBotAPIClient(
            bot_token="123456789:test-bot-token-value",
            transport=httpx.MockTransport(handler),
        )

        try:
            return await client.send_message(
                chat_id=CHAT_ID,
                text="يرجى تأكيد الطلب.",
                reply_markup=confirmation_markup(),
            )
        finally:
            await client.close()

    sent = asyncio.run(exercise())

    assert sent.message_id == 77
    assert sent.chat_id == CHAT_ID

    assert len(requests) == 1
    assert requests[0].url.path.endswith(
        "/sendMessage"
    )

    body = json.loads(
        requests[0].content
    )

    assert body == {
        "chat_id": CHAT_ID,
        "text": "يرجى تأكيد الطلب.",
        "protect_content": True,
        "reply_markup": {
            "inline_keyboard": [
                [
                    {
                        "text": "✅ تأكيد الطلب",
                        "callback_data": "workflow:confirm",
                    },
                    {
                        "text": "❌ إلغاء",
                        "callback_data": "workflow:cancel",
                    },
                ]
            ]
        },
    }


def test_bot_api_client_answers_callback_query() -> None:
    requests: list[httpx.Request] = []

    async def handler(
        request: httpx.Request,
    ) -> httpx.Response:
        requests.append(request)

        return httpx.Response(
            200,
            json={
                "ok": True,
                "result": True,
            },
        )

    async def exercise() -> None:
        client = TelegramBotAPIClient(
            bot_token="123456789:test-bot-token-value",
            transport=httpx.MockTransport(handler),
        )

        try:
            await client.answer_callback_query(
                callback_query_id="callback-query-001",
                text="تم تأكيد الطلب.",
                show_alert=False,
            )
        finally:
            await client.close()

    asyncio.run(exercise())

    assert len(requests) == 1

    assert requests[0].url.path.endswith(
        "/answerCallbackQuery"
    )

    body = json.loads(
        requests[0].content
    )

    assert body == {
        "callback_query_id": "callback-query-001",
        "show_alert": False,
        "text": "تم تأكيد الطلب.",
    }
