"""MySQL administration projections, security events, and controlled mutations."""

from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import and_, exists, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from hotel_bot.domain.admin.errors import AdminResourceNotFoundError
from hotel_bot.domain.admin.models import (
    AdminCredential,
    AdminPrincipal,
    ConversationAdminDetail,
    ConversationAdminItem,
    EscalationAdminItem,
    EvaluationAdminItem,
    FeedbackAdminItem,
    KnowledgeAdminDetail,
    KnowledgeAdminItem,
    KnowledgeRevisionAdminItem,
    MessageAdminItem,
    ServiceRequestAdminItem,
    ToolEventAdminItem,
)
from hotel_bot.domain.admin.security import (
    mask_guest_reference,
    mask_tracking_code,
    redact_admin_text,
)
from hotel_bot.domain.conversation.enums import ConversationStatus, MessageDirection
from hotel_bot.domain.hotel.enums import ServiceRequestStatus, ServiceRequestType, Urgency
from hotel_bot.domain.hotel.policies import validate_status_transition
from hotel_bot.domain.knowledge.enums import KnowledgeStatus, SourceFormat
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
    Conversation,
    Escalation,
    EvaluationRun,
    Feedback,
    Guest,
    KnowledgeDocument,
    KnowledgeRevision,
    LLMRun,
    Message,
    Room,
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
                )
                for item in revisions
            ),
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
                "sample_count": tool_total,
                "success_rate": round(tool_counts.get("succeeded", 0) / tool_total, 4)
                if tool_total
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
