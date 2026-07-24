"""Strict schema and cross-reference validation for the synthetic dataset."""

from datetime import date, datetime
from typing import Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from hotel_bot.domain.hotel.enums import (
    BookingStatus,
    RoomOperationalStatus,
    ServiceRequestStatus,
    ServiceRequestType,
    Urgency,
)
from hotel_bot.domain.hotel.policies import SERVICE_CATEGORIES


class SeedModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class HotelProfileSeed(SeedModel):
    code: str = Field(pattern=r"^[a-z0-9-]+$")
    names: dict[str, str]
    description: dict[str, str]
    address: dict[str, str]
    timezone: str
    currency: str = Field(min_length=3, max_length=3)
    check_in_time: str = Field(pattern=r"^([01]\d|2[0-3]):[0-5]\d$")
    check_out_time: str = Field(pattern=r"^([01]\d|2[0-3]):[0-5]\d$")
    reception_email: str
    reception_phone: str


class RoomTypeSeed(SeedModel):
    code: str = Field(pattern=r"^[a-z0-9_]+$")
    names: dict[str, str]
    descriptions: dict[str, str]
    capacity_adults: int = Field(gt=0, le=8)
    capacity_children: int = Field(ge=0, le=8)
    amenities: list[str] = Field(min_length=1)
    active: bool = True


class RoomSeed(SeedModel):
    room_number: str = Field(pattern=r"^[1-9]\d{2,3}$")
    room_type_code: str
    floor: int = Field(ge=0, le=100)
    operational_status: RoomOperationalStatus = RoomOperationalStatus.AVAILABLE


class GuestSeed(SeedModel):
    key: str = Field(pattern=r"^[a-z0-9_]+$")
    preferred_language: str = Field(pattern=r"^(ar|en)$")


class BookingSeed(SeedModel):
    reference: str = Field(pattern=r"^BKG-[A-Z0-9-]{6,24}$")
    guest_key: str
    verification_value: str = Field(min_length=4, max_length=64)
    guest_name_masked: str = Field(min_length=3, max_length=255)
    check_in: date
    check_out: date
    room_type_code: str
    room_number: str | None = None
    adults: int = Field(gt=0, le=8)
    children: int = Field(ge=0, le=8)
    status: BookingStatus

    @model_validator(mode="after")
    def validate_dates(self) -> Self:
        if self.check_out <= self.check_in:
            raise ValueError("booking check_out must be after check_in")
        return self


class ServiceRequestSeed(SeedModel):
    tracking_code: str = Field(pattern=r"^SR-[A-Z0-9-]{6,24}$")
    request_type: ServiceRequestType
    category: str
    room_number: str
    booking_reference: str | None = None
    description: str = Field(min_length=10, max_length=1000)
    urgency: Urgency
    status: ServiceRequestStatus
    idempotency_key: str = Field(min_length=16, max_length=128)
    completed_at: datetime | None = None

    @model_validator(mode="after")
    def validate_request(self) -> Self:
        if self.category not in SERVICE_CATEGORIES[self.request_type]:
            raise ValueError("service request category does not match its type")
        if self.status is ServiceRequestStatus.COMPLETED and self.completed_at is None:
            raise ValueError("completed service request requires completed_at")
        if self.status is not ServiceRequestStatus.COMPLETED and self.completed_at is not None:
            raise ValueError("only completed service requests may have completed_at")
        return self


class HotelSeedDataset(SeedModel):
    dataset_version: str = Field(pattern=r"^\d+\.\d+\.\d+$")
    hotel: HotelProfileSeed
    room_types: list[RoomTypeSeed] = Field(min_length=1)
    rooms: list[RoomSeed] = Field(min_length=1)
    guests: list[GuestSeed] = Field(min_length=1)
    bookings: list[BookingSeed]
    service_requests: list[ServiceRequestSeed]

    @model_validator(mode="after")
    def validate_references(self) -> Self:
        self._assert_unique("room type codes", [item.code for item in self.room_types])
        self._assert_unique("room numbers", [item.room_number for item in self.rooms])
        self._assert_unique("guest keys", [item.key for item in self.guests])
        self._assert_unique("booking references", [item.reference for item in self.bookings])
        self._assert_unique(
            "service tracking codes", [item.tracking_code for item in self.service_requests]
        )
        self._assert_unique(
            "service idempotency keys", [item.idempotency_key for item in self.service_requests]
        )

        room_types = {item.code: item for item in self.room_types}
        rooms = {item.room_number: item for item in self.rooms}
        guests = {item.key for item in self.guests}
        bookings = {item.reference for item in self.bookings}

        for room in self.rooms:
            if room.room_type_code not in room_types:
                raise ValueError(f"room {room.room_number} has an unknown room type")
        for booking in self.bookings:
            if booking.guest_key not in guests:
                raise ValueError(f"booking {booking.reference} has an unknown guest")
            room_type = room_types.get(booking.room_type_code)
            if room_type is None:
                raise ValueError(f"booking {booking.reference} has an unknown room type")
            if booking.adults > room_type.capacity_adults:
                raise ValueError(f"booking {booking.reference} exceeds adult capacity")
            if booking.children > room_type.capacity_children:
                raise ValueError(f"booking {booking.reference} exceeds child capacity")
            if booking.room_number:
                assigned_room = rooms.get(booking.room_number)
                if assigned_room is None or assigned_room.room_type_code != booking.room_type_code:
                    raise ValueError(f"booking {booking.reference} room/type mismatch")
        for request in self.service_requests:
            if request.room_number not in rooms:
                raise ValueError(f"service request {request.tracking_code} has an unknown room")
            if request.booking_reference and request.booking_reference not in bookings:
                raise ValueError(f"service request {request.tracking_code} has an unknown booking")
        return self

    @staticmethod
    def _assert_unique(label: str, values: list[str]) -> None:
        if len(values) != len(set(values)):
            raise ValueError(f"duplicate {label} in seed dataset")
