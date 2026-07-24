"""Telegram parsing, identity privacy, language, and delivery contracts."""

import asyncio
import json

import httpx
import pytest

from hotel_bot.application.telegram import (
    TelegramWebhookCoordinator,
    parse_telegram_update,
    telegram_identity_hash,
)
from hotel_bot.domain.telegram.errors import TelegramDeliveryError
from hotel_bot.domain.telegram.models import (
    TelegramGuestReply,
    TelegramSentMessage,
    TelegramUpdate,
)
from hotel_bot.infrastructure.telegram import TelegramBotAPIClient


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
                    "id": 123456789012,
                    "is_bot": is_bot,
                    "language_code": language_code,
                    "username": "must_not_be_stored",
                },
                "chat": {"id": 123456789012, "type": chat_type},
                "date": 1784635200,
                "text": text,
            },
        }
    )


def test_parser_accepts_private_text_and_normalizes_language_and_command() -> None:
    parsed = parse_telegram_update(update_payload(text="/help@hotel_bot", language_code="ar-SY"))

    assert parsed is not None
    assert parsed.update_id == "1001"
    assert parsed.command == "help"
    assert parsed.language == "ar"
    assert parsed.user_id == 123456789012


def test_parser_falls_back_to_text_language_and_ignores_unsupported_updates() -> None:
    english = parse_telegram_update(update_payload(text="Hello", language_code=None))
    arabic = parse_telegram_update(update_payload(text="مرحبا", language_code="fr"))

    assert english is not None and english.language == "en"
    assert arabic is not None and arabic.language == "ar"
    assert parse_telegram_update(update_payload(chat_type="group")) is None
    assert parse_telegram_update(update_payload(is_bot=True)) is None
    assert parse_telegram_update(update_payload(text=None)) is None


def test_identity_uses_keyed_hmac_not_plain_user_id_hash() -> None:
    first = telegram_identity_hash(123456789012, "a" * 32)
    repeated = telegram_identity_hash(123456789012, "a" * 32)
    rotated = telegram_identity_hash(123456789012, "b" * 32)

    assert first == repeated
    assert first != rotated
    assert "123456789012" not in first
    assert len(first) == 64


class FakeProcessor:
    def __init__(self, *, duplicate: bool = False) -> None:
        self.duplicate = duplicate
        self.calls = 0

    async def process(self, message: object, *, correlation_id: str) -> TelegramGuestReply:
        self.calls += 1
        return TelegramGuestReply(text="أهلاً بك", language="ar", duplicate=self.duplicate)


class FakeSender:
    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.sent: list[tuple[int, str]] = []

    async def send_message(self, *, chat_id: int, text: str) -> TelegramSentMessage:
        if self.fail:
            raise TelegramDeliveryError("offline")
        self.sent.append((chat_id, text))
        return TelegramSentMessage(message_id=77, chat_id=chat_id)


def test_coordinator_sends_once_and_skips_duplicate_delivery() -> None:
    sender = FakeSender()
    first = TelegramWebhookCoordinator(FakeProcessor(), sender)
    duplicate = TelegramWebhookCoordinator(FakeProcessor(duplicate=True), sender)

    processed = asyncio.run(first.handle(update_payload(), correlation_id="telegram-test-1"))
    replay = asyncio.run(duplicate.handle(update_payload(), correlation_id="telegram-test-1"))

    assert processed.status == "processed"
    assert replay.status == "duplicate"
    assert sender.sent == [(123456789012, "أهلاً بك")]


def test_delivery_failure_propagates_for_webhook_retry() -> None:
    coordinator = TelegramWebhookCoordinator(FakeProcessor(), FakeSender(fail=True))

    with pytest.raises(TelegramDeliveryError):
        asyncio.run(coordinator.handle(update_payload(), correlation_id="telegram-test-2"))


def test_bot_api_client_registers_message_only_webhook_with_secret() -> None:
    requests: list[httpx.Request] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json={"ok": True, "result": True})

    async def exercise() -> None:
        client = TelegramBotAPIClient(
            bot_token="123456789:test-bot-token-value",
            transport=httpx.MockTransport(handler),
        )
        try:
            await client.set_webhook(
                url="https://hotel.example/api/v1/telegram/webhook",
                secret_token="safe_webhook_secret_123",
                max_connections=12,
            )
        finally:
            await client.close()

    asyncio.run(exercise())

    body = json.loads(requests[0].content)
    assert requests[0].url.path.endswith("/setWebhook")
    assert body == {
        "url": "https://hotel.example/api/v1/telegram/webhook",
        "secret_token": "safe_webhook_secret_123",
        "allowed_updates": ["message"],
        "max_connections": 12,
        "drop_pending_updates": False,
    }
