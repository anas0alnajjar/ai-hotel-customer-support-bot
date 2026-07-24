"""SQLAlchemy adapter for deterministic hotel operations."""

from datetime import date, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from hotel_bot.domain.hotel.enums import (
    BookingStatus,
    RoomOperationalStatus,
    ServiceRequestStatus,
    ServiceRequestType,
    Urgency,
)
from hotel_bot.domain.hotel.errors import InvalidStatusTransition, ServiceRequestNotFound
from hotel_bot.domain.hotel.models import (
    BookingSnapshot,
    InventorySnapshot,
    NewServiceRequest,
    RoomSnapshot,
    RoomTypeSnapshot,
    ServiceRequestSnapshot,
)
from hotel_bot.persistence.models import Booking, Room, RoomType, ServiceRequest


class SQLAlchemyHotelOperationsRepository:
    """Map authoritative MySQL rows to immutable domain snapshots."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def load_inventory(self, check_in: date, check_out: date) -> InventorySnapshot:
        room_types = (await self._session.scalars(select(RoomType))).all()
        rooms = (await self._session.scalars(select(Room))).all()
        bookings = (
            await self._session.scalars(
                select(Booking).where(
                    Booking.check_in < check_out,
                    Booking.check_out > check_in,
                )
            )
        ).all()
        return InventorySnapshot(
            room_types=tuple(self._map_room_type(item) for item in room_types),
            rooms=tuple(self._map_room(item) for item in rooms),
            overlapping_bookings=tuple(self._map_booking(item) for item in bookings),
        )

    async def list_room_types(self, *, active_only: bool) -> tuple[RoomTypeSnapshot, ...]:
        statement = select(RoomType).order_by(RoomType.code)
        if active_only:
            statement = statement.where(RoomType.active.is_(True))
        rows = (await self._session.scalars(statement)).all()
        return tuple(self._map_room_type(item) for item in rows)

    async def get_room_type(self, room_type_id: UUID) -> RoomTypeSnapshot | None:
        row = await self._session.get(RoomType, room_type_id)
        return self._map_room_type(row) if row else None

    async def get_room_by_id(self, room_id: UUID) -> RoomSnapshot | None:
        row = await self._session.get(Room, room_id)
        return self._map_room(row) if row else None

    async def get_room_by_number(self, room_number: str) -> RoomSnapshot | None:
        row = await self._session.scalar(
            select(Room).where(Room.room_number == room_number).limit(1)
        )
        return self._map_room(row) if row else None

    async def get_booking(self, reference: str) -> BookingSnapshot | None:
        row = await self._session.scalar(
            select(Booking).where(Booking.reference == reference).limit(1)
        )
        return self._map_booking(row) if row else None

    async def get_booking_by_id(self, booking_id: UUID) -> BookingSnapshot | None:
        row = await self._session.get(Booking, booking_id)
        return self._map_booking(row) if row else None

    async def get_service_request_by_tracking_code(
        self, tracking_code: str
    ) -> ServiceRequestSnapshot | None:
        row = await self._session.scalar(
            select(ServiceRequest).where(ServiceRequest.tracking_code == tracking_code).limit(1)
        )
        return self._map_service_request(row) if row else None

    async def get_or_create_service_request(
        self, request: NewServiceRequest
    ) -> tuple[ServiceRequestSnapshot, bool]:
        existing = await self._session.scalar(
            select(ServiceRequest)
            .where(ServiceRequest.idempotency_key == request.idempotency_key)
            .with_for_update()
            .limit(1)
        )
        if existing is not None:
            return self._map_service_request(existing), False

        row = ServiceRequest(
            id=request.id,
            tracking_code=request.tracking_code,
            type=request.request_type,
            category=request.category,
            room_id=request.room_id,
            booking_id=request.booking_id,
            requested_by_guest_id=request.requested_by_guest_id,
            description=request.description,
            urgency=request.urgency,
            status=ServiceRequestStatus.OPEN,
            idempotency_key=request.idempotency_key,
        )
        self._session.add(row)
        await self._session.flush()
        await self._session.refresh(row)
        return self._map_service_request(row), True

    async def transition_service_request(
        self,
        request_id: UUID,
        current: ServiceRequestStatus,
        target: ServiceRequestStatus,
        *,
        completed_at: datetime | None,
    ) -> ServiceRequestSnapshot:
        row = await self._session.scalar(
            select(ServiceRequest).where(ServiceRequest.id == request_id).with_for_update().limit(1)
        )
        if row is None:
            raise ServiceRequestNotFound(
                "service_request_not_found", "service request was not found"
            )
        if row.status is not current:
            raise InvalidStatusTransition(
                "concurrent_status_change",
                "service request status changed before this transition was committed",
            )
        row.status = target
        row.completed_at = completed_at
        await self._session.flush()
        await self._session.refresh(row)
        return self._map_service_request(row)

    @staticmethod
    def _map_room_type(row: RoomType) -> RoomTypeSnapshot:
        return RoomTypeSnapshot(
            id=row.id,
            code=row.code,
            names=row.name_json,
            descriptions=row.description_json,
            capacity_adults=row.capacity_adults,
            capacity_children=row.capacity_children,
            amenities=tuple(row.amenities_json),
            active=row.active,
        )

    @staticmethod
    def _map_room(row: Room) -> RoomSnapshot:
        return RoomSnapshot(
            id=row.id,
            room_number=row.room_number,
            room_type_id=row.room_type_id,
            operational_status=RoomOperationalStatus(row.operational_status),
        )

    @staticmethod
    def _map_booking(row: Booking) -> BookingSnapshot:
        return BookingSnapshot(
            id=row.id,
            reference=row.reference,
            guest_verification_hash=row.guest_verification_hash,
            guest_name_masked=row.guest_name_masked,
            check_in=row.check_in,
            check_out=row.check_out,
            room_type_id=row.room_type_id,
            room_id=row.room_id,
            adults=row.adults,
            children=row.children,
            status=BookingStatus(row.status),
        )

    @staticmethod
    def _map_service_request(row: ServiceRequest) -> ServiceRequestSnapshot:
        return ServiceRequestSnapshot(
            id=row.id,
            tracking_code=row.tracking_code,
            request_type=ServiceRequestType(row.type),
            category=row.category,
            room_id=row.room_id,
            booking_id=row.booking_id,
            requested_by_guest_id=row.requested_by_guest_id,
            description=row.description,
            urgency=Urgency(row.urgency),
            status=ServiceRequestStatus(row.status),
            idempotency_key=row.idempotency_key,
            created_at=row.created_at,
            updated_at=row.updated_at,
            completed_at=row.completed_at,
        )
