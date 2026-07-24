"""Authoritative relational schema for the hotel support platform."""

from datetime import date, datetime
from enum import StrEnum
from typing import Any
from uuid import UUID

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy import (
    text as sql_text,
)
from sqlalchemy.dialects.mysql import LONGTEXT
from sqlalchemy.orm import Mapped, mapped_column

from hotel_bot.domain.hotel.enums import (
    BookingStatus,
    RoomOperationalStatus,
    ServiceRequestStatus,
    ServiceRequestType,
    Urgency,
)
from hotel_bot.persistence.base import Base
from hotel_bot.persistence.enums import (
    ActorType,
    AdminRole,
    AdminStatus,
    ChannelUpdateStatus,
    ConversationStatus,
    EscalationStatus,
    EvaluationStatus,
    FeedbackSource,
    IndexStatus,
    KnowledgeStatus,
    LLMRunStatus,
    MessageDirection,
    ToolExecutionStatus,
)
from hotel_bot.persistence.mixins import TimestampMixin, UUIDPrimaryKeyMixin


def enum_type[EnumT: StrEnum](enum_class: type[EnumT], name: str) -> Enum:
    """Create a portable, validated string enum with an explicit CHECK constraint."""

    def values(cls: type[EnumT]) -> list[str]:
        return [member.value for member in cls]

    return Enum(
        enum_class,
        name=name,
        native_enum=False,
        create_constraint=True,
        validate_strings=True,
        values_callable=values,
        length=max(len(member.value) for member in enum_class),
    )


class AdminUser(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "admin_users"

    email: Mapped[str] = mapped_column(String(320), nullable=False, unique=True)
    username: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[AdminRole] = mapped_column(enum_type(AdminRole, "admin_role"), nullable=False)
    status: Mapped[AdminStatus] = mapped_column(
        enum_type(AdminStatus, "admin_status"),
        nullable=False,
        default=AdminStatus.ACTIVE,
        server_default=AdminStatus.ACTIVE.value,
    )
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime())


class Guest(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "guests"

    telegram_user_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    preferred_language: Mapped[str] = mapped_column(
        String(8), nullable=False, default="ar", server_default="ar"
    )


class Conversation(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "conversations"
    __table_args__ = (
        Index("ix_conversations_guest_status", "guest_id", "status"),
        Index("ix_conversations_status_last_activity", "status", "last_activity_at"),
    )

    guest_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("guests.id", ondelete="RESTRICT"), nullable=False
    )
    channel: Mapped[str] = mapped_column(String(32), nullable=False, server_default="telegram")
    status: Mapped[ConversationStatus] = mapped_column(
        enum_type(ConversationStatus, "conversation_status"),
        nullable=False,
        default=ConversationStatus.OPEN,
        server_default=ConversationStatus.OPEN.value,
    )
    language: Mapped[str] = mapped_column(String(8), nullable=False, server_default="ar")
    summary: Mapped[str | None] = mapped_column(Text())
    context_state_json: Mapped[dict[str, Any] | None] = mapped_column(JSON())
    summary_through_message_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey(
            "messages.id",
            name="fk_conversations_summary_message",
            use_alter=True,
            ondelete="SET NULL",
        ),
    )
    started_at: Mapped[datetime] = mapped_column(
        DateTime(), nullable=False, server_default=sql_text("CURRENT_TIMESTAMP")
    )
    last_activity_at: Mapped[datetime] = mapped_column(
        DateTime(), nullable=False, server_default=sql_text("CURRENT_TIMESTAMP")
    )
    closed_at: Mapped[datetime | None] = mapped_column(DateTime())


