"""MySQL administration projections, security events, and controlled mutations."""

import secrets
from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any, Literal
from uuid import UUID

from sqlalchemy import and_, exists, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from hotel_bot.domain.admin.errors import (
    AdminResourceNotFoundError,
    AdminValidationError,
)
from hotel_bot.domain.admin.models import (
    AdminCredential,
    AdminPrincipal,
    BookingAdminItem,
    BookingMutationResult,
    ConversationAdminDetail,
    ConversationAdminItem,
    EscalationAdminItem,
    EvaluationAdminItem,
    FeedbackAdminItem,
    KnowledgeAdminDetail,
    KnowledgeAdminItem,
    KnowledgeRevisionAdminItem,
    MessageAdminItem,
    RoomAdminItem,
    RoomTypeAdminItem,
    ServiceRequestAdminItem,
    ToolEventAdminItem,
)
from hotel_bot.domain.admin.security import (
    mask_guest_reference,
    mask_tracking_code,
    redact_admin_text,
)
from hotel_bot.domain.conversation.enums import ConversationStatus, MessageDirection
from hotel_bot.domain.hotel.enums import (
    BookingStatus,
    RoomOperationalStatus,
    ServiceRequestStatus,
    ServiceRequestType,
    Urgency,
)
from hotel_bot.domain.hotel.policies import validate_status_transition
from hotel_bot.domain.hotel.security import hash_verification_value
from hotel_bot.domain.knowledge.enums import IndexStatus, KnowledgeStatus, SourceFormat
from hotel_bot.persistence.enums import (
    ActorType,
    AdminRole,
    AdminStatus,
    EscalationStatus,
    EvaluationStatus,
    FeedbackSource,
    LLMRunStatus,
    ToolExecutionStatus,
)
from hotel_bot.persistence.models import (
    AdminUser,
    AuditEvent,
    Booking,
    Conversation,
    Escalation,
    EvaluationRun,
    Feedback,
    Guest,
    IndexVersion,
    KnowledgeChunk,
    KnowledgeDocument,
    KnowledgeRevision,
    LLMRun,
    Message,
    Room,
    RoomType,
    ServiceRequest,
    ToolExecution,
)


def utc_now_naive() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def _actor_type(role: AdminRole) -> ActorType:
    return {
        AdminRole.ADMIN: ActorType.ADMIN,
        AdminRole.SUPPORT: ActorType.SUPPORT,
        AdminRole.EVALUATOR: ActorType.EVALUATOR,
    }[role]


class SQLAlchemyAdminRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def find_credential(self, identifier: str) -> AdminCredential | None:
        row = await self._session.scalar(
            select(AdminUser)
            .where(
                or_(
                    func.lower(AdminUser.email) == identifier,
                    func.lower(AdminUser.username) == identifier,
                ),
                AdminUser.status == AdminStatus.ACTIVE,
            )
            .limit(1)
        )
        if row is None:
            return None
        return AdminCredential(principal=self._principal(row), password_hash=row.password_hash)

    async def get_active_principal(self, admin_id: UUID) -> AdminPrincipal | None:
        row = await self._session.scalar(
            select(AdminUser)
            .where(AdminUser.id == admin_id, AdminUser.status == AdminStatus.ACTIVE)
            .limit(1)
        )
        return self._principal(row) if row else None

    async def count_recent_login_failures(self, identifier_key: UUID, since: datetime) -> int:
        return int(
            await self._session.scalar(
                select(func.count(AuditEvent.id)).where(
                    AuditEvent.action == "admin_login_failed",
                    AuditEvent.resource_type == "admin_auth_identifier",
                    AuditEvent.resource_id == identifier_key,
                    AuditEvent.created_at >= since,
                )
            )
            or 0
        )

    async def record_login_failure(
        self, *, identifier_key: UUID, correlation_id: str, reason: str
    ) -> None:
        self._session.add(
            AuditEvent(
                actor_type=ActorType.SYSTEM,
                actor_id=None,
                action="admin_login_failed",
                resource_type="admin_auth_identifier",
                resource_id=identifier_key,
                metadata_redacted={"reason": reason},
                correlation_id=correlation_id,
            )
        )
        await self._session.flush()

    async def record_login_success(
        self,
        *,
        principal: AdminPrincipal,
        identifier_key: UUID,
        correlation_id: str,
        occurred_at: datetime,
    ) -> None:
        row = await self._session.scalar(
            select(AdminUser).where(AdminUser.id == principal.id).with_for_update().limit(1)
        )
        if row is None or row.status is not AdminStatus.ACTIVE:
            raise AdminResourceNotFoundError("admin_user_unavailable", "admin user is unavailable")
        row.last_login_at = occurred_at
        self._audit(
            principal,
            action="admin_login_succeeded",
            resource_type="admin_user",
            resource_id=principal.id,
            correlation_id=correlation_id,
            metadata={"identifier_key": str(identifier_key)},
        )
        await self._session.flush()

    async def record_access_denied(
        self,
        *,
        correlation_id: str,
        reason: str,
        admin_id: UUID | None,
        resource: str,
    ) -> None:
        self._session.add(
            AuditEvent(
                actor_type=ActorType.SYSTEM,
                actor_id=admin_id,
                action="admin_access_denied",
                resource_type="admin_endpoint",
                resource_id=None,
                metadata_redacted={
                    "reason": reason,
                    "resource": resource[:128],
                    "authenticated_principal": admin_id is not None,
                },
                correlation_id=correlation_id,
            )
        )
        await self._session.flush()

    async def list_conversations(
        self,
        *,
        search: str | None,
        status: ConversationStatus | None,
        language: str | None,
        intent: str | None,
        escalation_status: EscalationStatus | None,
        offset: int,
        limit: int,
    ) -> tuple[tuple[ConversationAdminItem, ...], int]:
        filters: list[Any] = []
        if status is not None:
            filters.append(Conversation.status == status)
        if language is not None:
            filters.append(Conversation.language == language)
        if intent is not None:
            filters.append(
                exists(
                    select(Message.id).where(
                        Message.conversation_id == Conversation.id,
                        Message.intent == intent,
                    )
                )
            )
        if escalation_status is not None:
            filters.append(
                exists(
                    select(Escalation.id).where(
                        Escalation.conversation_id == Conversation.id,
                        Escalation.status == escalation_status,
                    )
                )
            )
        if search:
            term = f"%{search.casefold()}%"
            filters.append(
                exists(
                    select(Message.id).where(
                        Message.conversation_id == Conversation.id,
                        or_(
                            func.lower(Message.text).like(term),
                            func.lower(Message.intent).like(term),
                            func.lower(Message.correlation_id).like(term),
                        ),
                    )
                )
            )

        total = int(
            await self._session.scalar(select(func.count(Conversation.id)).where(and_(*filters)))
            or 0
        )
        message_count = (
            select(func.count(Message.id))
            .where(Message.conversation_id == Conversation.id)
            .correlate(Conversation)
            .scalar_subquery()
        )
        last_text = (
            select(Message.text)
            .where(Message.conversation_id == Conversation.id)
            .order_by(Message.sequence_number.desc())
            .limit(1)
            .correlate(Conversation)
            .scalar_subquery()
        )
        latest_intent = (
            select(Message.intent)
            .where(Message.conversation_id == Conversation.id, Message.intent.is_not(None))
            .order_by(Message.sequence_number.desc())
            .limit(1)
            .correlate(Conversation)
            .scalar_subquery()
        )
        latest_escalation = (
            select(Escalation.status)
            .where(Escalation.conversation_id == Conversation.id)
            .order_by(Escalation.created_at.desc())
            .limit(1)
            .correlate(Conversation)
            .scalar_subquery()
        )
        rows = (
            await self._session.execute(
                select(
                    Conversation,
                    Guest.telegram_user_hash,
                    message_count,
                    last_text,
                    latest_intent,
                    latest_escalation,
                )
                .join(Guest, Guest.id == Conversation.guest_id)
                .where(and_(*filters))
                .order_by(Conversation.last_activity_at.desc(), Conversation.id)
                .offset(offset)
                .limit(limit)
            )
        ).all()
        items = tuple(
            self._conversation_item(
                conversation,
                guest_hash,
                int(count or 0),
                last_message,
                latest_message_intent,
                EscalationStatus(escalation) if escalation else None,
            )
            for (
                conversation,
                guest_hash,
                count,
                last_message,
                latest_message_intent,
                escalation,
            ) in rows
        )
        return items, total

    async def get_conversation(self, conversation_id: UUID) -> ConversationAdminDetail:
        row = (
            await self._session.execute(
                select(Conversation, Guest.telegram_user_hash)
                .join(Guest, Guest.id == Conversation.guest_id)
                .where(Conversation.id == conversation_id)
                .limit(1)
            )
        ).one_or_none()
        if row is None:
            raise AdminResourceNotFoundError("conversation_not_found", "conversation was not found")
        conversation, guest_hash = row
        messages = tuple(
            (
                await self._session.scalars(
                    select(Message)
                    .where(Message.conversation_id == conversation_id)
                    .order_by(Message.sequence_number)
                )
            ).all()
        )
        message_ids = [item.id for item in messages]
        tool_rows: Sequence[ToolExecution] = ()
        feedback_rows: Sequence[Feedback] = ()
        if message_ids:
            tool_rows = (
                await self._session.scalars(
                    select(ToolExecution)
                    .where(ToolExecution.message_id.in_(message_ids))
                    .order_by(ToolExecution.created_at, ToolExecution.id)
                )
            ).all()
            feedback_rows = (
                await self._session.scalars(
                    select(Feedback)
                    .where(Feedback.message_id.in_(message_ids))
                    .order_by(Feedback.created_at, Feedback.id)
                )
            ).all()
        escalation_rows = (
            await self._session.scalars(
                select(Escalation)
                .where(Escalation.conversation_id == conversation_id)
                .order_by(Escalation.created_at, Escalation.id)
            )
        ).all()
        latest_message = messages[-1].text if messages else None
        latest_intent = next((item.intent for item in reversed(messages) if item.intent), None)
        latest_escalation = (
            EscalationStatus(escalation_rows[-1].status) if escalation_rows else None
        )
        summary = self._conversation_item(
            conversation,
            guest_hash,
            len(messages),
            latest_message,
            latest_intent,
            latest_escalation,
        )
        return ConversationAdminDetail(
            conversation=summary,
            messages=tuple(self._message_item(item) for item in messages),
            tool_events=tuple(self._tool_item(item) for item in tool_rows),
            feedback=tuple(self._feedback_item(item) for item in feedback_rows),
            escalations=tuple(self._escalation_item(item) for item in escalation_rows),
        )

    async def list_knowledge(
        self,
        *,
        search: str | None,
        status: KnowledgeStatus | None,
        language: str | None,
        offset: int,
        limit: int,
    ) -> tuple[tuple[KnowledgeAdminItem, ...], int]:
        filters: list[Any] = []
        if search:
            filters.append(func.lower(KnowledgeDocument.title).like(f"%{search.casefold()}%"))
        if status is not None:
            filters.append(KnowledgeDocument.status == status)
        if language is not None:
            filters.append(KnowledgeDocument.language == language)
        total = int(
            await self._session.scalar(
                select(func.count(KnowledgeDocument.id)).where(and_(*filters))
            )
            or 0
        )
        rows = (
            await self._session.execute(
                select(KnowledgeDocument, func.count(KnowledgeRevision.id))
                .outerjoin(KnowledgeRevision, KnowledgeRevision.document_id == KnowledgeDocument.id)
                .where(and_(*filters))
                .group_by(KnowledgeDocument.id)
                .order_by(KnowledgeDocument.updated_at.desc(), KnowledgeDocument.id)
                .offset(offset)
                .limit(limit)
            )
        ).all()
        return tuple(self._knowledge_item(item, int(count)) for item, count in rows), total

    async def get_knowledge(self, document_id: UUID) -> KnowledgeAdminDetail:
        document = await self._session.get(KnowledgeDocument, document_id)
        if document is None:
            raise AdminResourceNotFoundError(
                "knowledge_document_not_found", "knowledge document was not found"
            )
        revisions = (
            await self._session.scalars(
                select(KnowledgeRevision)
                .where(KnowledgeRevision.document_id == document_id)
                .order_by(KnowledgeRevision.version.desc())
            )
        ).all()
        approval_events = (
            await self._session.scalars(
                select(AuditEvent)
                .where(
                    AuditEvent.resource_type == "knowledge_document",
                    AuditEvent.resource_id == document_id,
                    AuditEvent.action.in_(
                        (
                            "knowledge_revision_approved",
                            "knowledge_revision_reactivated",
                        )
                    ),
                )
                .order_by(AuditEvent.created_at, AuditEvent.id)
            )
        ).all()
        approvals: dict[UUID, tuple[datetime, UUID | None]] = {}
        for event in approval_events:
            value = (event.metadata_redacted or {}).get("revision_id")
            try:
                revision_id = UUID(str(value))
            except (TypeError, ValueError):
                continue
            approvals.setdefault(revision_id, (event.created_at, event.actor_id))
        active_index = await self._session.scalar(
            select(IndexVersion)
            .where(IndexVersion.status == IndexStatus.ACTIVE)
            .order_by(IndexVersion.activated_at.desc(), IndexVersion.id.desc())
            .limit(1)
        )
        indexed_revision_ids: set[UUID] = set()
        if active_index is not None:
            indexed_revision_ids = set(
                await self._session.scalars(
                    select(KnowledgeChunk.revision_id)
                    .join(KnowledgeRevision, KnowledgeRevision.id == KnowledgeChunk.revision_id)
                    .where(
                        KnowledgeChunk.index_version_id == active_index.id,
                        KnowledgeRevision.document_id == document_id,
                    )
                    .distinct()
                )
            )
        build_in_progress = bool(
            await self._session.scalar(
                select(func.count(IndexVersion.id)).where(
                    IndexVersion.status == IndexStatus.BUILDING
                )
            )
        )
        expected_revision_ids = (
            {document.current_revision_id}
            if (
                KnowledgeStatus(document.status) is KnowledgeStatus.APPROVED
                and document.current_revision_id is not None
            )
            else set()
        )
        synchronized = indexed_revision_ids == expected_revision_ids
        faiss_sync_status: Literal["synchronized", "needs_rebuild", "building"] = (
            "building"
            if build_in_progress
            else "synchronized"
            if synchronized
            else "needs_rebuild"
        )
        retrieval_eligible = bool(
            KnowledgeStatus(document.status) is KnowledgeStatus.APPROVED
            and document.current_revision_id is not None
            and document.current_revision_id in indexed_revision_ids
            and synchronized
        )
        return KnowledgeAdminDetail(
            document=self._knowledge_item(document, len(revisions)),
            revisions=tuple(
                KnowledgeRevisionAdminItem(
                    id=item.id,
                    version=item.version,
                    content=item.content,
                    checksum=item.checksum,
                    created_by=item.created_by,
                    created_at=item.created_at,
                    status=(
                        "approved"
                        if item.id == document.current_revision_id
                        else "historical"
                        if item.id in approvals
                        else "draft"
                    ),
                    approved_at=(approvals[item.id][0] if item.id in approvals else None),
                    approved_by=(approvals[item.id][1] if item.id in approvals else None),
                    effective=item.id == document.current_revision_id,
                    indexed_in_faiss=item.id in indexed_revision_ids,
                    editable=(
                        item.id not in approvals
                        and item.id != document.current_revision_id
                        and KnowledgeStatus(document.status) is not KnowledgeStatus.ARCHIVED
                    ),
                )
                for item in revisions
            ),
            retrieval_eligible=retrieval_eligible,
            faiss_sync_status=faiss_sync_status,
            active_index_id=active_index.id if active_index else None,
        )

    async def list_service_requests(
        self,
        *,
        search: str | None,
        status: ServiceRequestStatus | None,
        urgency: Urgency | None,
        request_type: ServiceRequestType | None,
        offset: int,
        limit: int,
    ) -> tuple[tuple[ServiceRequestAdminItem, ...], int]:
        filters: list[Any] = []
        if search:
            term = f"%{search.casefold()}%"
            filters.append(
                or_(
                    func.lower(ServiceRequest.tracking_code).like(term),
                    func.lower(ServiceRequest.description).like(term),
                    func.lower(ServiceRequest.category).like(term),
                    func.lower(Room.room_number).like(term),
                )
            )
        if status is not None:
            filters.append(ServiceRequest.status == status)
        if urgency is not None:
            filters.append(ServiceRequest.urgency == urgency)
        if request_type is not None:
            filters.append(ServiceRequest.type == request_type)
        count_query = (
            select(func.count(ServiceRequest.id))
            .join(Room, Room.id == ServiceRequest.room_id)
            .where(and_(*filters))
        )
        total = int(await self._session.scalar(count_query) or 0)
        rows = (
            await self._session.execute(
                select(ServiceRequest, Room.room_number)
                .join(Room, Room.id == ServiceRequest.room_id)
                .where(and_(*filters))
                .order_by(ServiceRequest.created_at.desc(), ServiceRequest.id)
                .offset(offset)
                .limit(limit)
            )
        ).all()
        return tuple(self._service_request_item(item, room) for item, room in rows), total

    async def transition_service_request(
        self,
        *,
        request_id: UUID,
        target: ServiceRequestStatus,
        principal: AdminPrincipal,
        correlation_id: str,
    ) -> ServiceRequestAdminItem:
        row = await self._session.scalar(
            select(ServiceRequest).where(ServiceRequest.id == request_id).with_for_update().limit(1)
        )
        if row is None:
            raise AdminResourceNotFoundError(
                "service_request_not_found", "service request was not found"
            )
        current = ServiceRequestStatus(row.status)
        validate_status_transition(current, target)
        room_number = await self._session.scalar(
            select(Room.room_number).where(Room.id == row.room_id).limit(1)
        )
        if room_number is None:
            raise AdminResourceNotFoundError("service_room_not_found", "service room was not found")
        row.status = target
        row.completed_at = utc_now_naive() if target is ServiceRequestStatus.COMPLETED else None
        self._audit(
            principal,
            action="service_request_status_updated",
            resource_type="service_request",
            resource_id=row.id,
            correlation_id=correlation_id,
            metadata={"from": current.value, "to": target.value},
        )
        await self._session.flush()
        await self._session.refresh(row)
        return self._service_request_item(row, room_number)

    async def create_evaluator_feedback(
        self,
        *,
        message_id: UUID,
        rating: int | None,
        label: str | None,
        comment: str | None,
        principal: AdminPrincipal,
        correlation_id: str,
    ) -> FeedbackAdminItem:
        if await self._session.get(Message, message_id) is None:
            raise AdminResourceNotFoundError("message_not_found", "message was not found")
        row = Feedback(
            message_id=message_id,
            source=FeedbackSource.EVALUATOR,
            rating=rating,
            label=label,
            comment=comment,
        )
        self._session.add(row)
        await self._session.flush()
        await self._session.refresh(row)
        self._audit(
            principal,
            action="evaluator_feedback_created",
            resource_type="message",
            resource_id=message_id,
            correlation_id=correlation_id,
            metadata={"feedback_id": str(row.id), "source": FeedbackSource.EVALUATOR.value},
        )
        await self._session.flush()
        return self._feedback_item(row)

    async def list_room_types(self) -> tuple[RoomTypeAdminItem, ...]:
        rows = (
            await self._session.scalars(
                select(RoomType).order_by(RoomType.code)
            )
        ).all()
        return tuple(self._room_type_item(row) for row in rows)

    async def update_room_type(
        self,
        room_type_id: UUID,
        *,
        values: dict[str, Any],
        principal: AdminPrincipal,
        correlation_id: str,
    ) -> RoomTypeAdminItem:
        row = await self._session.get(RoomType, room_type_id)
        if row is None:
            raise AdminResourceNotFoundError(
                "room_type_not_found",
                "room type was not found",
            )
        if "name_ar" in values:
            row.name_json = {**row.name_json, "ar": values["name_ar"]}
        if "name_en" in values:
            row.name_json = {**row.name_json, "en": values["name_en"]}
        for field in (
            "capacity_adults",
            "capacity_children",
            "nightly_rate_cents",
            "active",
        ):
            if field in values:
                setattr(row, field, values[field])
        self._audit(
            principal,
            action="room_type_updated",
            resource_type="room_type",
            resource_id=row.id,
            correlation_id=correlation_id,
            metadata={"fields": sorted(values)},
        )
        await self._session.flush()
        return self._room_type_item(row)

    async def list_rooms(
        self,
        *,
        room_type_id: UUID | None,
        status: RoomOperationalStatus | None,
    ) -> tuple[RoomAdminItem, ...]:
        filters: list[Any] = []
        if room_type_id is not None:
            filters.append(Room.room_type_id == room_type_id)
        if status is not None:
            filters.append(Room.operational_status == status)
        rows = (
            await self._session.execute(
                select(Room, RoomType.code)
                .join(RoomType, RoomType.id == Room.room_type_id)
                .where(*filters)
                .order_by(Room.room_number)
            )
        ).all()
        return tuple(
            self._room_item(room, room_type_code)
            for room, room_type_code in rows
        )

    async def update_room(
        self,
        room_id: UUID,
        *,
        room_type_id: UUID | None,
        floor: int | None,
        operational_status: RoomOperationalStatus | None,
        principal: AdminPrincipal,
        correlation_id: str,
    ) -> RoomAdminItem:
        row = await self._session.get(Room, room_id)
        if row is None:
            raise AdminResourceNotFoundError(
                "room_not_found",
                "room was not found",
            )
        if room_type_id is not None:
            room_type = await self._session.get(RoomType, room_type_id)
            if room_type is None:
                raise AdminValidationError(
                    "room_type_not_found",
                    "room type was not found",
                )
            row.room_type_id = room_type_id
        if floor is not None:
            row.floor = floor
        if operational_status is not None:
            row.operational_status = operational_status
        room_type_code = await self._session.scalar(
            select(RoomType.code).where(RoomType.id == row.room_type_id)
        )
        assert room_type_code is not None
        self._audit(
            principal,
            action="room_updated",
            resource_type="room",
            resource_id=row.id,
            correlation_id=correlation_id,
            metadata={
                "room_type_changed": room_type_id is not None,
                "status": (
                    operational_status.value
                    if operational_status
                    else None
                ),
            },
        )
        await self._session.flush()
        return self._room_item(row, room_type_code)

    async def list_bookings(self) -> tuple[BookingAdminItem, ...]:
        rows = (
            await self._session.execute(
                select(
                    Booking,
                    RoomType.code,
                    Room.room_number,
                )
                .join(RoomType, RoomType.id == Booking.room_type_id)
                .outerjoin(Room, Room.id == Booking.room_id)
                .order_by(Booking.check_in.desc(), Booking.reference)
            )
        ).all()
        return tuple(
            self._booking_item(booking, room_type_code, room_number)
            for booking, room_type_code, room_number in rows
        )

    async def create_booking(
        self,
        *,
        reference: str,
        guest_name_masked: str,
        check_in: Any,
        check_out: Any,
        room_type_id: UUID,
        room_id: UUID | None,
        adults: int,
        children: int,
        status: BookingStatus,
        verification_value: str | None,
        principal: AdminPrincipal,
        correlation_id: str,
    ) -> BookingMutationResult:
        existing = await self._session.scalar(
            select(Booking.id).where(Booking.reference == reference).limit(1)
        )
        if existing is not None:
            raise AdminValidationError(
                "booking_reference_exists",
                "booking reference already exists",
            )
        room_type, room, room_number = await self._validate_booking_relations(
            room_type_id=room_type_id,
            room_id=room_id,
            check_in=check_in,
            check_out=check_out,
            adults=adults,
            children=children,
        )
        code = verification_value or f"{secrets.randbelow(1_000_000):06d}"
        row = Booking(
            reference=reference,
            guest_verification_hash=hash_verification_value(
                code,
                salt=secrets.token_bytes(16),
            ),
            guest_name_masked=guest_name_masked,
            check_in=check_in,
            check_out=check_out,
            room_type_id=room_type.id,
            room_id=room.id if room else None,
            adults=adults,
            children=children,
            status=status,
        )
        self._session.add(row)
        await self._session.flush()
        self._audit(
            principal,
            action="demo_booking_created",
            resource_type="booking",
            resource_id=row.id,
            correlation_id=correlation_id,
            metadata={"reference": reference, "verification_rotated": True},
        )
        await self._session.flush()
        return BookingMutationResult(
            booking=self._booking_item(row, room_type.code, room_number),
            verification_code_once=code,
        )

    async def update_booking(
        self,
        booking_id: UUID,
        *,
        values: dict[str, Any],
        principal: AdminPrincipal,
        correlation_id: str,
    ) -> BookingMutationResult:
        row = await self._session.get(Booking, booking_id)
        if row is None:
            raise AdminResourceNotFoundError(
                "booking_not_found",
                "booking was not found",
            )
        relation_fields = {
            "check_in": values.get("check_in", row.check_in),
            "check_out": values.get("check_out", row.check_out),
            "room_type_id": values.get("room_type_id", row.room_type_id),
            "room_id": values.get("room_id", row.room_id),
            "adults": values.get("adults", row.adults),
            "children": values.get("children", row.children),
        }
        room_type, room, room_number = await self._validate_booking_relations(
            **relation_fields,
        )
        for field in (
            "guest_name_masked",
            "check_in",
            "check_out",
            "adults",
            "children",
            "status",
        ):
            if field in values:
                setattr(row, field, values[field])
        row.room_type_id = room_type.id
        row.room_id = room.id if room else None
        code = values.get("verification_value")
        if code:
            row.guest_verification_hash = hash_verification_value(
                code,
                salt=secrets.token_bytes(16),
            )
        self._audit(
            principal,
            action="demo_booking_updated",
            resource_type="booking",
            resource_id=row.id,
            correlation_id=correlation_id,
            metadata={
                "fields": sorted(values),
                "verification_rotated": bool(code),
            },
        )
        await self._session.flush()
        return BookingMutationResult(
            booking=self._booking_item(row, room_type.code, room_number),
            verification_code_once=code,
        )

    async def reset_booking_verification(
        self,
        booking_id: UUID,
        *,
        principal: AdminPrincipal,
        correlation_id: str,
    ) -> BookingMutationResult:
        row = await self._session.get(Booking, booking_id)
        if row is None:
            raise AdminResourceNotFoundError(
                "booking_not_found",
                "booking was not found",
            )
        code = f"{secrets.randbelow(1_000_000):06d}"
        row.guest_verification_hash = hash_verification_value(
            code,
            salt=secrets.token_bytes(16),
        )
        room_type_code = await self._session.scalar(
            select(RoomType.code).where(RoomType.id == row.room_type_id)
        )
        room_number = (
            await self._session.scalar(
                select(Room.room_number).where(Room.id == row.room_id)
            )
            if row.room_id
            else None
        )
        assert room_type_code is not None
        self._audit(
            principal,
            action="booking_verification_reset",
            resource_type="booking",
            resource_id=row.id,
            correlation_id=correlation_id,
            metadata={"verification_rotated": True},
        )
        await self._session.flush()
        return BookingMutationResult(
            booking=self._booking_item(row, room_type_code, room_number),
            verification_code_once=code,
        )

    async def record_demo_reset(
        self,
        *,
        dataset_version: str,
        principal: AdminPrincipal,
        correlation_id: str,
    ) -> None:
        self._audit(
            principal,
            action="demo_data_reset",
            resource_type="hotel_seed_dataset",
            resource_id=None,
            correlation_id=correlation_id,
            metadata={"dataset_version": dataset_version},
        )
        await self._session.flush()

    async def _validate_booking_relations(
        self,
        *,
        room_type_id: UUID,
        room_id: UUID | None,
        check_in: Any,
        check_out: Any,
        adults: int,
        children: int,
    ) -> tuple[RoomType, Room | None, str | None]:
        if check_out <= check_in:
            raise AdminValidationError(
                "invalid_booking_date_range",
                "check-out must be after check-in",
            )
        room_type = await self._session.get(RoomType, room_type_id)
        if room_type is None:
            raise AdminValidationError(
                "room_type_not_found",
                "room type was not found",
            )
        if (
            adults > room_type.capacity_adults
            or children > room_type.capacity_children
        ):
            raise AdminValidationError(
                "booking_exceeds_room_capacity",
                "booking exceeds room capacity",
            )
        room = await self._session.get(Room, room_id) if room_id else None
        if room_id and room is None:
            raise AdminValidationError("room_not_found", "room was not found")
        if room and room.room_type_id != room_type_id:
            raise AdminValidationError(
                "room_type_mismatch",
                "assigned room does not match room type",
            )
        return room_type, room, room.room_number if room else None

    async def operational_evaluation_metrics(self) -> dict[str, Any]:
        llm_rows = (
            await self._session.execute(
                select(LLMRun.status, func.count(LLMRun.id)).group_by(LLMRun.status)
            )
        ).all()
        tool_rows = (
            await self._session.execute(
                select(ToolExecution.result_status, func.count(ToolExecution.id)).group_by(
                    ToolExecution.result_status
                )
            )
        ).all()
        rejection_rows = (
            await self._session.execute(
                select(ToolExecution.error_code, func.count(ToolExecution.id))
                .where(
                    ToolExecution.result_status
                    == ToolExecutionStatus.REJECTED
                )
                .group_by(ToolExecution.error_code)
            )
        ).all()
        feedback_rows = (
            await self._session.execute(
                select(Feedback.label, func.count(Feedback.id))
                .where(Feedback.source == FeedbackSource.EVALUATOR)
                .group_by(Feedback.label)
            )
        ).all()
        llm_counts = {LLMRunStatus(status).value: int(count) for status, count in llm_rows}
        tool_counts = {ToolExecutionStatus(status).value: int(count) for status, count in tool_rows}
        feedback_counts = {label or "unlabeled": int(count) for label, count in feedback_rows}
        llm_total = sum(llm_counts.values())
        tool_total = sum(tool_counts.values())
        expected_rejections = tool_counts.get("rejected", 0)
        unexpected_failures = (
            tool_counts.get("failed", 0)
            + tool_counts.get("timed_out", 0)
        )
        valid_tool_requests = (
            tool_counts.get("succeeded", 0)
            + unexpected_failures
        )
        avg_rating = await self._session.scalar(
            select(func.avg(Feedback.rating)).where(
                Feedback.source == FeedbackSource.EVALUATOR,
                Feedback.rating.is_not(None),
            )
        )
        return {
            "answer_quality": {
                "evaluator_label_counts": feedback_counts,
                "evaluator_sample_count": sum(feedback_counts.values()),
                "average_evaluator_rating": round(float(avg_rating), 4) if avg_rating else None,
                "ground_truth_policy": "evaluator_labels_are_distinct_from_guest_feedback",
            },
            "llm_reliability": {
                "status_counts": llm_counts,
                "sample_count": llm_total,
                "success_rate": round(llm_counts.get("succeeded", 0) / llm_total, 4)
                if llm_total
                else None,
            },
            "tool_execution": {
                "status_counts": tool_counts,
                "expected_rejection_error_counts": {
                    code or "unspecified": int(count)
                    for code, count in rejection_rows
                },
                "sample_count": tool_total,
                "valid_tool_requests_succeeded": tool_counts.get(
                    "succeeded", 0
                ),
                "expected_requests_rejected": expected_rejections,
                "unexpected_execution_failures": unexpected_failures,
                "valid_request_success_rate": round(
                    tool_counts.get("succeeded", 0)
                    / valid_tool_requests,
                    4,
                )
                if valid_tool_requests
                else None,
            },
        }

    async def create_evaluation(
        self,
        *,
        dataset_version: str,
        system_versions: dict[str, Any],
        metrics: dict[str, Any],
        principal: AdminPrincipal,
        correlation_id: str,
    ) -> EvaluationAdminItem:
        now = utc_now_naive()
        row = EvaluationRun(
            dataset_version=dataset_version,
            system_versions=system_versions,
            metrics_json=metrics,
            status=EvaluationStatus.COMPLETED,
            started_at=now,
            finished_at=now,
        )
        self._session.add(row)
        await self._session.flush()
        await self._session.refresh(row)
        self._audit(
            principal,
            action="offline_evaluation_completed",
            resource_type="evaluation_run",
            resource_id=row.id,
            correlation_id=correlation_id,
            metadata={"dataset_version": dataset_version},
        )
        await self._session.flush()
        return self._evaluation_item(row)

    async def get_evaluation(self, evaluation_id: UUID) -> EvaluationAdminItem:
        row = await self._session.get(EvaluationRun, evaluation_id)
        if row is None:
            raise AdminResourceNotFoundError("evaluation_not_found", "evaluation run was not found")
        return self._evaluation_item(row)

    async def list_evaluations(
        self,
        *,
        status: EvaluationStatus | None,
        offset: int,
        limit: int,
    ) -> tuple[tuple[EvaluationAdminItem, ...], int]:
        filters = (EvaluationRun.status == status,) if status is not None else ()
        total = int(
            await self._session.scalar(select(func.count(EvaluationRun.id)).where(*filters)) or 0
        )
        rows = (
            await self._session.scalars(
                select(EvaluationRun)
                .where(*filters)
                .order_by(EvaluationRun.created_at.desc(), EvaluationRun.id.desc())
                .offset(offset)
                .limit(limit)
            )
        ).all()
        return tuple(self._evaluation_item(row) for row in rows), total

    def _audit(
        self,
        principal: AdminPrincipal,
        *,
        action: str,
        resource_type: str,
        resource_id: UUID | None,
        correlation_id: str,
        metadata: dict[str, Any] | None,
    ) -> None:
        self._session.add(
            AuditEvent(
                actor_type=_actor_type(principal.role),
                actor_id=principal.id,
                action=action,
                resource_type=resource_type,
                resource_id=resource_id,
                metadata_redacted=metadata,
                correlation_id=correlation_id,
            )
        )

    @staticmethod
    def _principal(row: AdminUser) -> AdminPrincipal:
        return AdminPrincipal(
            id=row.id,
            email=row.email,
            username=row.username,
            role=AdminRole(row.role),
        )

    @staticmethod
    def _conversation_item(
        row: Conversation,
        guest_hash: str,
        message_count: int,
        last_message: str | None,
        latest_intent: str | None,
        escalation_status: EscalationStatus | None,
    ) -> ConversationAdminItem:
        preview = redact_admin_text(last_message)[:240] if last_message else None
        return ConversationAdminItem(
            id=row.id,
            guest_reference=mask_guest_reference(guest_hash),
            channel=row.channel,
            status=ConversationStatus(row.status),
            language=row.language,
            message_count=message_count,
            last_message_preview=preview,
            latest_intent=latest_intent,
            escalation_status=escalation_status,
            started_at=row.started_at,
            last_activity_at=row.last_activity_at,
            closed_at=row.closed_at,
        )

    @staticmethod
    def _message_item(row: Message) -> MessageAdminItem:
        return MessageAdminItem(
            id=row.id,
            sequence_number=row.sequence_number,
            direction=MessageDirection(row.direction),
            text=redact_admin_text(row.text),
            language=row.language,
            intent=row.intent,
            confidence=float(row.confidence) if row.confidence is not None else None,
            classifier_version=row.classifier_version,
            correlation_id=row.correlation_id,
            created_at=row.created_at,
            redacted=row.redacted_at is not None,
        )

    @staticmethod
    def _tool_item(row: ToolExecution) -> ToolEventAdminItem:
        return ToolEventAdminItem(
            id=row.id,
            message_id=row.message_id,
            tool_name=row.tool_name,
            arguments=row.arguments_redacted,
            result_status=ToolExecutionStatus(row.result_status),
            result=row.result_redacted,
            latency_ms=row.latency_ms,
            correlation_id=row.correlation_id,
            error_code=row.error_code,
            created_at=row.created_at,
        )

    @staticmethod
    def _feedback_item(row: Feedback) -> FeedbackAdminItem:
        return FeedbackAdminItem(
            id=row.id,
            message_id=row.message_id,
            source=FeedbackSource(row.source),
            rating=row.rating,
            label=row.label,
            comment=redact_admin_text(row.comment) if row.comment else None,
            created_at=row.created_at,
        )

    @staticmethod
    def _escalation_item(row: Escalation) -> EscalationAdminItem:
        return EscalationAdminItem(
            id=row.id,
            reason=redact_admin_text(row.reason),
            status=EscalationStatus(row.status),
            assigned_to=row.assigned_to,
            created_at=row.created_at,
            updated_at=row.updated_at,
            resolved_at=row.resolved_at,
        )

    @staticmethod
    def _knowledge_item(row: KnowledgeDocument, revision_count: int) -> KnowledgeAdminItem:
        return KnowledgeAdminItem(
            id=row.id,
            title=row.title,
            language=row.language,
            source_format=SourceFormat(row.source_format),
            status=KnowledgeStatus(row.status),
            current_revision_id=row.current_revision_id,
            revision_count=revision_count,
            created_at=row.created_at,
            updated_at=row.updated_at,
        )

    @staticmethod
    def _room_type_item(row: RoomType) -> RoomTypeAdminItem:
        return RoomTypeAdminItem(
            id=row.id,
            code=row.code,
            name_ar=row.name_json.get("ar", row.code),
            name_en=row.name_json.get("en", row.code),
            capacity_adults=row.capacity_adults,
            capacity_children=row.capacity_children,
            nightly_rate_cents=row.nightly_rate_cents,
            currency="USD",
            active=row.active,
        )

    @staticmethod
    def _room_item(row: Room, room_type_code: str) -> RoomAdminItem:
        return RoomAdminItem(
            id=row.id,
            room_number=row.room_number,
            room_type_id=row.room_type_id,
            room_type_code=room_type_code,
            floor=row.floor,
            operational_status=RoomOperationalStatus(row.operational_status),
        )

    @staticmethod
    def _booking_item(
        row: Booking,
        room_type_code: str,
        room_number: str | None,
    ) -> BookingAdminItem:
        return BookingAdminItem(
            id=row.id,
            reference=row.reference,
            guest_name_masked=row.guest_name_masked,
            check_in=row.check_in,
            check_out=row.check_out,
            room_type_id=row.room_type_id,
            room_type_code=room_type_code,
            room_id=row.room_id,
            room_number=room_number,
            adults=row.adults,
            children=row.children,
            status=BookingStatus(row.status),
        )

    @staticmethod
    def _service_request_item(row: ServiceRequest, room_number: str) -> ServiceRequestAdminItem:
        return ServiceRequestAdminItem(
            id=row.id,
            tracking_code=mask_tracking_code(row.tracking_code),
            request_type=ServiceRequestType(row.type),
            category=row.category,
            room_number=room_number,
            description=redact_admin_text(row.description),
            urgency=Urgency(row.urgency),
            status=ServiceRequestStatus(row.status),
            created_at=row.created_at,
            updated_at=row.updated_at,
            completed_at=row.completed_at,
        )

    @staticmethod
    def _evaluation_item(row: EvaluationRun) -> EvaluationAdminItem:
        return EvaluationAdminItem(
            id=row.id,
            dataset_version=row.dataset_version,
            system_versions=row.system_versions,
            metrics=row.metrics_json,
            status=EvaluationStatus(row.status),
            started_at=row.started_at,
            finished_at=row.finished_at,
            error_summary=row.error_summary,
            created_at=row.created_at,
        )
