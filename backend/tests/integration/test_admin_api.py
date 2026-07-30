"""Real-MySQL administration authentication, RBAC, masking, and API acceptance journey."""

import asyncio
import os
from pathlib import Path
from tempfile import TemporaryDirectory
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import delete, select, update

from hotel_bot.core.config import Settings
from hotel_bot.domain.admin.security import hash_admin_password
from hotel_bot.domain.conversation.enums import ConversationStatus, MessageDirection
from hotel_bot.domain.hotel.enums import (
    RoomOperationalStatus,
    ServiceRequestStatus,
    ServiceRequestType,
    Urgency,
)
from hotel_bot.domain.hotel.security import verify_verification_value
from hotel_bot.domain.knowledge.enums import IndexStatus
from hotel_bot.infrastructure.database import DatabaseManager
from hotel_bot.main import create_app
from hotel_bot.persistence.enums import ActorType, AdminRole, AdminStatus
from hotel_bot.persistence.models import (
    AdminUser,
    AuditEvent,
    Booking,
    Conversation,
    EvaluationRun,
    Feedback,
    Guest,
    IndexVersion,
    KnowledgeChunk,
    KnowledgeDocument,
    KnowledgeRevision,
    Message,
    Room,
    RoomType,
    ServiceRequest,
)

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        os.getenv("RUN_MYSQL_INTEGRATION") != "1",
        reason="set RUN_MYSQL_INTEGRATION=1 with the project MySQL container running",
    ),
]

PASSWORD = "Strong integration password 1!"
TOKEN_SECRET = "integration-admin-token-secret-32-bytes-minimum"


def mysql_settings(index_path: Path) -> Settings:
    project_root = Path(__file__).resolve().parents[3]
    values = {
        key: value
        for line in (project_root / ".env").read_text(encoding="utf-8").splitlines()
        if line and not line.lstrip().startswith("#") and "=" in line
        for key, value in [line.split("=", maxsplit=1)]
    }
    return Settings(
        APP_ENVIRONMENT="test",
        DB_HOST=values["DB_HOST"],
        DB_PORT=int(values["DB_PORT"]),
        DB_NAME=values["DB_NAME"],
        DB_USER=values["DB_USER"],
        DB_PASSWORD=SecretStr(values["DB_PASSWORD"]),
        ADMIN_TOKEN_SECRET=SecretStr(TOKEN_SECRET),
        DEMO_MODE=True,
        EMBEDDING_PROVIDER="hashing_test",
        EMBEDDING_DIMENSION=64,
        KNOWLEDGE_INDEX_PATH=index_path,
        _env_file=None,
    )  # type: ignore[call-arg]