class Message(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "messages"
    __table_args__ = (
        CheckConstraint(
            "confidence IS NULL OR (confidence >= 0 AND confidence <= 1)",
            name="confidence_range",
        ),
        CheckConstraint("sequence_number > 0", name="sequence_number_positive"),
        UniqueConstraint("conversation_id", "sequence_number", name="uq_messages_conversation_seq"),
        Index("ix_messages_conversation_created", "conversation_id", "created_at"),
        Index("ix_messages_correlation_id", "correlation_id"),
    )

    conversation_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False
    )
    sequence_number: Mapped[int] = mapped_column(Integer(), nullable=False)
    direction: Mapped[MessageDirection] = mapped_column(
        enum_type(MessageDirection, "message_direction"), nullable=False
    )
    text: Mapped[str] = mapped_column(LONGTEXT(), nullable=False)
    language: Mapped[str] = mapped_column(String(8), nullable=False)
    intent: Mapped[str | None] = mapped_column(String(64))
    confidence: Mapped[float | None] = mapped_column(Numeric(5, 4))
    classifier_version: Mapped[str | None] = mapped_column(String(64))
    correlation_id: Mapped[str] = mapped_column(String(128), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(), nullable=False, server_default=sql_text("CURRENT_TIMESTAMP")
    )
    redacted_at: Mapped[datetime | None] = mapped_column(DateTime())
    retention_action: Mapped[str | None] = mapped_column(String(32))


class ChannelUpdate(UUIDPrimaryKeyMixin, Base):
    """Idempotency ledger for externally delivered channel updates."""

    __tablename__ = "channel_updates"
    __table_args__ = (
        UniqueConstraint("channel", "external_update_id", name="uq_channel_updates_external"),
        Index("ix_channel_updates_correlation_id", "correlation_id"),
    )

    channel: Mapped[str] = mapped_column(String(32), nullable=False)
    external_update_id: Mapped[str] = mapped_column(String(128), nullable=False)
    payload_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    guest_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("guests.id", ondelete="RESTRICT"), nullable=False
    )
    conversation_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("conversations.id", ondelete="SET NULL")
    )
    inbound_message_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("messages.id", ondelete="SET NULL")
    )
    response_message_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("messages.id", ondelete="SET NULL")
    )
    correlation_id: Mapped[str] = mapped_column(String(128), nullable=False)
    status: Mapped[ChannelUpdateStatus] = mapped_column(
        enum_type(ChannelUpdateStatus, "channel_update_status"),
        nullable=False,
        default=ChannelUpdateStatus.PROCESSING,
        server_default=ChannelUpdateStatus.PROCESSING.value,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(), nullable=False, server_default=sql_text("CURRENT_TIMESTAMP")
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime())


class LLMRun(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "llm_runs"
    __table_args__ = (
        CheckConstraint(
            "input_tokens IS NULL OR input_tokens >= 0", name="input_tokens_nonnegative"
        ),
        CheckConstraint(
            "output_tokens IS NULL OR output_tokens >= 0", name="output_tokens_nonnegative"
        ),
        CheckConstraint(
            "thought_tokens IS NULL OR thought_tokens >= 0", name="thought_tokens_nonnegative"
        ),
        CheckConstraint(
            "total_tokens IS NULL OR total_tokens >= 0", name="total_tokens_nonnegative"
        ),
        CheckConstraint(
            "estimated_cost_usd IS NULL OR estimated_cost_usd >= 0",
            name="estimated_cost_nonnegative",
        ),
        CheckConstraint("latency_ms >= 0", name="latency_nonnegative"),
    )

    message_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("messages.id", ondelete="CASCADE"), nullable=False
    )
    provider: Mapped[str] = mapped_column(String(64), nullable=False)
    model: Mapped[str] = mapped_column(String(128), nullable=False)
    prompt_version: Mapped[str] = mapped_column(String(64), nullable=False)
    request_kind: Mapped[str] = mapped_column(String(32), nullable=False)
    input_tokens: Mapped[int | None] = mapped_column(Integer())
    output_tokens: Mapped[int | None] = mapped_column(Integer())
    thought_tokens: Mapped[int | None] = mapped_column(Integer())
    total_tokens: Mapped[int | None] = mapped_column(Integer())
    estimated_cost_usd: Mapped[float | None] = mapped_column(Numeric(12, 6))
    provider_request_id: Mapped[str | None] = mapped_column(String(128))
    latency_ms: Mapped[int] = mapped_column(Integer(), nullable=False)
    status: Mapped[LLMRunStatus] = mapped_column(
        enum_type(LLMRunStatus, "llm_run_status"), nullable=False
    )
    error_code: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(), nullable=False, server_default=sql_text("CURRENT_TIMESTAMP")
    )


