"""Telegram parsing, pseudonymous identity, and channel coordination."""

import hashlib
import hmac
import re
from typing import Protocol, cast

from hotel_bot.domain.conversation.models import SupportedLanguage
from hotel_bot.domain.telegram.errors import TelegramDeliveryError
from hotel_bot.domain.telegram.models import (
    TelegramCommand,
    TelegramGuestReply,
    TelegramInboundCallback,
    TelegramInboundMessage,
    TelegramInlineKeyboardMarkup,
    TelegramSentMessage,
    TelegramUpdate,
    TelegramWebhookResult,
)


ARABIC_PATTERN = re.compile(r"[\u0600-\u06ff]")


class TelegramGuestProcessor(Protocol):
    async def process(
        self,
        message: TelegramInboundMessage,
        *,
        correlation_id: str,
    ) -> TelegramGuestReply:
        ...

    async def process_callback(
        self,
        callback: TelegramInboundCallback,
        *,
        correlation_id: str,
    ) -> TelegramGuestReply:
        ...


class TelegramSender(Protocol):
    async def send_message(
        self,
        *,
        chat_id: int,
        text: str,
        reply_markup: TelegramInlineKeyboardMarkup | None = None,
    ) -> TelegramSentMessage:
        ...

    async def answer_callback_query(
        self,
        *,
        callback_query_id: str,
        text: str | None = None,
        show_alert: bool = False,
    ) -> None:
        ...


def telegram_identity_hash(
    user_id: int,
    pepper: str,
) -> str:
    """Generate a pseudonymous Telegram guest identity."""

    if user_id <= 0:
        raise ValueError(
            "Telegram user ID must be positive"
        )

    if len(pepper) < 32:
        raise ValueError(
            "Telegram identity pepper must contain at least 32 characters"
        )

    return hmac.new(
        pepper.encode("utf-8"),
        f"telegram:{user_id}".encode("ascii"),
        hashlib.sha256,
    ).hexdigest()


def _language(
    language_code: str | None,
    text: str,
) -> str:
    """Resolve Arabic or English from Telegram metadata and text."""

    primary = (
        (language_code or "")
        .strip()
        .lower()
        .split("-", maxsplit=1)[0]
    )

    if primary in {
        "ar",
        "en",
    }:
        return primary

    return (
        "ar"
        if ARABIC_PATTERN.search(text)
        else "en"
    )


def _command(
    text: str,
) -> TelegramCommand | None:
    """Parse supported Telegram slash commands."""

    token = text.split(
        maxsplit=1
    )[0].lower()

    if not token.startswith("/"):
        return None

    name = token[1:].split(
        "@",
        maxsplit=1,
    )[0]

    mapping = {
        "start": "start",
        "help": "help",
        "new": "new",
        "ar": "language_ar",
        "en": "language_en",
    }

    return cast(
        TelegramCommand | None,
        mapping.get(name),
    )


def parse_telegram_update(
    update: TelegramUpdate,
) -> TelegramInboundMessage | None:
    """Parse a private, non-empty Telegram text message."""

    message = update.message

    if (
        message is None
        or message.chat.type != "private"
        or message.sender is None
        or message.sender.is_bot
        or message.text is None
        or not message.text.strip()
    ):
        return None

    text = message.text.strip()

    return TelegramInboundMessage(
        update_id=str(
            update.update_id
        ),
        chat_id=message.chat.id,
        user_id=message.sender.id,
        message_id=message.message_id,
        text=text,
        language=cast(
            "SupportedLanguage",
            _language(
                message.sender.language_code,
                text,
            ),
        ),
        command=_command(text),
    )


def parse_telegram_callback(
    update: TelegramUpdate,
) -> TelegramInboundCallback | None:
    """Parse a private inline-button callback query."""

    callback = update.callback_query

    if (
        callback is None
        or callback.sender.is_bot
        or callback.message is None
        or callback.message.chat.type != "private"
        or callback.data is None
        or not callback.data.strip()
    ):
        return None

    callback_data = callback.data.strip()

    return TelegramInboundCallback(
        update_id=str(
            update.update_id
        ),
        callback_query_id=callback.id,
        chat_id=callback.message.chat.id,
        user_id=callback.sender.id,
        message_id=callback.message.message_id,
        data=callback_data,
        language=cast(
            "SupportedLanguage",
            _language(
                callback.sender.language_code,
                callback_data,
            ),
        ),
    )


class TelegramWebhookCoordinator:
    """Coordinate Telegram updates without exposing Bot API details."""

    def __init__(
        self,
        processor: TelegramGuestProcessor,
        sender: TelegramSender,
    ) -> None:
        self._processor = processor
        self._sender = sender

    async def handle(
        self,
        update: TelegramUpdate,
        *,
        correlation_id: str,
    ) -> TelegramWebhookResult:
        """Process a callback query or regular text message."""

        callback = parse_telegram_callback(
            update
        )

        if callback is not None:
            await self._sender.answer_callback_query(
                callback_query_id=(
                    callback.callback_query_id
                ),
            )

            reply = (
                await self._processor.process_callback(
                    callback,
                    correlation_id=correlation_id,
                )
            )

            if reply.duplicate:
                return TelegramWebhookResult(
                    status="duplicate",
                    update_id=callback.update_id,
                )

            await self._send_reply(
                chat_id=callback.chat_id,
                reply=reply,
            )

            return TelegramWebhookResult(
                status="processed",
                update_id=callback.update_id,
            )

        inbound = parse_telegram_update(
            update
        )

        if inbound is None:
            return TelegramWebhookResult(
                status="ignored",
                update_id=str(
                    update.update_id
                ),
            )

        reply = await self._processor.process(
            inbound,
            correlation_id=correlation_id,
        )

        if reply.duplicate:
            return TelegramWebhookResult(
                status="duplicate",
                update_id=inbound.update_id,
            )

        await self._send_reply(
            chat_id=inbound.chat_id,
            reply=reply,
        )

        return TelegramWebhookResult(
            status="processed",
            update_id=inbound.update_id,
        )

    async def _send_reply(
        self,
        *,
        chat_id: int,
        reply: TelegramGuestReply,
    ) -> None:
        """Validate and deliver one Telegram reply."""

        if len(reply.text) > 4096:
            raise TelegramDeliveryError(
                "Telegram reply exceeds 4096 characters"
            )

        await self._sender.send_message(
            chat_id=chat_id,
            text=reply.text,
            reply_markup=reply.reply_markup,
        )