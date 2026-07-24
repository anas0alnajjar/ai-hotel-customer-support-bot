"""Load and idempotently insert the versioned fictional hotel dataset."""

import hashlib
import json
from collections import Counter
from dataclasses import dataclass
from importlib.resources import files
from typing import Any, TypeVar
from uuid import NAMESPACE_URL, UUID, uuid5

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import DeclarativeBase, InstrumentedAttribute

from hotel_bot.domain.hotel.security import (
    deterministic_seed_salt,
    hash_verification_value,
)
from hotel_bot.persistence.models import Booking, Guest, Room, RoomType, ServiceRequest
from hotel_bot.seed.schema import HotelSeedDataset

SEED_NAMESPACE = uuid5(NAMESPACE_URL, "https://example.invalid/nour-al-sham-grand/v1")
ModelT = TypeVar("ModelT", bound=DeclarativeBase)


class SeedConflict(RuntimeError):
    """Raised when a natural key is already owned by a non-seed identifier."""


@dataclass(frozen=True, slots=True)
class HotelSeedResult:
    dataset_version: str
    inserted: dict[str, int]
    existing: dict[str, int]

    @property
    def inserted_total(self) -> int:
        return sum(self.inserted.values())

    @property
    def existing_total(self) -> int:
        return sum(self.existing.values())


def stable_seed_id(entity: str, natural_key: str) -> UUID:
    return uuid5(SEED_NAMESPACE, f"{entity}:{natural_key}")


def load_seed_dataset() -> HotelSeedDataset:
    resource = files("hotel_bot.seed").joinpath("data/nour-al-sham-v1.json")
    payload = json.loads(resource.read_text(encoding="utf-8"))
    return HotelSeedDataset.model_validate(payload)


