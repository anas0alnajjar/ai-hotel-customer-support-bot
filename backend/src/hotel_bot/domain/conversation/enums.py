"""Conversation-domain enumerations shared by application and persistence layers."""

from enum import StrEnum


class ConversationStatus(StrEnum):
    OPEN = "open"
    ESCALATED = "escalated"
    CLOSED = "closed"


class MessageDirection(StrEnum):
    INBOUND = "inbound"
    OUTBOUND = "outbound"
    SYSTEM = "system"


class ChannelUpdateStatus(StrEnum):
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"


class ActiveWorkflow(StrEnum):
    AVAILABILITY = "availability"
    BOOKING_LOOKUP = "booking_lookup"
    ROOM_SERVICE = "room_service"
    MAINTENANCE = "maintenance"
    REQUEST_STATUS = "request_status"
