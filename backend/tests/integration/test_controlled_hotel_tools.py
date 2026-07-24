"""Real-MySQL tool execution, audit privacy, confirmation, and idempotency tests."""

import asyncio
import hashlib
import os
from datetime import date
from pathlib import Path
from typing import cast
from uuid import uuid4

import pytest
from pydantic import SecretStr
from sqlalchemy import delete, select

from hotel_bot.application.hotel_operations import HotelOperationsService
from hotel_bot.application.hotel_tools import (
    AvailabilityOutput,
    BookingLookupOutput,
    RoomTypesOutput,
    ServiceRequestCreatedOutput,
    ServiceRequestStatusOutput,
    build_hotel_tool_registry,
)
from hotel_bot.application.tools import ControlledToolExecutor
from hotel_bot.core.config import Settings
from hotel_bot.domain.tools.enums import ToolCaller, ToolExecutionStatus
from hotel_bot.domain.tools.models import ToolCall, ToolExecutionContext
from hotel_bot.infrastructure.database import DatabaseManager
from hotel_bot.infrastructure.repositories.hotel_operations import (
    SQLAlchemyHotelOperationsRepository,
)
from hotel_bot.infrastructure.repositories.tool_audit import SQLAlchemyToolAuditRepository
from hotel_bot.persistence.enums import ConversationStatus, MessageDirection
from hotel_bot.persistence.models import (
    Conversation,
    Guest,
    Message,
    ServiceRequest,
    ToolExecution,
)
from hotel_bot.seed import HotelSeeder

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        os.getenv("RUN_MYSQL_INTEGRATION") != "1",
        reason="set RUN_MYSQL_INTEGRATION=1 with the project MySQL container running",
    ),
]


def mysql_settings() -> Settings:
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
        _env_file=None,
    )  # type: ignore[call-arg]


