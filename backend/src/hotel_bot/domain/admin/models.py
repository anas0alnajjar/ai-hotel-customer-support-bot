"""Typed administration projections independent from HTTP and SQLAlchemy."""

from datetime import date, datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from hotel_bot.domain.conversation.enums import ConversationStatus, MessageDirection
from hotel_bot.domain.hotel.enums import (
    BookingStatus,
    RoomOperationalStatus,
    ServiceRequestStatus,
    ServiceRequestType,
    Urgency,
)
from hotel_bot.domain.knowledge.enums import KnowledgeStatus, SourceFormat
from hotel_bot.persistence.enums import (
    AdminRole,
    EscalationStatus,
    EvaluationStatus,
    FeedbackSource,
    ToolExecutionStatus,
)


class AdminPrincipal(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: UUID
    email: str
    username: str
    role: AdminRole


class AdminCredential(BaseModel):
    model_config = ConfigDict(frozen=True)

    principal: AdminPrincipal
    password_hash: str


class AdminLoginResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    access_token: str
    expires_in: int
    principal: AdminPrincipal


class ConversationAdminItem(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: UUID
    guest_reference: str
    channel: str
    status: ConversationStatus
    language: str
    message_count: int
    last_message_preview: str | None
    latest_intent: str | None
    escalation_status: EscalationStatus | None
    started_at: datetime
    last_activity_at: datetime
    closed_at: datetime | None


class MessageAdminItem(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: UUID
    sequence_number: int
    direction: MessageDirection
    text: str
    language: str
    intent: str | None
    confidence: float | None
    classifier_version: str | None
    correlation_id: str
    created_at: datetime
    redacted: bool


class ToolEventAdminItem(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: UUID
    message_id: UUID
    tool_name: str
    arguments: dict[str, Any]
    result_status: ToolExecutionStatus
    result: dict[str, Any] | None
    latency_ms: int
    correlation_id: str
    error_code: str | None
    created_at: datetime


class FeedbackAdminItem(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: UUID
    message_id: UUID
    source: FeedbackSource
    rating: int | None
    label: str | None
    comment: str | None
    created_at: datetime


class EscalationAdminItem(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: UUID
    reason: str
    status: EscalationStatus
    assigned_to: UUID | None
    created_at: datetime
    updated_at: datetime
    resolved_at: datetime | None


class ConversationAdminDetail(BaseModel):
    model_config = ConfigDict(frozen=True)

    conversation: ConversationAdminItem
    messages: tuple[MessageAdminItem, ...]
    tool_events: tuple[ToolEventAdminItem, ...]
    feedback: tuple[FeedbackAdminItem, ...]
    escalations: tuple[EscalationAdminItem, ...]


class KnowledgeRevisionAdminItem(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: UUID
    version: int
    content: str
    checksum: str
    created_by: UUID | None
    created_at: datetime
    status: Literal["draft", "approved", "historical"]
    approved_at: datetime | None
    approved_by: UUID | None
    effective: bool
    indexed_in_faiss: bool
    editable: bool


class KnowledgeAdminItem(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: UUID
    title: str
    language: str
    source_format: SourceFormat
    status: KnowledgeStatus
    current_revision_id: UUID | None
    revision_count: int
    created_at: datetime
    updated_at: datetime


class KnowledgeAdminDetail(BaseModel):
    model_config = ConfigDict(frozen=True)

    document: KnowledgeAdminItem
    revisions: tuple[KnowledgeRevisionAdminItem, ...]
    retrieval_eligible: bool
    faiss_sync_status: Literal["synchronized", "needs_rebuild", "building"]
    active_index_id: UUID | None


class ServiceRequestAdminItem(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: UUID
    tracking_code: str
    request_type: ServiceRequestType
    category: str
    room_number: str
    description: str
    urgency: Urgency
    status: ServiceRequestStatus
    created_at: datetime
    updated_at: datetime
    completed_at: datetime | None


class EvaluationAdminItem(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: UUID
    dataset_version: str
    system_versions: dict[str, Any]
    metrics: dict[str, Any] | None
    status: EvaluationStatus
    started_at: datetime | None
    finished_at: datetime | None
    error_summary: str | None
    created_at: datetime


class RoomTypeAdminItem(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: UUID
    code: str
    name_ar: str
    name_en: str
    capacity_adults: int
    capacity_children: int
    nightly_rate_cents: int
    currency: str
    active: bool


class RoomAdminItem(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: UUID
    room_number: str
    room_type_id: UUID
    room_type_code: str
    floor: int
    operational_status: RoomOperationalStatus


class BookingAdminItem(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: UUID
    reference: str
    guest_name_masked: str
    check_in: date
    check_out: date
    room_type_id: UUID
    room_type_code: str
    room_id: UUID | None
    room_number: str | None
    adults: int
    children: int
    status: BookingStatus


class BookingMutationResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    booking: BookingAdminItem
    verification_code_once: str | None = None


class DemoCredentialItem(BaseModel):
    model_config = ConfigDict(frozen=True)

    booking_reference: str
    verification_code: str


class DemoCredentials(BaseModel):
    model_config = ConfigDict(frozen=True)

    label: str = "Demo data — not real guest credentials"
    dataset_version: str
    credentials: tuple[DemoCredentialItem, ...]


class Page(BaseModel):
    model_config = ConfigDict(frozen=True)

    items: tuple[Any, ...]
    page: int
    page_size: int
    total: int
    pages: int