class KnowledgeDocument(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "knowledge_documents"

    title: Mapped[str] = mapped_column(String(255), nullable=False)
    language: Mapped[str] = mapped_column(String(8), nullable=False)
    source_format: Mapped[str] = mapped_column(
        String(16), nullable=False, server_default="plain_text"
    )
    status: Mapped[KnowledgeStatus] = mapped_column(
        enum_type(KnowledgeStatus, "knowledge_status"),
        nullable=False,
        default=KnowledgeStatus.DRAFT,
        server_default=KnowledgeStatus.DRAFT.value,
    )
    current_revision_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey(
            "knowledge_revisions.id",
            name="fk_knowledge_documents_current_revision",
            use_alter=True,
            ondelete="SET NULL",
        ),
    )


class KnowledgeRevision(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "knowledge_revisions"
    __table_args__ = (
        UniqueConstraint("document_id", "version", name="uq_knowledge_revision_version"),
        UniqueConstraint("document_id", "checksum", name="uq_knowledge_revision_checksum"),
        CheckConstraint("version > 0", name="version_positive"),
    )

    document_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("knowledge_documents.id", ondelete="CASCADE"),
        nullable=False,
    )
    content: Mapped[str] = mapped_column(LONGTEXT(), nullable=False)
    checksum: Mapped[str] = mapped_column(String(64), nullable=False)
    version: Mapped[int] = mapped_column(Integer(), nullable=False)
    created_by: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("admin_users.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(), nullable=False, server_default=sql_text("CURRENT_TIMESTAMP")
    )


class IndexVersion(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "index_versions"
    __table_args__ = (
        CheckConstraint("dimension > 0", name="dimension_positive"),
        CheckConstraint("document_count >= 0", name="document_count_nonnegative"),
        CheckConstraint("chunk_count >= 0", name="chunk_count_nonnegative"),
    )

    embedding_model: Mapped[str] = mapped_column(String(255), nullable=False)
    dimension: Mapped[int] = mapped_column(Integer(), nullable=False)
    chunk_config: Mapped[dict[str, Any]] = mapped_column(JSON(), nullable=False)
    checksum: Mapped[str | None] = mapped_column(String(64), unique=True)
    artifact_path: Mapped[str | None] = mapped_column(String(512))
    document_count: Mapped[int] = mapped_column(Integer(), nullable=False, server_default="0")
    chunk_count: Mapped[int] = mapped_column(Integer(), nullable=False, server_default="0")
    build_error: Mapped[str | None] = mapped_column(Text())
    status: Mapped[IndexStatus] = mapped_column(
        enum_type(IndexStatus, "index_status"), nullable=False
    )
    activated_at: Mapped[datetime | None] = mapped_column(DateTime())
    created_at: Mapped[datetime] = mapped_column(
        DateTime(), nullable=False, server_default=sql_text("CURRENT_TIMESTAMP")
    )


class KnowledgeChunk(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "knowledge_chunks"
    __table_args__ = (
        UniqueConstraint("index_version_id", "faiss_vector_id", name="uq_chunk_faiss_vector"),
        UniqueConstraint(
            "index_version_id", "revision_id", "chunk_index", name="uq_chunk_position"
        ),
        CheckConstraint("chunk_index >= 0", name="chunk_index_nonnegative"),
        CheckConstraint("faiss_vector_id >= 0", name="faiss_vector_id_nonnegative"),
    )

    revision_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("knowledge_revisions.id", ondelete="CASCADE"), nullable=False
    )
    index_version_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("index_versions.id", ondelete="CASCADE"), nullable=False
    )
    chunk_index: Mapped[int] = mapped_column(Integer(), nullable=False)
    text: Mapped[str] = mapped_column(LONGTEXT(), nullable=False)
    metadata_json: Mapped[dict[str, Any] | None] = mapped_column(JSON())
    embedding_config_id: Mapped[str] = mapped_column(String(128), nullable=False)
    faiss_vector_id: Mapped[int] = mapped_column(Integer(), nullable=False)


