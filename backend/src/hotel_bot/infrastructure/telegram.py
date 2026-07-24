"""HTTP adapter for Telegram Bot API without token-bearing logs."""

from typing import Any

import httpx

from hotel_bot.domain.telegram.errors import TelegramDeliveryError
from hotel_bot.domain.telegram.models import (
    TelegramInlineKeyboardMarkup,
    TelegramSentMessage,
)


class TelegramBotAPIClient:
    def __init__(
        self,
        *,
        bot_token: str,
        base_url: str = "https://api.telegram.org",
        timeout_ms: int = 10_000,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        if len(bot_token.strip()) < 20:
            raise ValueError("Telegram bot token is invalid")

        self._token = bot_token.strip()
        self._client = httpx.AsyncClient(
            base_url=base_url.rstrip("/"),
            timeout=timeout_ms / 1000,
            transport=transport,
        )

    async def send_message(
        self,
        *,
        chat_id: int,
        text: str,
        reply_markup: TelegramInlineKeyboardMarkup | None = None,
    ) -> TelegramSentMessage:
        request_json: dict[str, Any] = {
            "chat_id": chat_id,
            "text": text,
            "protect_content": True,
        }

        if reply_markup is not None:
            request_json["reply_markup"] = reply_markup.model_dump(
                mode="json",
                exclude_none=True,
            )

        try:
            payload = await self._post(
                "sendMessage",
                json=request_json,
            )
        except (httpx.HTTPError, ValueError) as exc:
            raise TelegramDeliveryError("Telegram sendMessage failed") from exc

        result: Any = payload.get("result") if isinstance(payload, dict) else None

        if payload.get("ok") is not True or not isinstance(result, dict):
            raise TelegramDeliveryError("Telegram rejected sendMessage")

        try:
            return TelegramSentMessage(
                message_id=int(result["message_id"]),
                chat_id=int(result["chat"]["id"]),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise TelegramDeliveryError(
                "Telegram returned an invalid sendMessage response"
            ) from exc

    async def answer_callback_query(
        self,
        *,
        callback_query_id: str,
        text: str | None = None,
        show_alert: bool = False,
    ) -> None:
        if not callback_query_id.strip():
            raise ValueError("Telegram callback query ID is required")

        if text is not None and len(text) > 200:
            raise ValueError("Telegram callback answer exceeds 200 characters")

        request_json: dict[str, Any] = {
            "callback_query_id": callback_query_id,
            "show_alert": show_alert,
        }

        if text:
            request_json["text"] = text

        try:
            payload = await self._post(
                "answerCallbackQuery",
                json=request_json,
            )
        except (httpx.HTTPError, ValueError) as exc:
            raise TelegramDeliveryError(
                "Telegram answerCallbackQuery failed"
            ) from exc

        if payload.get("ok") is not True or payload.get("result") is not True:
            raise TelegramDeliveryError(
                "Telegram rejected answerCallbackQuery"
            )

    async def set_webhook(
        self,
        *,
        url: str,
        secret_token: str,
        max_connections: int = 20,
    ) -> None:
        if not url.startswith("https://"):
            raise ValueError("Telegram webhook URL must use HTTPS")

        if not 1 <= max_connections <= 100:
            raise ValueError("Telegram webhook max connections must be 1 to 100")

        try:
            payload = await self._post(
                "setWebhook",
                json={
                    "url": url,
                    "secret_token": secret_token,
                    "allowed_updates": [
                        "message",
                        "callback_query",
                    ],
                    "max_connections": max_connections,
                    "drop_pending_updates": False,
                },
            )
        except (httpx.HTTPError, ValueError) as exc:
            raise TelegramDeliveryError("Telegram setWebhook failed") from exc

        if payload.get("ok") is not True or payload.get("result") is not True:
            raise TelegramDeliveryError("Telegram rejected setWebhook")

    async def _post(
        self,
        method: str,
        *,
        json: dict[str, Any],
    ) -> dict[str, Any]:
        response = await self._client.post(
            f"/bot{self._token}/{method}",
            json=json,
        )
        response.raise_for_status()

        payload = response.json()

        if not isinstance(payload, dict):
            raise ValueError("Telegram returned a non-object response")

        return payload

    async def close(self) -> None:
        await self._client.aclose()