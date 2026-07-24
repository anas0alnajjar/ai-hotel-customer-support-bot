"""Conversation session, message, context, and retention use cases."""

import hashlib
import json
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Protocol, cast
from uuid import UUID

from hotel_bot.domain.conversation.context import build_context
from hotel_bot.domain.conversation.enums import MessageDirection
from hotel_bot.domain.conversation.errors import ConversationError, IdempotencyConflict
from hotel_bot.domain.conversation.models import (
    ChannelUpdateSnapshot,
    ContextEnvelope,
    ConversationSnapshot,
    ConversationState,
    InboundMessageResult,
    MessageSnapshot,
    RetentionCleanupResult,
    SupportedLanguage,
)


def utc_now_naive() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


class ConversationRepository(Protocol):
    async def get_guest_preferred_language(
        self, identity_hash: str
    ) -> SupportedLanguage | None: ...

    async def get_or_create_guest(
        self, identity_hash: str, language: SupportedLanguage
    ) -> UUID: ...

    async def reserve_channel_update(
        self,
        *,
        channel: str,
        external_update_id: str,
        fingerprint: str,
        guest_id: UUID,
        correlation_id: str,
    ) -> tuple[ChannelUpdateSnapshot, bool]: ...

    async def get_or_start_conversation(
        self,
        *,
        guest_id: UUID,
        channel: str,
        language: SupportedLanguage,
        now: datetime,
        inactive_before: datetime,
        force_new: bool,
    ) -> ConversationSnapshot: ...

    async def append_message(
        self,
        *,
        conversation_id: UUID,
        direction: MessageDirection,
        text: str,
        language: SupportedLanguage,
        correlation_id: str,
        now: datetime,
    ) -> MessageSnapshot: ...

    async def link_inbound_update(
        self, update_id: UUID, conversation_id: UUID, message_id: UUID
    ) -> None: ...

    async def complete_channel_update(
        self, update_id: UUID, response_message_id: UUID, completed_at: datetime
    ) -> None: ...

    async def get_message(self, message_id: UUID) -> MessageSnapshot | None: ...

    async def get_conversation(self, conversation_id: UUID) -> ConversationSnapshot | None: ...

    async def get_channel_update(
        self, channel: str, external_update_id: str
    ) -> ChannelUpdateSnapshot | None: ...

    async def list_messages(self, conversation_id: UUID) -> tuple[MessageSnapshot, ...]: ...

    async def update_state(
        self, conversation_id: UUID, state: ConversationState
    ) -> ConversationSnapshot: ...

    async def redact_expired_messages(
        self,
        *,
        cutoff: datetime,
        now: datetime,
        batch_size: int,
        correlation_id: str,
    ) -> RetentionCleanupResult: ...


def _normalize_language(value: str) -> SupportedLanguage:
    language = value.strip().lower()
    if language not in {"ar", "en"}:
        raise ConversationError("unsupported_language", "language must be 'ar' or 'en'")
    return cast(SupportedLanguage, language)


def _normalize_text(value: str) -> str:
    normalized = value.replace("\r\n", "\n").replace("\r", "\n").strip()
    if not normalized:
        raise ConversationError("empty_message", "message text cannot be empty")
    if len(normalized) > 20_000:
        raise ConversationError("message_too_long", "message text exceeds 20000 characters")
    return normalized


