"""Provider-neutral conversation snapshots and validated structured state."""

from datetime import date, datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from hotel_bot.domain.conversation.enums import (
    ActiveWorkflow,
    ChannelUpdateStatus,
    ConversationStatus,
    MessageDirection,
)

SupportedLanguage = Literal["ar", "en"]


class ConversationState(BaseModel):
    """Small operational state safe to retain without storing secrets or free-form prose."""

    model_config = ConfigDict(extra="forbid")

    language: SupportedLanguage = "ar"
    check_in: date | None = None
    check_out: date | None = None
    adults: int | None = Field(default=None, ge=1, le=20)
    children: int | None = Field(default=None, ge=0, le=20)
    room_type_code: str | None = Field(default=None, min_length=1, max_length=32)
    masked_booking_reference: str | None = Field(default=None, min_length=3, max_length=32)
    room_number: str | None = Field(default=None, min_length=1, max_length=16)
    service_category: str | None = Field(default=None, min_length=1, max_length=64)
    service_description: str | None = Field(default=None, min_length=1, max_length=1000)
    active_request_tracking_code: str | None = Field(default=None, min_length=3, max_length=32)
    active_workflow: ActiveWorkflow | None = None


class MessageSnapshot(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: UUID
    conversation_id: UUID
    sequence_number: int = Field(ge=1)
    direction: MessageDirection
    text: str
    language: SupportedLanguage
    correlation_id: str
    created_at: datetime
    redacted_at: datetime | None = None


class ConversationSnapshot(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: UUID
    guest_id: UUID
    channel: str
    status: ConversationStatus
    language: SupportedLanguage
    state: ConversationState
    summary: str | None
    started_at: datetime
    last_activity_at: datetime


class ChannelUpdateSnapshot(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: UUID
    channel: str
    external_update_id: str
    payload_fingerprint: str
    guest_id: UUID
    conversation_id: UUID | None
    inbound_message_id: UUID | None
    response_message_id: UUID | None
    correlation_id: str
    status: ChannelUpdateStatus


class ConversationTurn(BaseModel):
    model_config = ConfigDict(frozen=True)

    inbound: MessageSnapshot
    outbound: MessageSnapshot


class ContextEnvelope(BaseModel):
    """Bounded context that a later LLM adapter can serialize."""

    model_config = ConfigDict(frozen=True)

    state: ConversationState
    current_message: MessageSnapshot
    turns: tuple[ConversationTurn, ...]
    evidence: tuple[str, ...]
    summary: str | None
    estimated_tokens: int
    truncated: bool


class InboundMessageResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    conversation: ConversationSnapshot
    message: MessageSnapshot
    duplicate: bool


class RetentionCleanupResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    redacted_messages: int
    affected_conversations: int
    cutoff: datetime
    has_more: bool
