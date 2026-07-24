"""Real-MySQL tests for repeatable seeding and hotel operation use cases."""

import asyncio
import os
from datetime import date
from pathlib import Path

import pytest
from pydantic import SecretStr
from sqlalchemy import delete, select

from hotel_bot.application.hotel_operations import HotelOperationsService
from hotel_bot.core.config import Settings
from hotel_bot.domain.hotel.enums import (
    RoomOperationalStatus,
    ServiceRequestStatus,
    ServiceRequestType,
    Urgency,
)
from hotel_bot.domain.hotel.errors import (
    IdempotencyConflict,
    InvalidStatusTransition,
    VerificationFailed,
)
from hotel_bot.infrastructure.database import DatabaseManager
from hotel_bot.infrastructure.repositories.hotel_operations import (
    SQLAlchemyHotelOperationsRepository,
)
from hotel_bot.persistence.models import Booking, Guest, Room, RoomType, ServiceRequest
from hotel_bot.seed import HotelSeeder, load_seed_dataset
from hotel_bot.seed.loader import stable_seed_id

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


async def ensure_seeded(database: DatabaseManager) -> None:
    async with database.transaction() as session:
        await HotelSeeder(session).seed()


def test_seed_is_repeatable_privacy_safe_and_does_not_reset_existing_rows() -> None:
    async def exercise_seed() -> None:
        database = DatabaseManager(mysql_settings())
        dataset = load_seed_dataset()
        try:
            await ensure_seeded(database)
            async with database.transaction() as session:
                second = await HotelSeeder(session, dataset).seed()

            assert second.inserted_total == 0
            assert second.existing == {
                "room_types": 5,
                "rooms": 22,
                "guests": 6,
                "bookings": 8,
                "service_requests": 3,
            }

            room_101_id = stable_seed_id("room", "101")
            async with database.transaction() as session:
                room_101 = await session.get(Room, room_101_id)
                assert room_101 is not None
                room_101.operational_status = RoomOperationalStatus.CLEANING

            async with database.transaction() as session:
                third = await HotelSeeder(session, dataset).seed()
                room_101 = await session.get(Room, room_101_id)
                assert room_101 is not None
                assert room_101.operational_status is RoomOperationalStatus.CLEANING
                assert third.inserted_total == 0
                room_101.operational_status = RoomOperationalStatus.AVAILABLE

            async with database.session() as session:
                room_type_ids = [
                    stable_seed_id("room-type", item.code) for item in dataset.room_types
                ]
                room_ids = [stable_seed_id("room", item.room_number) for item in dataset.rooms]
                guest_ids = [stable_seed_id("guest", item.key) for item in dataset.guests]
                booking_ids = [
                    stable_seed_id("booking", item.reference) for item in dataset.bookings
                ]
                request_ids = [
                    stable_seed_id("service-request", item.tracking_code)
                    for item in dataset.service_requests
                ]
                assert len(
                    (
                        await session.scalars(
                            select(RoomType.id).where(RoomType.id.in_(room_type_ids))
                        )
                    ).all()
                ) == len(room_type_ids)
                assert len(
                    (await session.scalars(select(Room.id).where(Room.id.in_(room_ids)))).all()
                ) == len(room_ids)
                assert len(
                    (await session.scalars(select(Guest.id).where(Guest.id.in_(guest_ids)))).all()
                ) == len(guest_ids)
                assert len(
                    (
                        await session.scalars(select(Booking.id).where(Booking.id.in_(booking_ids)))
                    ).all()
                ) == len(booking_ids)
                assert len(
                    (
                        await session.scalars(
                            select(ServiceRequest.id).where(ServiceRequest.id.in_(request_ids))
                        )
                    ).all()
                ) == len(request_ids)
                booking = await session.scalar(
                    select(Booking).where(Booking.reference == "BKG-2026-0001")
                )
                assert booking is not None
                assert booking.guest_verification_hash.startswith("pbkdf2_sha256$")
                assert booking.guest_verification_hash != "0101"
        finally:
            await database.dispose()

    asyncio.run(exercise_seed())