def _payload_fingerprint(
    *, channel: str, guest_identity_hash: str, text: str, language: SupportedLanguage
) -> str:
    payload = json.dumps(
        {
            "channel": channel,
            "guest_identity_hash": guest_identity_hash,
            "language": language,
            "text": text,
        },
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


class ConversationService:
    """Coordinate one atomic channel update without depending on Telegram or an LLM."""

    def __init__(
        self,
        repository: ConversationRepository,
        *,
        inactivity_minutes: int = 30,
        context_turns: int = 5,
        context_max_tokens: int = 3000,
        clock: Callable[[], datetime] = utc_now_naive,
    ) -> None:
        self._repository = repository
        self._inactivity = timedelta(minutes=inactivity_minutes)
        self._context_turns = context_turns
        self._context_max_tokens = context_max_tokens
        self._clock = clock

    async def preferred_language(
        self, identity_hash: str, fallback: SupportedLanguage
    ) -> SupportedLanguage:
        return await self._repository.get_guest_preferred_language(identity_hash) or fallback

    async def record_inbound(
        self,
        *,
        channel: str,
        external_update_id: str,
        guest_identity_hash: str,
        text: str,
        language: str,
        correlation_id: str,
        force_new_conversation: bool = False,
    ) -> InboundMessageResult:
        normalized_channel = channel.strip().lower()
        normalized_update_id = external_update_id.strip()
        normalized_hash = guest_identity_hash.strip().lower()
        normalized_correlation = correlation_id.strip()
        normalized_text = _normalize_text(text)
        normalized_language = _normalize_language(language)
        if not normalized_channel or not normalized_update_id or not normalized_correlation:
            raise ConversationError(
                "missing_message_metadata", "channel, update id, and correlation id are required"
            )
        if len(normalized_hash) != 64 or any(
            character not in "0123456789abcdef" for character in normalized_hash
        ):
            raise ConversationError(
                "invalid_guest_identity_hash", "guest identity must be a SHA-256 hex digest"
            )

        fingerprint = _payload_fingerprint(
            channel=normalized_channel,
            guest_identity_hash=normalized_hash,
            text=normalized_text,
            language=normalized_language,
        )
        guest_id = await self._repository.get_or_create_guest(normalized_hash, normalized_language)
        update, created = await self._repository.reserve_channel_update(
            channel=normalized_channel,
            external_update_id=normalized_update_id,
            fingerprint=fingerprint,
            guest_id=guest_id,
            correlation_id=normalized_correlation,
        )
        if not created:
            if update.payload_fingerprint != fingerprint:
                raise IdempotencyConflict(
                    "external_update_payload_conflict",
                    "external update id was already used for a different payload",
                )
            if update.inbound_message_id is None or update.conversation_id is None:
                raise ConversationError(
                    "external_update_incomplete",
                    "external update is currently incomplete and should be retried",
                )
            message = await self._repository.get_message(update.inbound_message_id)
            conversation = await self._repository.get_conversation(update.conversation_id)
            if message is None or conversation is None:
                raise ConversationError(
                    "external_update_inconsistent", "external update references missing records"
                )
            return InboundMessageResult(conversation=conversation, message=message, duplicate=True)

        now = self._clock()
        conversation = await self._repository.get_or_start_conversation(
            guest_id=guest_id,
            channel=normalized_channel,
            language=normalized_language,
            now=now,
            inactive_before=now - self._inactivity,
            force_new=force_new_conversation,
        )
        message = await self._repository.append_message(
            conversation_id=conversation.id,
            direction=MessageDirection.INBOUND,
            text=normalized_text,
            language=normalized_language,
            correlation_id=normalized_correlation,
            now=now,
        )
        await self._repository.link_inbound_update(update.id, conversation.id, message.id)
        return InboundMessageResult(conversation=conversation, message=message, duplicate=False)

    async def record_outbound(
        self,
        *,
        channel: str,
        external_update_id: str,
        text: str,
        language: str,
        correlation_id: str,
    ) -> MessageSnapshot:
        update = await self._repository.get_channel_update(
            channel.strip().lower(), external_update_id.strip()
        )
        if update is None or update.conversation_id is None:
            raise ConversationError("external_update_not_found", "external update was not found")
        if update.response_message_id is not None:
            existing = await self._repository.get_message(update.response_message_id)
            if existing is None:
                raise ConversationError(
                    "external_update_inconsistent", "response message record is missing"
                )
            return existing

        now = self._clock()
        message = await self._repository.append_message(
            conversation_id=update.conversation_id,
            direction=MessageDirection.OUTBOUND,
            text=_normalize_text(text),
            language=_normalize_language(language),
            correlation_id=correlation_id.strip(),
            now=now,
        )
        await self._repository.complete_channel_update(update.id, message.id, now)
        return message

    async def assemble_context(
        self,
        *,
        conversation_id: UUID,
        current_message_id: UUID,
        evidence: tuple[str, ...] = (),
    ) -> ContextEnvelope:
        conversation = await self._repository.get_conversation(conversation_id)
        current = await self._repository.get_message(current_message_id)
        if conversation is None or current is None or current.conversation_id != conversation_id:
            raise ConversationError("conversation_not_found", "conversation context was not found")
        history = await self._repository.list_messages(conversation_id)
        return build_context(
            state=conversation.state,
            current_message=current,
            history=history,
            summary=conversation.summary,
            evidence=evidence,
            max_turns=self._context_turns,
            max_tokens=self._context_max_tokens,
        )

    async def update_state(
        self, conversation_id: UUID, state: ConversationState
    ) -> ConversationSnapshot:
        return await self._repository.update_state(conversation_id, state)

    @staticmethod
    def help_text(language: str) -> str:
        if _normalize_language(language) == "ar":
            return (
                "أنا مساعد فندق نور الشام الافتراضي. أساعدك بمعلومات الفندق وأنواع الغرف "
                "والتوفر والتحقق من الحجز وخدمة الغرف والصيانة وتتبع الطلبات. العمليات "
                "محاكاة وليست حجزاً أو التزاماً حقيقياً. استخدم /new لمحادثة جديدة، "
                "/ar للعربية، /en للإنجليزية، و/help للمساعدة."
            )
        return (
            "I am the virtual assistant for Nour Al-Sham Hotel. I can help with hotel "
            "information, room types and availability, booking lookup, room service, "
            "maintenance, and request tracking. Operations are simulations, not real "
            "bookings or commitments. Use /new for a new conversation, /ar for Arabic, "
            "/en for English, and /help for help."
        )


class RetentionCleanupService:
    def __init__(
        self,
        repository: ConversationRepository,
        *,
        retention_days: int = 90,
        batch_size: int = 500,
        clock: Callable[[], datetime] = utc_now_naive,
    ) -> None:
        self._repository = repository
        self._retention = timedelta(days=retention_days)
        self._batch_size = batch_size
        self._clock = clock

    async def run(self, *, correlation_id: str) -> RetentionCleanupResult:
        now = self._clock()
        return await self._repository.redact_expired_messages(
            cutoff=now - self._retention,
            now=now,
            batch_size=self._batch_size,
            correlation_id=correlation_id.strip(),
        )
