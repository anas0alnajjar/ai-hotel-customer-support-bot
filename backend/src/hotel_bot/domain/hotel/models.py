"""Immutable domain snapshots and results for hotel operations."""

from dataclasses import dataclass
from datetime import date, datetime
from uuid import UUID

from hotel_bot.domain.hotel.enums import (
    BookingStatus,
    RoomOperationalStatus,
    ServiceRequestStatus,
    ServiceRequestType,
    Urgency,
)


@dataclass(frozen=True, slots=True)
class RoomTypeSnapshot:
    id: UUID
    code: str
    names: dict[str, str]
    descriptions: dict[str, str]
    capacity_adults: int
    capacity_children: int
    amenities: tuple[str, ...]
    active: bool


@dataclass(frozen=True, slots=True)
class RoomSnapshot:
    id: UUID
    room_number: str
    room_type_id: UUID
    operational_status: RoomOperationalStatus


@dataclass(frozen=True, slots=True)
class BookingSnapshot:
    id: UUID
    reference: str
    guest_verification_hash: str
    guest_name_masked: str
    check_in: date
    check_out: date
    room_type_id: UUID
    room_id: UUID | None
    adults: int
    children: int
    status: BookingStatus


@dataclass(frozen=True, slots=True)
class InventorySnapshot:
    room_types: tuple[RoomTypeSnapshot, ...]
    rooms: tuple[RoomSnapshot, ...]
    overlapping_bookings: tuple[BookingSnapshot, ...]


@dataclass(frozen=True, slots=True)
class AvailabilityOption:
    room_type_code: str
    names: dict[str, str]
    capacity_adults: int
    capacity_children: int
    available_rooms: int
    amenities: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class AvailabilityResult:
    check_in: date
    check_out: date
    adults: int
    children: int
    options: tuple[AvailabilityOption, ...]
    simulation: bool = True


@dataclass(frozen=True, slots=True)
class BookingSummary:
    reference: str
    guest_name_masked: str
    check_in: date
    check_out: date
    room_type_code: str
    room_number: str | None
    adults: int
    children: int
    status: BookingStatus
    simulation: bool = True


@dataclass(frozen=True, slots=True)
class NewServiceRequest:
    id: UUID
    tracking_code: str
    request_type: ServiceRequestType
    category: str
    room_id: UUID
    booking_id: UUID | None
    requested_by_guest_id: UUID | None
    description: str
    urgency: Urgency
    idempotency_key: str


@dataclass(frozen=True, slots=True)
class ServiceRequestSnapshot:
    id: UUID
    tracking_code: str
    request_type: ServiceRequestType
    category: str
    room_id: UUID
    booking_id: UUID | None
    requested_by_guest_id: UUID | None
    description: str
    urgency: Urgency
    status: ServiceRequestStatus
    idempotency_key: str
    created_at: datetime | None = None
    updated_at: datetime | None = None
    completed_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class ServiceRequestCreationResult:
    request: ServiceRequestSnapshot
    created: bool
    requires_immediate_contact: bool
    emergency_guidance_code: str | None
