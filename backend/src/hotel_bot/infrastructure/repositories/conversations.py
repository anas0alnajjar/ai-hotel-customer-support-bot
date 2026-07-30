"""SQLAlchemy adapter for atomic conversation and retention operations."""

from collections import Counter
from datetime import datetime
from typing import cast
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from hotel_bot.domain.conversation.enums import (
    ChannelUpdateStatus,
    ConversationStatus,
    MessageDirection,
)
from hotel_bot.domain.conversation.errors import ConversationError, IdempotencyConflict
from hotel_bot.domain.conversation.models import (
    ChannelUpdateSnapshot,
    ConversationSnapshot,
    ConversationState,
    MessageSnapshot,
    RetentionCleanupResult,
    SupportedLanguage,
)
from hotel_bot.persistence.enums import ActorType
from hotel_bot.persistence.models import (
    AuditEvent,
    ChannelUpdate,
    Conversation,
    Guest,
    Message,
)


class SQLAlchemyConversationRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_guest_preferred_language(self, identity_hash: str) -> SupportedLanguage | None:
        value = await self._session.scalar(
            select(Guest.preferred_language)
            .where(Guest.telegram_user_hash == identity_hash)
            .limit(1)
        )
        return cast(SupportedLanguage, value) if value in {"ar", "en"} else None

    async def get_or_create_guest(self, identity_hash: str, language: SupportedLanguage) -> UUID:
        row = await self._session.scalar(
            select(Guest)
            .where(Guest.telegram_user_hash == identity_hash)
            .with_for_update()
            .limit(1)
        )
        if row is None:
            candidate = Guest(telegram_user_hash=identity_hash, preferred_language=language)
            try:
                async with self._session.begin_nested():
                    self._session.add(candidate)
                    await self._session.flush()
            except IntegrityError:
                row = await self._session.scalar(
                    select(Guest)
                    .where(Guest.telegram_user_hash == identity_hash)
                    .with_for_update()
                    .limit(1)
                )
            else:
                row = candidate
        if row is None:
            raise ConversationError(
                "guest_persistence_failed", "guest identity could not be stored"
            )
        row.preferred_language = language
        await self._session.flush()
        return row.id

    async def reserve_channel_update(
        self,
        *,
        channel: str,
        external_update_id: str,
        fingerprint: str,
        guest_id: UUID,
        correlation_id: str,
    ) -> tuple[ChannelUpdateSnapshot, bool]:
        row = await self._session.scalar(
            select(ChannelUpdate)
            .where(
                ChannelUpdate.channel == channel,
                ChannelUpdate.external_update_id == external_update_id,
            )
            .with_for_update()
            .limit(1)
        )
        if row is not None:
            return self._map_channel_update(row), False

        candidate = ChannelUpdate(
            channel=channel,
            external_update_id=external_update_id,
            payload_fingerprint=fingerprint,
            guest_id=guest_id,
            correlation_id=correlation_id,
            status=ChannelUpdateStatus.PROCESSING,
        )
        try:
            async with self._session.begin_nested():
                self._session.add(candidate)
                await self._session.flush()
        except IntegrityError:
            row = await self._session.scalar(
                select(ChannelUpdate)
                .where(
                    ChannelUpdate.channel == channel,
                    ChannelUpdate.external_update_id == external_update_id,
                )
                .with_for_update()
                .limit(1)
            )
            if row is None:
                raise ConversationError(
                    "channel_update_persistence_failed", "channel update could not be reserved"
                ) from None
            return self._map_channel_update(row), False
        return self._map_channel_update(candidate), True

    async def get_or_start_conversation(
        self,
        *,
        guest_id: UUID,
        channel: str,
        language: SupportedLanguage,
        now: datetime,
        inactive_before: datetime,
        force_new: bool,
    ) -> ConversationSnapshot:
        guest = await self._session.get(Guest, guest_id, with_for_update=True)
        if guest is None:
            raise ConversationError("guest_not_found", "guest identity was not found")

        open_rows = (
            await self._session.scalars(
                select(Conversation)
                .where(
                    Conversation.guest_id == guest_id,
                    Conversation.channel == channel,
                    Conversation.status == ConversationStatus.OPEN,
                )
                .order_by(Conversation.last_activity_at.desc(), Conversation.started_at.desc())
                .with_for_update()
            )
        ).all()
        reusable = open_rows[0] if open_rows else None
        if reusable is not None and not force_new and reusable.last_activity_at >= inactive_before:
            state = ConversationState.model_validate(
                reusable.context_state_json or {"language": language}
            ).model_copy(update={"language": language})
            reusable.language = language
            reusable.context_state_json = state.model_dump(mode="json", exclude_none=True)
            await self._session.flush()
            return self._map_conversation(reusable)

        for row in open_rows:
            row.status = ConversationStatus.CLOSED
            row.closed_at = now

        state = ConversationState(language=language)
        created = Conversation(
            guest_id=guest_id,
            channel=channel,
            status=ConversationStatus.OPEN,
            language=language,
            context_state_json=state.model_dump(mode="json", exclude_none=True),
            started_at=now,
            last_activity_at=now,
        )
        self._session.add(created)
        await self._session.flush()
        return self._map_conversation(created)

    async def append_message(
        self,
        *,
        conversation_id: UUID,
        direction: MessageDirection,
        text: str,
        language: SupportedLanguage,
        correlation_id: str,
        now: datetime,
    ) -> MessageSnapshot:
        conversation = await self._session.scalar(
            select(Conversation)
            .where(Conversation.id == conversation_id)
            .with_for_update()
            .limit(1)
        )
        if conversation is None or conversation.status is ConversationStatus.CLOSED:
            raise ConversationError("conversation_closed", "conversation is not open")
        last_sequence = await self._session.scalar(
            select(func.max(Message.sequence_number)).where(
                Message.conversation_id == conversation_id
            )
        )
        row = Message(
            conversation_id=conversation_id,
            sequence_number=int(last_sequence or 0) + 1,
            direction=direction,
            text=text,
            language=language,
            correlation_id=correlation_id,
            created_at=now,
        )
        conversation.last_activity_at = now
        conversation.language = language
        self._session.add(row)
        await self._session.flush()
        return self._map_message(row)

    async def link_inbound_update(
        self, update_id: UUID, conversation_id: UUID, message_id: UUID
    ) -> None:
        row = await self._session.scalar(
            select(ChannelUpdate).where(ChannelUpdate.id == update_id).with_for_update().limit(1)
        )
        if row is None:
            raise ConversationError("external_update_not_found", "external update was not found")
        row.conversation_id = conversation_id
        row.inbound_message_id = message_id
        await self._session.flush()

    async def complete_channel_update(
        self, update_id: UUID, response_message_id: UUID, completed_at: datetime
    ) -> None:
        row = await self._session.scalar(
            select(ChannelUpdate).where(ChannelUpdate.id == update_id).with_for_update().limit(1)
        )
        if row is None:
            raise ConversationError("external_update_not_found", "external update was not found")
        if row.response_message_id is not None and row.response_message_id != response_message_id:
            raise IdempotencyConflict(
                "external_update_response_conflict", "external update already has a response"
            )
        row.response_message_id = response_message_id
        row.status = ChannelUpdateStatus.COMPLETED
        row.completed_at = completed_at
        await self._session.flush()

    async def get_message(self, message_id: UUID) -> MessageSnapshot | None:
        row = await self._session.get(Message, message_id)
        return self._map_message(row) if row else None

    async def get_conversation(self, conversation_id: UUID) -> ConversationSnapshot | None:
        row = await self._session.get(Conversation, conversation_id)
        return self._map_conversation(row) if row else None

    async def get_channel_update(
        self, channel: str, external_update_id: str
    ) -> ChannelUpdateSnapshot | None:
        row = await self._session.scalar(
            select(ChannelUpdate)
            .where(
                ChannelUpdate.channel == channel,
                ChannelUpdate.external_update_id == external_update_id,
            )
            .with_for_update()
            .limit(1)
        )
        return self._map_channel_update(row) if row else None

    async def list_messages(self, conversation_id: UUID) -> tuple[MessageSnapshot, ...]:
        rows = (
            await self._session.scalars(
                select(Message)
                .where(Message.conversation_id == conversation_id)
                .order_by(Message.sequence_number)
            )
        ).all()
        return tuple(self._map_message(row) for row in rows)

    async def update_state(
        self, conversation_id: UUID, state: ConversationState
    ) -> ConversationSnapshot:
        row = await self._session.scalar(
            select(Conversation)
            .where(Conversation.id == conversation_id)
            .with_for_update()
            .limit(1)
        )
        if row is None or row.status is ConversationStatus.CLOSED:
            raise ConversationError("conversation_closed", "conversation is not open")
        row.context_state_json = state.model_dump(mode="json", exclude_none=True)
        row.language = state.language
        await self._session.flush()
        return self._map_conversation(row)

    async def redact_message(
        self,
        message_id: UUID,
        *,
        replacement: str,
        now: datetime,
    ) -> MessageSnapshot:
        row = await self._session.scalar(
            select(Message)
            .where(Message.id == message_id)
            .with_for_update()
            .limit(1)
        )
        if row is None:
            raise ConversationError(
                "message_not_found",
                "message was not found",
            )
        row.text = replacement
        row.redacted_at = now
        row.retention_action = "verification_redacted"
        await self._session.flush()
        return self._map_message(row)

    async def redact_expired_messages(
        self,
        *,
        cutoff: datetime,
        now: datetime,
        batch_size: int,
        correlation_id: str,
    ) -> RetentionCleanupResult:
        rows = (
            await self._session.scalars(
                select(Message)
                .where(Message.created_at < cutoff, Message.redacted_at.is_(None))
                .order_by(Message.created_at, Message.id)
                .limit(batch_size)
                .with_for_update(skip_locked=True)
            )
        ).all()
        conversation_ids = {row.conversation_id for row in rows}
        direction_counts = Counter(MessageDirection(row.direction).value for row in rows)
        for row in rows:
            row.text = "[redacted:retention]"
            row.redacted_at = now
            row.retention_action = "anonymized"

        if conversation_ids:
            conversations = (
                await self._session.scalars(
                    select(Conversation)
                    .where(Conversation.id.in_(conversation_ids))
                    .with_for_update()
                )
            ).all()
            for conversation in conversations:
                conversation.summary = None
                conversation.summary_through_message_id = None

        self._session.add(
            AuditEvent(
                actor_type=ActorType.SYSTEM,
                actor_id=None,
                action="conversation_retention_cleanup",
                resource_type="message",
                resource_id=None,
                metadata_redacted={
                    "policy_version": "1.0",
                    "cutoff": cutoff.isoformat(),
                    "message_count": len(rows),
                    "conversation_count": len(conversation_ids),
                    "direction_counts": dict(direction_counts),
                    "batch_limit": batch_size,
                },
                correlation_id=correlation_id,
                created_at=now,
            )
        )

        await self._session.flush()
        remaining = await self._session.scalar(
            select(Message.id)
            .where(Message.created_at < cutoff, Message.redacted_at.is_(None))
            .limit(1)
        )
        return RetentionCleanupResult(
            redacted_messages=len(rows),
            affected_conversations=len(conversation_ids),
            cutoff=cutoff,
            has_more=remaining is not None,
        )

    @staticmethod
    def _map_conversation(row: Conversation) -> ConversationSnapshot:
        language = cast(SupportedLanguage, row.language)
        return ConversationSnapshot(
            id=row.id,
            guest_id=row.guest_id,
            channel=row.channel,
            status=ConversationStatus(row.status),
            language=language,
            state=ConversationState.model_validate(
                row.context_state_json or {"language": language}
            ),
            summary=row.summary,
            started_at=row.started_at,
            last_activity_at=row.last_activity_at,
        )

    @staticmethod
    def _map_message(row: Message) -> MessageSnapshot:
        return MessageSnapshot(
            id=row.id,
            conversation_id=row.conversation_id,
            sequence_number=row.sequence_number,
            direction=MessageDirection(row.direction),
            text=row.text,
            language=cast(SupportedLanguage, row.language),
            correlation_id=row.correlation_id,
            created_at=row.created_at,
            redacted_at=row.redacted_at,
        )

    @staticmethod
    def _map_channel_update(row: ChannelUpdate) -> ChannelUpdateSnapshot:
        return ChannelUpdateSnapshot(
            id=row.id,
            channel=row.channel,
            external_update_id=row.external_update_id,
            payload_fingerprint=row.payload_fingerprint,
            guest_id=row.guest_id,
            conversation_id=row.conversation_id,
            inbound_message_id=row.inbound_message_id,
            response_message_id=row.response_message_id,
            correlation_id=row.correlation_id,
            status=ChannelUpdateStatus(row.status),
        )