def test_admin_api_auth_rbac_masking_and_management_journey() -> None:
    async def prepare(settings: Settings, prefix: str) -> dict[str, UUID]:
        database = DatabaseManager(settings)
        ids = {
            "admin": uuid4(),
            "support": uuid4(),
            "evaluator": uuid4(),
            "guest": uuid4(),
            "conversation": uuid4(),
            "message": uuid4(),
            "room_type": uuid4(),
            "room": uuid4(),
            "service": uuid4(),
        }
        password_hash = hash_admin_password(PASSWORD)
        try:
            async with database.transaction() as session:
                for role in (AdminRole.ADMIN, AdminRole.SUPPORT, AdminRole.EVALUATOR):
                    session.add(
                        AdminUser(
                            id=ids[role.value],
                            email=f"{prefix}-{role.value}@example.invalid",
                            username=f"{prefix}_{role.value}",
                            password_hash=password_hash,
                            role=role,
                            status=AdminStatus.ACTIVE,
                        )
                    )
                session.add(
                    Guest(
                        id=ids["guest"],
                        telegram_user_hash="f" * 56 + ids["guest"].hex[:8],
                        preferred_language="en",
                    )
                )
                await session.flush()
                session.add(
                    Conversation(
                        id=ids["conversation"],
                        guest_id=ids["guest"],
                        channel="telegram",
                        status=ConversationStatus.OPEN,
                        language="en",
                    )
                )
                await session.flush()
                session.add(
                    Message(
                        id=ids["message"],
                        conversation_id=ids["conversation"],
                        sequence_number=1,
                        direction=MessageDirection.INBOUND,
                        text=(
                            "Booking BKG-SECRET-777 verification=Hidden77 "
                            "email guest@example.com phone +963 944 123 456"
                        ),
                        language="en",
                        intent="booking_lookup",
                        confidence=0.95,
                        classifier_version="integration-v1",
                        correlation_id=f"{prefix}-message",
                    )
                )
                session.add(
                    RoomType(
                        id=ids["room_type"],
                        code=f"it-{prefix}",
                        name_json={"ar": "اختبار", "en": "Integration"},
                        description_json={"ar": "غرفة اختبار", "en": "Integration room"},
                        capacity_adults=2,
                        capacity_children=1,
                        amenities_json=["wifi"],
                        active=True,
                    )
                )
                await session.flush()
                session.add(
                    Room(
                        id=ids["room"],
                        room_number=f"T{ids['room'].hex[:6]}",
                        room_type_id=ids["room_type"],
                        floor=9,
                        operational_status=RoomOperationalStatus.AVAILABLE,
                    )
                )
                await session.flush()
                session.add(
                    ServiceRequest(
                        id=ids["service"],
                        tracking_code=f"SR-{ids['service'].hex[:10].upper()}",
                        type=ServiceRequestType.MAINTENANCE,
                        category="hvac",
                        room_id=ids["room"],
                        booking_id=None,
                        description="Air conditioning requires an integration inspection.",
                        urgency=Urgency.NORMAL,
                        status=ServiceRequestStatus.OPEN,
                        idempotency_key=f"integration-{ids['service'].hex}",
                        requested_by_guest_id=ids["guest"],
                    )
                )
        finally:
            await database.dispose()
        return ids

    async def capture_active(settings: Settings) -> tuple[UUID, ...]:
        database = DatabaseManager(settings)
        try:
            async with database.session() as session:
                return tuple(
                    await session.scalars(
                        select(IndexVersion.id).where(IndexVersion.status == IndexStatus.ACTIVE)
                    )
                )
        finally:
            await database.dispose()

    async def cleanup(
        settings: Settings,
        ids: dict[str, UUID],
        prefix: str,
        document_id: UUID | None,
        index_id: UUID | None,
        evaluation_id: UUID | None,
        previously_active: tuple[UUID, ...],
    ) -> None:
        database = DatabaseManager(settings)
        try:
            async with database.transaction() as session:
                if index_id is not None:
                    await session.execute(
                        delete(KnowledgeChunk).where(KnowledgeChunk.index_version_id == index_id)
                    )
                    await session.execute(delete(IndexVersion).where(IndexVersion.id == index_id))
                if previously_active:
                    await session.execute(
                        update(IndexVersion)
                        .where(IndexVersion.id.in_(previously_active))
                        .values(status=IndexStatus.ACTIVE)
                    )
                if document_id is not None:
                    await session.execute(
                        update(KnowledgeDocument)
                        .where(KnowledgeDocument.id == document_id)
                        .values(current_revision_id=None)
                    )
                    await session.execute(
                        delete(KnowledgeRevision).where(
                            KnowledgeRevision.document_id == document_id
                        )
                    )
                    await session.execute(
                        delete(KnowledgeDocument).where(KnowledgeDocument.id == document_id)
                    )
                if evaluation_id is not None:
                    await session.execute(
                        delete(EvaluationRun).where(EvaluationRun.id == evaluation_id)
                    )
                await session.execute(
                    delete(ServiceRequest).where(ServiceRequest.id == ids["service"])
                )
                await session.execute(delete(Feedback).where(Feedback.message_id == ids["message"]))
                await session.execute(delete(Message).where(Message.id == ids["message"]))
                await session.execute(
                    delete(Conversation).where(Conversation.id == ids["conversation"])
                )
                await session.execute(delete(Room).where(Room.id == ids["room"]))
                await session.execute(delete(RoomType).where(RoomType.id == ids["room_type"]))
                await session.execute(delete(Guest).where(Guest.id == ids["guest"]))
                await session.execute(
                    delete(AuditEvent).where(
                        (AuditEvent.correlation_id.like(f"{prefix}%"))
                        | (
                            AuditEvent.actor_id.in_(
                                [ids["admin"], ids["support"], ids["evaluator"]]
                            )
                        )
                    )
                )
                await session.execute(
                    delete(AdminUser).where(
                        AdminUser.id.in_([ids["admin"], ids["support"], ids["evaluator"]])
                    )
                )
        finally:
            await database.dispose()

    prefix = f"admin-it-{uuid4().hex[:8]}"
    document_id: UUID | None = None
    index_id: UUID | None = None
    evaluation_id: UUID | None = None
    with TemporaryDirectory() as temporary_directory:
        settings = mysql_settings(Path(temporary_directory))
        ids = asyncio.run(prepare(settings, prefix))
        previously_active = asyncio.run(capture_active(settings))
        try:
            app = create_app(settings)
            with TestClient(app) as client:
                unauthorized = client.get(
                    "/api/v1/admin/conversations",
                    headers={"X-Correlation-ID": f"{prefix}-unauthorized"},
                )
                assert unauthorized.status_code == 401

                invalid = client.post(
                    "/api/v1/admin/auth/login",
                    json={"identifier": f"{prefix}_admin", "password": "Wrong password value!"},
                    headers={"X-Correlation-ID": f"{prefix}-invalid-login"},
                )
                assert invalid.status_code == 401
                assert invalid.json() == {"detail": "invalid_admin_credentials"}

                for attempt in range(5):
                    limited = client.post(
                        "/api/v1/admin/auth/login",
                        json={
                            "identifier": f"{prefix}_missing",
                            "password": "Wrong password value!",
                        },
                        headers={"X-Correlation-ID": f"{prefix}-rate-limit-{attempt}"},
                    )
                    assert limited.status_code == 401
                rate_limited = client.post(
                    "/api/v1/admin/auth/login",
                    json={
                        "identifier": f"{prefix}_missing",
                        "password": "Wrong password value!",
                    },
                    headers={"X-Correlation-ID": f"{prefix}-rate-limited"},
                )
                assert rate_limited.status_code == 429
                assert rate_limited.headers["retry-after"] == "900"

                def login(role: str) -> str:
                    response = client.post(
                        "/api/v1/admin/auth/login",
                        json={"identifier": f"{prefix}_{role}", "password": PASSWORD},
                        headers={"X-Correlation-ID": f"{prefix}-login-{role}"},
                    )
                    assert response.status_code == 200
                    assert response.headers["cache-control"] == "no-store"
                    return str(response.json()["access_token"])

                admin_token = login("admin")
                support_token = login("support")
                evaluator_token = login("evaluator")

                def headers(token: str, event: str) -> dict[str, str]:
                    return {
                        "Authorization": f"Bearer {token}",
                        "X-Correlation-ID": f"{prefix}-{event}",
                    }

                me = client.get("/api/v1/admin/auth/me", headers=headers(admin_token, "me"))
                assert me.status_code == 200
                assert me.json()["role"] == "admin"

                room_types_response = client.get(
                    "/api/v1/admin/hotel-data/room-types",
                    headers=headers(admin_token, "hotel-room-types"),
                )
                assert room_types_response.status_code == 200
                seeded_type = next(
                    item
                    for item in room_types_response.json()
                    if item["code"] == "standard_king"
                )
                assert seeded_type["nightly_rate_cents"] >= 0
                assert seeded_type["name_ar"]
                assert seeded_type["name_en"]

                rooms_response = client.get(
                    "/api/v1/admin/hotel-data/rooms?status=available",
                    headers=headers(admin_token, "hotel-rooms"),
                )
                assert rooms_response.status_code == 200
                assert any(
                    item["room_number"] == "101"
                    for item in rooms_response.json()
                )

                bookings_response = client.get(
                    "/api/v1/admin/hotel-data/bookings",
                    headers=headers(admin_token, "hotel-bookings"),
                )
                assert bookings_response.status_code == 200
                seeded_booking = next(
                    item
                    for item in bookings_response.json()
                    if item["reference"] == "BKG-2026-0001"
                )
                assert "guest_verification_hash" not in seeded_booking

                demo_credentials = client.get(
                    "/api/v1/admin/hotel-data/demo-credentials",
                    headers=headers(admin_token, "demo-credentials"),
                )
                assert demo_credentials.status_code == 200
                assert demo_credentials.json()["label"] == (
                    "Demo data — not real guest credentials"
                )
                assert {
                    (
                        item["booking_reference"],
                        item["verification_code"],
                    )
                    for item in demo_credentials.json()["credentials"]
                } >= {
                    ("BKG-2026-0001", "0101"),
                    ("BKG-2026-0004", "0404"),
                }

                edited_booking = client.patch(
                    (
                        "/api/v1/admin/hotel-data/bookings/"
                        f"{seeded_booking['id']}"
                    ),
                    headers=headers(admin_token, "booking-edit"),
                    json={"guest_name_masked": "D*** E***"},
                )
                assert edited_booking.status_code == 200
                assert edited_booking.json()["verification_code_once"] is None

                reset_code_response = client.post(
                    (
                        "/api/v1/admin/hotel-data/bookings/"
                        f"{seeded_booking['id']}/reset-verification"
                    ),
                    headers=headers(admin_token, "booking-code-reset"),
                )
                assert reset_code_response.status_code == 200
                one_time_code = reset_code_response.json()[
                    "verification_code_once"
                ]
                assert one_time_code

                async def stored_hash() -> str:
                    database = DatabaseManager(settings)
                    try:
                        async with database.session() as session:
                            value = await session.scalar(
                                select(Booking.guest_verification_hash).where(
                                    Booking.id == UUID(seeded_booking["id"])
                                )
                            )
                            assert value is not None
                            return value
                    finally:
                        await database.dispose()

                verification_hash = asyncio.run(stored_hash())
                assert one_time_code not in verification_hash
                assert verify_verification_value(
                    one_time_code,
                    verification_hash,
                )

                for suffix in ("first", "second"):
                    reset_demo = client.post(
                        "/api/v1/admin/hotel-data/reset",
                        headers=headers(
                            admin_token,
                            f"demo-reset-{suffix}",
                        ),
                        json={"confirmation": "RESET DEMO DATA"},
                    )
                    assert reset_demo.status_code == 200
                    assert reset_demo.json()["reset"] is True

                restored_hash = asyncio.run(stored_hash())
                assert verify_verification_value("0101", restored_hash)

                forbidden = client.get(
                    "/api/v1/admin/knowledge",
                    headers=headers(support_token, "support-knowledge"),
                )
                assert forbidden.status_code == 403

                conversations = client.get(
                    "/api/v1/admin/conversations?intent=booking_lookup",
                    headers=headers(evaluator_token, "conversation-list"),
                )
                assert conversations.status_code == 200
                listed = next(
                    item
                    for item in conversations.json()["items"]
                    if item["id"] == str(ids["conversation"])
                )
                assert listed["guest_reference"].startswith("guest_********")
                assert "BKG-SECRET-777" not in (listed["last_message_preview"] or "")

                detail = client.get(
                    f"/api/v1/admin/conversations/{ids['conversation']}",
                    headers=headers(admin_token, "conversation-detail"),
                )
                assert detail.status_code == 200
                serialized = detail.text
                assert "BKG-SECRET-777" not in serialized
                assert "Hidden77" not in serialized
                assert "guest@example.com" not in serialized
                assert "+963 944 123 456" not in serialized

                feedback = client.post(
                    f"/api/v1/admin/messages/{ids['message']}/feedback",
                    json={"rating": 4, "label": "correct_intent", "comment": "Reviewed."},
                    headers=headers(evaluator_token, "feedback"),
                )
                assert feedback.status_code == 201
                assert feedback.json()["source"] == "evaluator"

                support_feedback = client.post(
                    f"/api/v1/admin/messages/{ids['message']}/feedback",
                    json={"label": "should_fail"},
                    headers=headers(support_token, "support-feedback"),
                )
                assert support_feedback.status_code == 403

                knowledge = client.post(
                    "/api/v1/admin/knowledge",
                    json={
                        "title": "Integration late checkout policy",
                        "language": "en",
                        "source_format": "plain_text",
                        "content": (
                            "Integration late checkout is available until 2 PM when approved "
                            "by the front desk."
                        ),
                    },
                    headers=headers(admin_token, "knowledge-create"),
                )
                assert knowledge.status_code == 201
                document_id = UUID(knowledge.json()["document_id"])

                revision = client.patch(
                    f"/api/v1/admin/knowledge/{document_id}",
                    json={
                        "title": "Integration late checkout policy v2",
                        "content": (
                            "Integration late checkout is available until 3 PM only after "
                            "front desk approval."
                        ),
                    },
                    headers=headers(admin_token, "knowledge-update"),
                )
                assert revision.status_code == 200
                revision_id = UUID(revision.json()["revision_id"])
                approval = client.post(
                    f"/api/v1/admin/knowledge/{document_id}/revisions/{revision_id}/approve",
                    headers=headers(admin_token, "knowledge-approve"),
                )
                assert approval.status_code == 200
                assert approval.json()["status"] == "approved"

                reindex = client.post(
                    "/api/v1/admin/knowledge/reindex",
                    headers=headers(admin_token, "knowledge-reindex"),
                )
                assert reindex.status_code == 202
                index_id = UUID(reindex.json()["index_version_id"])

                service_list = client.get(
                    "/api/v1/admin/service-requests?status=open",
                    headers=headers(support_token, "service-list"),
                )
                assert service_list.status_code == 200
                assert str(ids["service"]) in service_list.text
                service_item = next(
                    item
                    for item in service_list.json()["items"]
                    if item["id"] == str(ids["service"])
                )
                assert service_item["tracking_code"].startswith("SR-******")
                transition = client.patch(
                    f"/api/v1/admin/service-requests/{ids['service']}/status",
                    json={"status": "acknowledged"},
                    headers=headers(support_token, "service-transition"),
                )
                assert transition.status_code == 200
                assert transition.json()["status"] == "acknowledged"

                evaluator_transition = client.patch(
                    f"/api/v1/admin/service-requests/{ids['service']}/status",
                    json={"status": "in_progress"},
                    headers=headers(evaluator_token, "evaluator-service"),
                )
                assert evaluator_transition.status_code == 403

                evaluation = client.post(
                    "/api/v1/admin/evaluations",
                    json={"dataset_version": "hotel-support-baseline-v1"},
                    headers=headers(evaluator_token, "evaluation"),
                )
                assert evaluation.status_code == 201
                evaluation_id = UUID(evaluation.json()["id"])
                metrics = evaluation.json()["metrics"]
                assert metrics["intent"]["macro_f1"] is not None
                assert metrics["retrieval"]["recall_at_k"] is not None
                assert metrics["answer_quality"]["evaluator_sample_count"] >= 1
                tool_metrics = metrics["tool_execution"]
                assert "valid_tool_requests_succeeded" in tool_metrics
                assert "expected_requests_rejected" in tool_metrics
                assert "unexpected_execution_failures" in tool_metrics
                assert (
                    tool_metrics["expected_requests_rejected"]
                    == tool_metrics["status_counts"].get("rejected", 0)
                )

                fetched = client.get(
                    f"/api/v1/admin/evaluations/{evaluation_id}",
                    headers=headers(admin_token, "evaluation-get"),
                )
                assert fetched.status_code == 200
                assert fetched.json()["id"] == str(evaluation_id)

                evaluation_list = client.get(
                    "/api/v1/admin/evaluations?status=completed&page=1&page_size=10",
                    headers=headers(evaluator_token, "evaluation-list"),
                )
                assert evaluation_list.status_code == 200
                assert evaluation_list.json()["total"] >= 1
                assert str(evaluation_id) in {
                    item["id"] for item in evaluation_list.json()["items"]
                }

            async def verify_audit() -> None:
                database = DatabaseManager(settings)
                try:
                    async with database.session() as session:
                        events = tuple(
                            await session.scalars(
                                select(AuditEvent).where(
                                    AuditEvent.correlation_id.like(f"{prefix}%")
                                )
                            )
                        )
                    actions = {item.action for item in events}
                    assert "admin_access_denied" in actions
                    assert "admin_login_failed" in actions
                    assert "admin_login_succeeded" in actions
                    assert "service_request_status_updated" in actions
                    assert all(item.actor_type in set(ActorType) for item in events)
                finally:
                    await database.dispose()

            asyncio.run(verify_audit())
        finally:
            asyncio.run(
                cleanup(
                    settings,
                    ids,
                    prefix,
                    document_id,
                    index_id,
                    evaluation_id,
                    previously_active,
                )
            )
