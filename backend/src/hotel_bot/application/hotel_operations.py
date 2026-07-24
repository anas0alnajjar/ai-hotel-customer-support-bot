"""Hotel operation use cases over a provider-neutral repository contract."""

from collections.abc import Callable
from datetime import UTC, date, datetime
from typing import Protocol
from uuid import UUID

from hotel_bot.domain.hotel.enums import (
    RoomOperationalStatus,
    ServiceRequestStatus,
    ServiceRequestType,
    Urgency,
)
from hotel_bot.domain.hotel.errors import (
    BookingNotFound,
    InvalidServiceRequest,
    RoomNotFound,
    ServiceRequestNotFound,
    VerificationFailed,
)
from hotel_bot.domain.hotel.models import (
    AvailabilityResult,
    BookingSnapshot,
    BookingSummary,
    InventorySnapshot,
    NewServiceRequest,
    RoomSnapshot,
    RoomTypeSnapshot,
    ServiceRequestCreationResult,
    ServiceRequestSnapshot,
)
from hotel_bot.domain.hotel.policies import (
    assert_idempotent_payload_matches,
    build_new_service_request,
    calculate_availability,
    requires_immediate_contact,
    validate_status_transition,
)
from hotel_bot.domain.hotel.security import verify_verification_value


class HotelOperationsRepository(Protocol):
    async def load_inventory(self, check_in: date, check_out: date) -> InventorySnapshot: ...

    async def list_room_types(self, *, active_only: bool) -> tuple[RoomTypeSnapshot, ...]: ...

    async def get_room_type(self, room_type_id: UUID) -> RoomTypeSnapshot | None: ...

    async def get_room_by_id(self, room_id: UUID) -> RoomSnapshot | None: ...

    async def get_room_by_number(self, room_number: str) -> RoomSnapshot | None: ...

    async def get_booking(self, reference: str) -> BookingSnapshot | None: ...

    async def get_booking_by_id(self, booking_id: UUID) -> BookingSnapshot | None: ...

    async def get_service_request_by_tracking_code(
        self, tracking_code: str
    ) -> ServiceRequestSnapshot | None: ...

    async def get_or_create_service_request(
        self, request: NewServiceRequest
    ) -> tuple[ServiceRequestSnapshot, bool]: ...

    async def transition_service_request(
        self,
        request_id: UUID,
        current: ServiceRequestStatus,
        target: ServiceRequestStatus,
        *,
        completed_at: datetime | None,
    ) -> ServiceRequestSnapshot: ...


def utc_now_naive() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