def test_mysql_operations_match_seeded_inventory_and_privacy_rules() -> None:
    async def exercise_operations() -> None:
        database = DatabaseManager(mysql_settings())
        try:
            await ensure_seeded(database)
            async with database.session() as session:
                service = HotelOperationsService(
                    SQLAlchemyHotelOperationsRepository(session),
                    today=lambda: date(2026, 7, 13),
                )
                result = await service.check_availability(
                    check_in=date(2026, 8, 2),
                    check_out=date(2026, 8, 4),
                    adults=2,
                )
                counts = {
                    option.room_type_code: option.available_rooms for option in result.options
                }
                assert counts == {
                    "deluxe_king": 3,
                    "executive_suite": 3,
                    "family_suite": 3,
                    "standard_king": 3,
                    "standard_twin": 4,
                }

                booking = await service.lookup_booking("bkg-2026-0001", "0101")
                assert booking.reference == "BKG-2026-0001"
                assert booking.guest_name_masked == "A*** A***"
                assert booking.room_number == "101"
                with pytest.raises(VerificationFailed):
                    await service.lookup_booking("BKG-2026-0001", "9999")

                request = await service.get_service_request_status("sr-seed-0001", "0101")
                assert request.status is ServiceRequestStatus.OPEN
                with pytest.raises(VerificationFailed):
                    await service.get_service_request_status("SR-SEED-0001", "9999")
        finally:
            await database.dispose()

    asyncio.run(exercise_operations())


def test_mysql_service_request_creation_is_idempotent_and_transactional() -> None:
    async def exercise_request() -> None:
        database = DatabaseManager(mysql_settings())
        try:
            await ensure_seeded(database)
            async with database.transaction() as session:
                service = HotelOperationsService(SQLAlchemyHotelOperationsRepository(session))
                first = await service.create_service_request(
                    request_type=ServiceRequestType.ROOM_SERVICE,
                    category="amenities",
                    room_number="102",
                    description="Please deliver two additional towel sets.",
                    urgency=Urgency.NORMAL,
                    idempotency_key="integration-service-request-0001",
                )
                retry = await service.create_service_request(
                    request_type=ServiceRequestType.ROOM_SERVICE,
                    category="amenities",
                    room_number="102",
                    description="Please deliver two additional towel sets.",
                    urgency=Urgency.NORMAL,
                    idempotency_key="integration-service-request-0001",
                )
                assert first.created is True
                assert retry.created is False
                assert retry.request.tracking_code == first.request.tracking_code

                with pytest.raises(IdempotencyConflict):
                    await service.create_service_request(
                        request_type=ServiceRequestType.ROOM_SERVICE,
                        category="amenities",
                        room_number="102",
                        description="This payload is intentionally different.",
                        urgency=Urgency.NORMAL,
                        idempotency_key="integration-service-request-0001",
                    )

                emergency = await service.create_service_request(
                    request_type=ServiceRequestType.MAINTENANCE,
                    category="safety",
                    room_number="304",
                    description="A simulated safety alarm requires immediate staff inspection.",
                    urgency=Urgency.EMERGENCY,
                    idempotency_key="integration-emergency-request-0001",
                )
                assert emergency.requires_immediate_contact is True
                assert emergency.emergency_guidance_code == (
                    "contact_reception_or_emergency_services"
                )
                assert emergency.request.status is ServiceRequestStatus.OPEN

                await session.execute(
                    delete(ServiceRequest).where(
                        ServiceRequest.id.in_([first.request.id, emergency.request.id])
                    )
                )
        finally:
            await database.dispose()

    asyncio.run(exercise_request())


def test_status_transition_rolls_back_when_session_is_not_committed() -> None:
    async def exercise_transition() -> None:
        database = DatabaseManager(mysql_settings())
        try:
            await ensure_seeded(database)
            async with database.session() as session:
                repository = SQLAlchemyHotelOperationsRepository(session)
                service = HotelOperationsService(repository)
                updated = await service.transition_service_request(
                    "SR-SEED-0001", ServiceRequestStatus.ACKNOWLEDGED
                )
                assert updated.status is ServiceRequestStatus.ACKNOWLEDGED

            async with database.session() as session:
                row = await session.scalar(
                    select(ServiceRequest).where(ServiceRequest.tracking_code == "SR-SEED-0001")
                )
                assert row is not None
                assert row.status is ServiceRequestStatus.OPEN

                with pytest.raises(InvalidStatusTransition) as error:
                    await SQLAlchemyHotelOperationsRepository(session).transition_service_request(
                        row.id,
                        ServiceRequestStatus.ACKNOWLEDGED,
                        ServiceRequestStatus.IN_PROGRESS,
                        completed_at=None,
                    )
                assert error.value.code == "concurrent_status_change"
        finally:
            await database.dispose()

    asyncio.run(exercise_transition())