class HotelSeeder:
    """Ensure deterministic seed rows exist without resetting later operational changes."""

    def __init__(self, session: AsyncSession, dataset: HotelSeedDataset | None = None) -> None:
        self._session = session
        self._dataset = dataset or load_seed_dataset()
        self._inserted: Counter[str] = Counter()
        self._existing: Counter[str] = Counter()

    async def seed(self) -> HotelSeedResult:
        room_type_ids = await self._seed_room_types()
        room_ids = await self._seed_rooms(room_type_ids)
        guest_ids = await self._seed_guests()
        booking_ids = await self._seed_bookings(room_type_ids, room_ids)
        await self._seed_service_requests(room_ids, guest_ids, booking_ids)
        return HotelSeedResult(
            dataset_version=self._dataset.dataset_version,
            inserted=dict(self._inserted),
            existing=dict(self._existing),
        )

    async def _seed_room_types(self) -> dict[str, UUID]:
        identifiers: dict[str, UUID] = {}
        for item in self._dataset.room_types:
            identifier = stable_seed_id("room-type", item.code)
            identifiers[item.code] = identifier
            if await self._exists_or_raise(
                RoomType,
                identifier,
                RoomType.id,
                RoomType.code,
                item.code,
                "room_types",
            ):
                continue
            self._session.add(
                RoomType(
                    id=identifier,
                    code=item.code,
                    name_json=dict(item.names),
                    description_json=dict(item.descriptions),
                    capacity_adults=item.capacity_adults,
                    capacity_children=item.capacity_children,
                    amenities_json=list(item.amenities),
                    active=item.active,
                )
            )
            self._inserted["room_types"] += 1
        await self._session.flush()
        return identifiers

    async def _seed_rooms(self, room_type_ids: dict[str, UUID]) -> dict[str, UUID]:
        identifiers: dict[str, UUID] = {}
        for item in self._dataset.rooms:
            identifier = stable_seed_id("room", item.room_number)
            identifiers[item.room_number] = identifier
            if await self._exists_or_raise(
                Room,
                identifier,
                Room.id,
                Room.room_number,
                item.room_number,
                "rooms",
            ):
                continue
            self._session.add(
                Room(
                    id=identifier,
                    room_number=item.room_number,
                    room_type_id=room_type_ids[item.room_type_code],
                    floor=item.floor,
                    operational_status=item.operational_status,
                )
            )
            self._inserted["rooms"] += 1
        await self._session.flush()
        return identifiers

    async def _seed_guests(self) -> dict[str, UUID]:
        identifiers: dict[str, UUID] = {}
        for item in self._dataset.guests:
            identifier = stable_seed_id("guest", item.key)
            identifiers[item.key] = identifier
            telegram_hash = hashlib.sha256(
                f"nour-al-sham-synthetic-telegram:{item.key}".encode()
            ).hexdigest()
            if await self._exists_or_raise(
                Guest,
                identifier,
                Guest.id,
                Guest.telegram_user_hash,
                telegram_hash,
                "guests",
            ):
                continue
            self._session.add(
                Guest(
                    id=identifier,
                    telegram_user_hash=telegram_hash,
                    preferred_language=item.preferred_language,
                )
            )
            self._inserted["guests"] += 1
        await self._session.flush()
        return identifiers

    async def _seed_bookings(
        self, room_type_ids: dict[str, UUID], room_ids: dict[str, UUID]
    ) -> dict[str, UUID]:
        identifiers: dict[str, UUID] = {}
        for item in self._dataset.bookings:
            identifier = stable_seed_id("booking", item.reference)
            identifiers[item.reference] = identifier
            if await self._exists_or_raise(
                Booking,
                identifier,
                Booking.id,
                Booking.reference,
                item.reference,
                "bookings",
            ):
                continue
            verification_hash = hash_verification_value(
                item.verification_value,
                salt=deterministic_seed_salt(item.reference),
            )
            self._session.add(
                Booking(
                    id=identifier,
                    reference=item.reference,
                    guest_verification_hash=verification_hash,
                    guest_name_masked=item.guest_name_masked,
                    check_in=item.check_in,
                    check_out=item.check_out,
                    room_type_id=room_type_ids[item.room_type_code],
                    room_id=room_ids[item.room_number] if item.room_number else None,
                    adults=item.adults,
                    children=item.children,
                    status=item.status,
                )
            )
            self._inserted["bookings"] += 1
        await self._session.flush()
        return identifiers

    async def _seed_service_requests(
        self,
        room_ids: dict[str, UUID],
        guest_ids: dict[str, UUID],
        booking_ids: dict[str, UUID],
    ) -> None:
        bookings_by_reference = {item.reference: item for item in self._dataset.bookings}
        for item in self._dataset.service_requests:
            identifier = stable_seed_id("service-request", item.tracking_code)
            if await self._exists_or_raise(
                ServiceRequest,
                identifier,
                ServiceRequest.id,
                ServiceRequest.tracking_code,
                item.tracking_code,
                "service_requests",
            ):
                continue
            booking = (
                bookings_by_reference[item.booking_reference] if item.booking_reference else None
            )
            self._session.add(
                ServiceRequest(
                    id=identifier,
                    tracking_code=item.tracking_code,
                    type=item.request_type,
                    category=item.category,
                    room_id=room_ids[item.room_number],
                    booking_id=(
                        booking_ids[item.booking_reference] if item.booking_reference else None
                    ),
                    requested_by_guest_id=guest_ids[booking.guest_key] if booking else None,
                    description=item.description,
                    urgency=item.urgency,
                    status=item.status,
                    idempotency_key=item.idempotency_key,
                    completed_at=item.completed_at,
                )
            )
            self._inserted["service_requests"] += 1
        await self._session.flush()

    async def _exists_or_raise(
        self,
        model: type[ModelT],
        expected_id: UUID,
        id_column: InstrumentedAttribute[UUID],
        natural_column: InstrumentedAttribute[Any],
        natural_value: object,
        counter_name: str,
    ) -> bool:
        existing = await self._session.get(model, expected_id)
        natural_id = await self._session.scalar(
            select(id_column).where(natural_column == natural_value).limit(1)
        )
        if natural_id is not None and natural_id != expected_id:
            raise SeedConflict(f"{counter_name} natural key is owned by a non-seed identifier")
        if existing is not None:
            self._existing[counter_name] += 1
            return True
        return False