class HotelOperationsService:
    """Execute deterministic hotel operations without any LLM dependency."""

    def __init__(
        self,
        repository: HotelOperationsRepository,
        *,
        today: Callable[[], date] = date.today,
        clock: Callable[[], datetime] = utc_now_naive,
    ) -> None:
        self._repository = repository
        self._today = today
        self._clock = clock

    async def list_room_types(self) -> tuple[RoomTypeSnapshot, ...]:
        return await self._repository.list_room_types(active_only=True)

    async def check_availability(
        self,
        *,
        check_in: date,
        check_out: date,
        adults: int,
        children: int = 0,
        room_type_code: str | None = None,
    ) -> AvailabilityResult:
        inventory = await self._repository.load_inventory(check_in, check_out)
        return calculate_availability(
            inventory,
            check_in=check_in,
            check_out=check_out,
            adults=adults,
            children=children,
            today=self._today(),
            room_type_code=room_type_code,
        )

    async def lookup_booking(
        self, booking_reference: str, verification_value: str
    ) -> BookingSummary:
        reference = booking_reference.strip().upper()
        if not 6 <= len(reference) <= 32:
            raise BookingNotFound(
                "booking_not_found_or_verification_failed", "booking could not be verified"
            )

        booking = await self._repository.get_booking(reference)
        if booking is None:
            raise BookingNotFound(
                "booking_not_found_or_verification_failed", "booking could not be verified"
            )
        if not verify_verification_value(verification_value, booking.guest_verification_hash):
            raise VerificationFailed(
                "booking_not_found_or_verification_failed", "booking could not be verified"
            )

        room_type = await self._repository.get_room_type(booking.room_type_id)
        if room_type is None:
            raise BookingNotFound("booking_data_incomplete", "booking data is incomplete")
        room_number: str | None = None
        if booking.room_id is not None:
            room = await self._repository.get_room_by_id(booking.room_id)
            room_number = room.room_number if room else None

        return BookingSummary(
            reference=booking.reference,
            guest_name_masked=booking.guest_name_masked,
            check_in=booking.check_in,
            check_out=booking.check_out,
            room_type_code=room_type.code,
            room_number=room_number,
            adults=booking.adults,
            children=booking.children,
            status=booking.status,
        )

    async def create_service_request(
        self,
        *,
        request_type: ServiceRequestType,
        category: str,
        room_number: str,
        description: str,
        urgency: Urgency,
        idempotency_key: str,
        booking_reference: str | None = None,
        verification_value: str | None = None,
    ) -> ServiceRequestCreationResult:
        room = await self._repository.get_room_by_number(room_number.strip().upper())
        if room is None:
            raise RoomNotFound("room_not_found", "room number was not found")
        if (
            request_type is ServiceRequestType.ROOM_SERVICE
            and room.operational_status is RoomOperationalStatus.OUT_OF_SERVICE
        ):
            raise InvalidServiceRequest(
                "room_out_of_service", "room service cannot be created for an out-of-service room"
            )

        booking: BookingSnapshot | None = None
        if booking_reference is not None or verification_value is not None:
            if not booking_reference or not verification_value:
                raise VerificationFailed(
                    "booking_verification_incomplete",
                    "booking reference and verification value are both required",
                )
            await self.lookup_booking(booking_reference, verification_value)
            booking = await self._repository.get_booking(booking_reference.strip().upper())
            if booking is None or (booking.room_id is not None and booking.room_id != room.id):
                raise VerificationFailed(
                    "room_booking_mismatch", "booking could not be verified for this room"
                )

        requested = build_new_service_request(
            request_type=request_type,
            category=category,
            room_id=room.id,
            booking_id=booking.id if booking else None,
            requested_by_guest_id=None,
            description=description,
            urgency=urgency,
            idempotency_key=idempotency_key,
        )
        stored, created = await self._repository.get_or_create_service_request(requested)
        if not created:
            assert_idempotent_payload_matches(stored, requested)

        emergency = requires_immediate_contact(stored)
        return ServiceRequestCreationResult(
            request=stored,
            created=created,
            requires_immediate_contact=emergency,
            emergency_guidance_code="contact_reception_or_emergency_services"
            if emergency
            else None,
        )

    async def get_service_request_status(
        self, tracking_code: str, verification_value: str
    ) -> ServiceRequestSnapshot:
        request = await self._repository.get_service_request_by_tracking_code(
            tracking_code.strip().upper()
        )
        if request is None:
            raise ServiceRequestNotFound(
                "service_request_not_found", "service request could not be verified"
            )
        if request.booking_id is None:
            raise VerificationFailed(
                "service_request_verification_unavailable",
                "service request requires staff-assisted verification",
            )
        booking = await self._repository.get_booking_by_id(request.booking_id)
        if booking is None or not verify_verification_value(
            verification_value, booking.guest_verification_hash
        ):
            raise VerificationFailed("verification_failed", "service request could not be verified")
        return request

    async def transition_service_request(
        self, tracking_code: str, target: ServiceRequestStatus
    ) -> ServiceRequestSnapshot:
        request = await self._repository.get_service_request_by_tracking_code(
            tracking_code.strip().upper()
        )
        if request is None:
            raise ServiceRequestNotFound(
                "service_request_not_found", "service request was not found"
            )
        validate_status_transition(request.status, target)
        completed_at = self._clock() if target is ServiceRequestStatus.COMPLETED else None
        return await self._repository.transition_service_request(
            request.id, request.status, target, completed_at=completed_at
        )
