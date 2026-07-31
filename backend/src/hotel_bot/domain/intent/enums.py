"""Versioned intent taxonomy and safe routing outcomes."""

from enum import StrEnum


class IntentCode(StrEnum):
    HOTEL_INFO = "hotel_info"
    ROOM_TYPES = "room_types"
    ROOM_AVAILABILITY = "room_availability"
    BOOKING_LOOKUP = "booking_lookup"
    ROOM_SERVICE_REQUEST = "room_service_request"
    MAINTENANCE_REQUEST = "maintenance_request"
    SERVICE_REQUEST_STATUS = "service_request_status"
    HUMAN_ESCALATION = "human_escalation"
    GREETING_SMALLTALK = "greeting_smalltalk"
    UNSUPPORTED = "unsupported"


class DatasetSplit(StrEnum):
    TRAIN = "train"
    VALIDATION = "validation"
    TEST = "test"


class RoutingDecision(StrEnum):
    KNOWLEDGE_CANDIDATE = "knowledge_candidate"
    ACTION_CANDIDATE = "action_candidate"
    CLARIFY = "clarify"
    ESCALATE = "escalate"
    CONTROLLED_RESPONSE = "controlled_response"
    FALLBACK = "fallback"


class PredictionSource(StrEnum):
    RULE = "rule"
    CLASSIFIER = "classifier"
    HYBRID_LLM = "hybrid_llm"
