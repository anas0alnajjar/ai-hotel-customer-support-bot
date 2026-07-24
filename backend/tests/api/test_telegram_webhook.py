"""Telegram webhook authentication, body limits, validation, and retry responses."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI
from fastapi.testclient import TestClient

from hotel_bot.dependencies import get_database_manager, get_telegram_runtime
from hotel_bot.domain.telegram.errors import TelegramDeliveryError
from hotel_bot.domain.telegram.models import TelegramWebhookResult

SECRET = "telegram_webhook_secret_123"
HEADERS = {"X-Telegram-Bot-Api-Secret-Token": SECRET}


class FakeDatabase:
    @asynccontextmanager
    async def transaction(self) -> AsyncIterator[object]:
        yield object()


class FakeRuntime:
    configured = True
    webhook_secret = SECRET

    def __init__(self, *, fail_delivery: bool = False) -> None:
        self.fail_delivery = fail_delivery
        self.updates: list[tuple[int, str]] = []

    async def handle(
        self,
        session: object,
        update: Any,
        *,
        correlation_id: str,
    ) -> TelegramWebhookResult:
        if self.fail_delivery:
            raise TelegramDeliveryError("offline")
        self.updates.append((update.update_id, correlation_id))
        return TelegramWebhookResult(status="processed", update_id=str(update.update_id))


def payload(update_id: int = 4001) -> dict[str, object]:
    return {
        "update_id": update_id,
        "message": {
            "message_id": 5,
            "from": {"id": 999, "is_bot": False, "language_code": "en"},
            "chat": {"id": 999, "type": "private"},
            "date": 1784635200,
            "text": "/start",
        },
    }


def configure(client: TestClient, runtime: FakeRuntime) -> None:
    app = client.app
    assert isinstance(app, FastAPI)
    app.dependency_overrides[get_database_manager] = lambda: FakeDatabase()
    app.dependency_overrides[get_telegram_runtime] = lambda: runtime


def test_webhook_rejects_missing_or_wrong_secret(client: TestClient) -> None:
    configure(client, FakeRuntime())

    missing = client.post("/api/v1/telegram/webhook", json=payload())
    wrong = client.post(
        "/api/v1/telegram/webhook",
        json=payload(),
        headers={"X-Telegram-Bot-Api-Secret-Token": "wrong"},
    )

    assert missing.status_code == 401
    assert wrong.status_code == 401


def test_webhook_validates_json_and_payload_size(client: TestClient) -> None:
    configure(client, FakeRuntime())

    malformed = client.post(
        "/api/v1/telegram/webhook",
        content=b"not-json",
        headers={**HEADERS, "Content-Type": "application/json"},
    )
    oversized = client.post(
        "/api/v1/telegram/webhook",
        content=b"x",
        headers={
            **HEADERS,
            "Content-Length": "262145",
            "Content-Type": "application/json",
        },
    )

    assert malformed.status_code == 400
    assert oversized.status_code == 413


def test_valid_webhook_propagates_correlation_and_returns_ack(client: TestClient) -> None:
    runtime = FakeRuntime()
    configure(client, runtime)

    response = client.post(
        "/api/v1/telegram/webhook",
        json=payload(),
        headers={**HEADERS, "X-Correlation-ID": "telegram-update-4001"},
    )

    assert response.status_code == 200
    assert response.json() == {"status": "processed", "update_id": "4001"}
    assert response.headers["X-Correlation-ID"] == "telegram-update-4001"
    assert runtime.updates == [(4001, "telegram-update-4001")]


def test_delivery_failure_returns_retryable_gateway_error(client: TestClient) -> None:
    configure(client, FakeRuntime(fail_delivery=True))

    response = client.post("/api/v1/telegram/webhook", json=payload(), headers=HEADERS)

    assert response.status_code == 502
    assert response.json() == {"detail": "telegram_delivery_failed"}