def test_controlled_hotel_tools_are_audited_private_and_idempotent() -> None:
    async def exercise() -> None:
        database = DatabaseManager(mysql_settings())
        guest_id = uuid4()
        conversation_id = uuid4()
        message_id = uuid4()
        correlation_id = f"tool-integration-{uuid4().hex}"
        idempotency_key = f"tool-integration-{uuid4().hex}"
        maintenance_idempotency_key = f"tool-maintenance-{uuid4().hex}"
        telegram_hash = hashlib.sha256(f"tool-test:{guest_id}".encode()).hexdigest()
        try:
            async with database.transaction() as session:
                await HotelSeeder(session).seed()
                session.add(
                    Guest(
                        id=guest_id,
                        telegram_user_hash=telegram_hash,
                        preferred_language="en",
                    )
                )
                await session.flush()
                session.add(
                    Conversation(
                        id=conversation_id,
                        guest_id=guest_id,
                        channel="integration_test",
                        status=ConversationStatus.OPEN,
                        language="en",
                    )
                )
                await session.flush()
                session.add(
                    Message(
                        id=message_id,
                        conversation_id=conversation_id,
                        sequence_number=1,
                        direction=MessageDirection.INBOUND,
                        text="integration tool request",
                        language="en",
                        correlation_id=correlation_id,
                    )
                )

            def execution_context(call_index: int, *, confirmed: bool) -> ToolExecutionContext:
                return ToolExecutionContext(
                    message_id=message_id,
                    correlation_id=correlation_id,
                    caller=ToolCaller.ASSISTANT,
                    confirmed=confirmed,
                    call_index=call_index,
                )

            async with database.transaction() as session:
                executor = ControlledToolExecutor(
                    build_hotel_tool_registry(
                        HotelOperationsService(
                            SQLAlchemyHotelOperationsRepository(session),
                            today=lambda: date(2026, 7, 13),
                        )
                    ),
                    SQLAlchemyToolAuditRepository(session),
                    max_calls_per_turn=10,
                )
                catalog = await executor.execute(
                    ToolCall("list_room_types", {}),
                    execution_context(1, confirmed=False),
                )
                assert catalog.status is ToolExecutionStatus.SUCCEEDED
                assert len(cast(RoomTypesOutput, catalog.output).room_types) == 5

                availability = await executor.execute(
                    ToolCall(
                        "check_room_availability",
                        {
                            "check_in": "2026-08-02",
                            "check_out": "2026-08-04",
                            "adults": 2,
                            "children": 0,
                        },
                    ),
                    execution_context(2, confirmed=False),
                )
                assert availability.status is ToolExecutionStatus.SUCCEEDED
                assert cast(AvailabilityOutput, availability.output).simulation is True

                booking = await executor.execute(
                    ToolCall(
                        "lookup_booking",
                        {
                            "booking_reference": "BKG-2026-0001",
                            "verification_value": "0101",
                        },
                    ),
                    execution_context(3, confirmed=False),
                )
                assert booking.status is ToolExecutionStatus.SUCCEEDED
                assert cast(BookingLookupOutput, booking.output).guest_name_masked == "A*** A***"

                invalid_booking = await executor.execute(
                    ToolCall(
                        "lookup_booking",
                        {
                            "booking_reference": "BKG-2026-0001",
                            "verification_value": "wrong-secret",
                        },
                    ),
                    execution_context(4, confirmed=False),
                )
                assert invalid_booking.status is ToolExecutionStatus.REJECTED
                assert invalid_booking.error_code == "booking_not_found_or_verification_failed"

                request_arguments = {
                    "category": "amenities",
                    "room_number": "102",
                    "description": "Deliver two additional towel sets to the room.",
                    "urgency": "normal",
                    "idempotency_key": idempotency_key,
                }
                unconfirmed = await executor.execute(
                    ToolCall("create_room_service_request", request_arguments),
                    execution_context(5, confirmed=False),
                )
                assert unconfirmed.status is ToolExecutionStatus.REJECTED
                assert unconfirmed.error_code == "tool_confirmation_required"

                created = await executor.execute(
                    ToolCall("create_room_service_request", request_arguments),
                    execution_context(6, confirmed=True),
                )
                retried = await executor.execute(
                    ToolCall("create_room_service_request", request_arguments),
                    execution_context(7, confirmed=True),
                )
                created_output = cast(ServiceRequestCreatedOutput, created.output)
                retried_output = cast(ServiceRequestCreatedOutput, retried.output)
                assert created.status is ToolExecutionStatus.SUCCEEDED
                assert retried.status is ToolExecutionStatus.SUCCEEDED
                assert created_output.created is True
                assert retried_output.created is False
                assert retried_output.tracking_code == created_output.tracking_code

                maintenance = await executor.execute(
                    ToolCall(
                        "create_maintenance_request",
                        {
                            "category": "safety",
                            "room_number": "304",
                            "description": (
                                "A simulated smoke alarm requires immediate staff inspection."
                            ),
                            "urgency": "emergency",
                            "idempotency_key": maintenance_idempotency_key,
                        },
                    ),
                    execution_context(8, confirmed=True),
                )
                maintenance_output = cast(ServiceRequestCreatedOutput, maintenance.output)
                assert maintenance.status is ToolExecutionStatus.SUCCEEDED
                assert maintenance_output.requires_immediate_contact is True
                assert maintenance_output.emergency_guidance_code == (
                    "contact_reception_or_emergency_services"
                )

                request_status = await executor.execute(
                    ToolCall(
                        "get_service_request_status",
                        {"tracking_code": "SR-SEED-0001", "verification_value": "0101"},
                    ),
                    execution_context(9, confirmed=False),
                )
                assert request_status.status is ToolExecutionStatus.SUCCEEDED
                assert cast(ServiceRequestStatusOutput, request_status.output).status == "open"

            async with database.session() as session:
                attempts = (
                    await session.scalars(
                        select(ToolExecution).where(ToolExecution.message_id == message_id)
                    )
                ).all()
                requests = (
                    await session.scalars(
                        select(ServiceRequest).where(
                            ServiceRequest.idempotency_key.in_(
                                [idempotency_key, maintenance_idempotency_key]
                            )
                        )
                    )
                ).all()

            assert len(attempts) == 9
            assert len(requests) == 2
            assert {item.correlation_id for item in attempts} == {correlation_id}
            assert all(item.latency_ms >= 0 for item in attempts)
            assert {(item.tool_name, item.result_status, item.error_code) for item in attempts} >= {
                ("list_room_types", ToolExecutionStatus.SUCCEEDED, None),
                (
                    "lookup_booking",
                    ToolExecutionStatus.REJECTED,
                    "booking_not_found_or_verification_failed",
                ),
                (
                    "create_room_service_request",
                    ToolExecutionStatus.REJECTED,
                    "tool_confirmation_required",
                ),
            }
            serialized_audit = str(
                [(item.arguments_redacted, item.result_redacted) for item in attempts]
            )
            assert "wrong-secret" not in serialized_audit
            assert "0101" not in serialized_audit
            assert "Deliver two additional" not in serialized_audit
            assert idempotency_key not in serialized_audit
            assert maintenance_idempotency_key not in serialized_audit
            assert "[REDACTED]" in serialized_audit
        finally:
            async with database.transaction() as session:
                await session.execute(
                    delete(ServiceRequest).where(
                        ServiceRequest.idempotency_key.in_(
                            [idempotency_key, maintenance_idempotency_key]
                        )
                    )
                )
                await session.execute(
                    delete(ToolExecution).where(ToolExecution.message_id == message_id)
                )
                await session.execute(delete(Message).where(Message.id == message_id))
                await session.execute(
                    delete(Conversation).where(Conversation.id == conversation_id)
                )
                await session.execute(delete(Guest).where(Guest.id == guest_id))
            await database.dispose()

    asyncio.run(exercise())
