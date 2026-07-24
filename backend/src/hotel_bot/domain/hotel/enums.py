"""Hotel-operation states shared by domain and persistence adapters."""

from enum import StrEnum


class BookingStatus(StrEnum):
    PENDING = "pending"
    CONFIRMED = "confirmed"
    CHECKED_IN = "checked_in"
    CHECKED_OUT = "checked_out"
    CANCELLED = "cancelled"


class RoomOperationalStatus(StrEnum):
    AVAILABLE = "available"
    OCCUPIED = "occupied"
    CLEANING = "cleaning"
    MAINTENANCE = "maintenance"
    OUT_OF_SERVICE = "out_of_service"


class ServiceRequestType(StrEnum):
    ROOM_SERVICE = "room_service"
    MAINTENANCE = "maintenance"


class Urgency(StrEnum):
    NORMAL = "normal"
    HIGH = "high"
    EMERGENCY = "emergency"


class ServiceRequestStatus(StrEnum):
    OPEN = "open"
    ACKNOWLEDGED = "acknowledged"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    CANCELLED = "cancelled"