class RoomType(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "room_types"
    __table_args__ = (
        CheckConstraint("capacity_adults > 0", name="adult_capacity_positive"),
        CheckConstraint("capacity_children >= 0", name="child_capacity_nonnegative"),
    )

    code: Mapped[str] = mapped_column(String(32), nullable=False, unique=True)
    name_json: Mapped[dict[str, str]] = mapped_column(JSON(), nullable=False)
    description_json: Mapped[dict[str, str]] = mapped_column(JSON(), nullable=False)
    capacity_adults: Mapped[int] = mapped_column(Integer(), nullable=False)
    capacity_children: Mapped[int] = mapped_column(Integer(), nullable=False, server_default="0")
    amenities_json: Mapped[list[str]] = mapped_column(JSON(), nullable=False)
    active: Mapped[bool] = mapped_column(Boolean(), nullable=False, server_default=sql_text("1"))


class Room(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "rooms"

    room_number: Mapped[str] = mapped_column(String(16), nullable=False, unique=True)
    room_type_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("room_types.id", ondelete="RESTRICT"), nullable=False
    )
    floor: Mapped[int] = mapped_column(Integer(), nullable=False)
    operational_status: Mapped[RoomOperationalStatus] = mapped_column(
        enum_type(RoomOperationalStatus, "room_operational_status"),
        nullable=False,
        default=RoomOperationalStatus.AVAILABLE,
        server_default=RoomOperationalStatus.AVAILABLE.value,
    )


class Booking(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "bookings"
    __table_args__ = (
        CheckConstraint("check_out > check_in", name="date_range_valid"),
        CheckConstraint("adults > 0", name="adults_positive"),
        CheckConstraint("children >= 0", name="children_nonnegative"),
        Index("ix_bookings_stay_status", "check_in", "check_out", "status"),
    )

    reference: Mapped[str] = mapped_column(String(32), nullable=False, unique=True)
    guest_verification_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    guest_name_masked: Mapped[str] = mapped_column(String(255), nullable=False)
    check_in: Mapped[date] = mapped_column(Date(), nullable=False)
    check_out: Mapped[date] = mapped_column(Date(), nullable=False)
    room_type_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("room_types.id", ondelete="RESTRICT"), nullable=False
    )
    room_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("rooms.id", ondelete="SET NULL")
    )
    adults: Mapped[int] = mapped_column(Integer(), nullable=False)
    children: Mapped[int] = mapped_column(Integer(), nullable=False, server_default="0")
    status: Mapped[BookingStatus] = mapped_column(
        enum_type(BookingStatus, "booking_status"), nullable=False
    )


class ServiceRequest(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "service_requests"
    __table_args__ = (Index("ix_service_requests_status_created", "status", "created_at"),)

    tracking_code: Mapped[str] = mapped_column(String(32), nullable=False, unique=True)
    type: Mapped[ServiceRequestType] = mapped_column(
        enum_type(ServiceRequestType, "service_request_type"), nullable=False
    )
    category: Mapped[str] = mapped_column(String(64), nullable=False)
    room_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("rooms.id", ondelete="RESTRICT"), nullable=False
    )
    booking_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("bookings.id", ondelete="SET NULL")
    )
    description: Mapped[str] = mapped_column(Text(), nullable=False)
    urgency: Mapped[Urgency] = mapped_column(enum_type(Urgency, "urgency"), nullable=False)
    status: Mapped[ServiceRequestStatus] = mapped_column(
        enum_type(ServiceRequestStatus, "service_request_status"),
        nullable=False,
        default=ServiceRequestStatus.OPEN,
        server_default=ServiceRequestStatus.OPEN.value,
    )
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False, unique=True)
    requested_by_guest_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("guests.id", ondelete="SET NULL")
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime())


