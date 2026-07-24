"""Authoritative intent taxonomy v1.0.0."""

from dataclasses import dataclass

from hotel_bot.domain.intent.enums import IntentCode

TAXONOMY_VERSION = "intent-taxonomy-v1.0.0"


@dataclass(frozen=True, slots=True)
class IntentDefinition:
    code: IntentCode
    expected_path: str
    required_parameters: tuple[str, ...] = ()
    state_changing: bool = False


INTENT_DEFINITIONS = {
    IntentCode.HOTEL_INFO: IntentDefinition(IntentCode.HOTEL_INFO, "rag"),
    IntentCode.ROOM_TYPES: IntentDefinition(IntentCode.ROOM_TYPES, "catalog"),
    IntentCode.ROOM_AVAILABILITY: IntentDefinition(
        IntentCode.ROOM_AVAILABILITY,
        "tool",
        ("check_in", "check_out", "adults"),
    ),
    IntentCode.BOOKING_LOOKUP: IntentDefinition(
        IntentCode.BOOKING_LOOKUP,
        "tool_with_verification",
        ("booking_reference", "verification_value"),
    ),
    IntentCode.ROOM_SERVICE_REQUEST: IntentDefinition(
        IntentCode.ROOM_SERVICE_REQUEST,
        "tool",
        ("room_number", "category", "description"),
        state_changing=True,
    ),
    IntentCode.MAINTENANCE_REQUEST: IntentDefinition(
        IntentCode.MAINTENANCE_REQUEST,
        "tool",
        ("room_number", "description"),
        state_changing=True,
    ),
    IntentCode.SERVICE_REQUEST_STATUS: IntentDefinition(
        IntentCode.SERVICE_REQUEST_STATUS,
        "tool_with_verification",
        ("tracking_code", "verification_value"),
    ),
    IntentCode.HUMAN_ESCALATION: IntentDefinition(IntentCode.HUMAN_ESCALATION, "escalation"),
    IntentCode.GREETING_SMALLTALK: IntentDefinition(
        IntentCode.GREETING_SMALLTALK, "controlled_response"
    ),
    IntentCode.UNSUPPORTED: IntentDefinition(IntentCode.UNSUPPORTED, "fallback"),
}

ACTION_INTENTS = frozenset(
    code
    for code, definition in INTENT_DEFINITIONS.items()
    if definition.expected_path.startswith("tool") or definition.expected_path == "catalog"
)
STATE_CHANGING_INTENTS = frozenset(
    code for code, definition in INTENT_DEFINITIONS.items() if definition.state_changing
)