class ToolExecution(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "tool_executions"
    __table_args__ = (
        CheckConstraint("latency_ms >= 0", name="latency_nonnegative"),
        Index("ix_tool_executions_correlation_id", "correlation_id"),
    )

    message_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("messages.id", ondelete="CASCADE"), nullable=False
    )
    tool_name: Mapped[str] = mapped_column(String(128), nullable=False)
    arguments_redacted: Mapped[dict[str, Any]] = mapped_column(JSON(), nullable=False)
    result_status: Mapped[ToolExecutionStatus] = mapped_column(
        enum_type(ToolExecutionStatus, "tool_execution_status"), nullable=False
    )
    result_redacted: Mapped[dict[str, Any] | None] = mapped_column(JSON())
    latency_ms: Mapped[int] = mapped_column(Integer(), nullable=False)
    correlation_id: Mapped[str] = mapped_column(String(128), nullable=False)
    error_code: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(), nullable=False, server_default=sql_text("CURRENT_TIMESTAMP")
    )


class Escalation(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "escalations"

    conversation_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False
    )
    reason: Mapped[str] = mapped_column(Text(), nullable=False)
    status: Mapped[EscalationStatus] = mapped_column(
        enum_type(EscalationStatus, "escalation_status"),
        nullable=False,
        default=EscalationStatus.OPEN,
        server_default=EscalationStatus.OPEN.value,
    )
    assigned_to: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("admin_users.id", ondelete="SET NULL")
    )
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime())


class Feedback(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "feedback"
    __table_args__ = (
        CheckConstraint("rating IS NULL OR (rating >= 1 AND rating <= 5)", name="rating_range"),
    )

    message_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("messages.id", ondelete="CASCADE"), nullable=False
    )
    source: Mapped[FeedbackSource] = mapped_column(
        enum_type(FeedbackSource, "feedback_source"), nullable=False
    )
    rating: Mapped[int | None] = mapped_column(Integer())
    label: Mapped[str | None] = mapped_column(String(64))
    comment: Mapped[str | None] = mapped_column(Text())
    created_at: Mapped[datetime] = mapped_column(
        DateTime(), nullable=False, server_default=sql_text("CURRENT_TIMESTAMP")
    )


class EvaluationRun(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "evaluation_runs"

    dataset_version: Mapped[str] = mapped_column(String(128), nullable=False)
    system_versions: Mapped[dict[str, Any]] = mapped_column(JSON(), nullable=False)
    metrics_json: Mapped[dict[str, Any] | None] = mapped_column(JSON())
    status: Mapped[EvaluationStatus] = mapped_column(
        enum_type(EvaluationStatus, "evaluation_status"),
        nullable=False,
        default=EvaluationStatus.PENDING,
        server_default=EvaluationStatus.PENDING.value,
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime())
    finished_at: Mapped[datetime | None] = mapped_column(DateTime())
    error_summary: Mapped[str | None] = mapped_column(Text())
    created_at: Mapped[datetime] = mapped_column(
        DateTime(), nullable=False, server_default=sql_text("CURRENT_TIMESTAMP")
    )


class AuditEvent(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "audit_events"
    __table_args__ = (
        Index("ix_audit_events_resource", "resource_type", "resource_id"),
        Index("ix_audit_events_correlation_id", "correlation_id"),
    )

    actor_type: Mapped[ActorType] = mapped_column(
        enum_type(ActorType, "audit_actor_type"), nullable=False
    )
    actor_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True))
    action: Mapped[str] = mapped_column(String(128), nullable=False)
    resource_type: Mapped[str] = mapped_column(String(64), nullable=False)
    resource_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True))
    metadata_redacted: Mapped[dict[str, Any] | None] = mapped_column(JSON())
    correlation_id: Mapped[str] = mapped_column(String(128), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(), nullable=False, server_default=sql_text("CURRENT_TIMESTAMP")
    )
