"""Deterministic guest-parameter extraction and prompt-redaction tests."""

from datetime import datetime
from uuid import uuid4

from hotel_bot.application.guest_flows import (
    _resolve_service_request_routing,
    _tool_arguments,
    extract_parameters,
    redact_sensitive_text,
    sanitize_context,
)
from hotel_bot.domain.conversation.enums import MessageDirection
from hotel_bot.domain.conversation.models import (
    ContextEnvelope,
    ConversationState,
    MessageSnapshot,
)
from hotel_bot.domain.intent.enums import (
    IntentCode,
    PredictionSource,
    RoutingDecision,
)
from hotel_bot.domain.intent.models import IntentPrediction, RoutingResult


def test_extracts_natural_bilingual_tool_parameters_and_stable_idempotency() -> None:
    availability = extract_parameters(
        "Need a room from 2026-08-10 to 2026-08-12 for 2 adults and 1 child",
        ConversationState(language="en"),
        idempotency_seed="update-1001",
    )
    booking = extract_parameters(
        "تحقق من BKG-2026-0001 رمز التحقق: 0101",
        ConversationState(language="ar"),
        idempotency_seed="update-1002",
    )

    assert str(availability["check_in"]) == "2026-08-10"
    assert str(availability["check_out"]) == "2026-08-12"
    assert availability["adults"] == 2
    assert availability["children"] == 1
    assert booking["booking_reference"] == "BKG-2026-0001"
    assert booking["verification_value"] == "0101"
    assert booking["idempotency_key"] == "telegram-update-1002"


def test_sensitive_booking_and_verification_values_never_enter_llm_context() -> None:
    message = MessageSnapshot(
        id=uuid4(),
        conversation_id=uuid4(),
        sequence_number=1,
        direction=MessageDirection.INBOUND,
        text="Lookup BKG-2026-0001 verification code: 0101",
        language="en",
        correlation_id="guest-flow-redaction",
        created_at=datetime(2026, 7, 21, 12, 0, 0),
    )
    context = ContextEnvelope(
        state=ConversationState(language="en", room_number="101"),
        current_message=message,
        turns=(),
        evidence=(),
        summary=None,
        estimated_tokens=50,
        truncated=False,
    )

    sanitized = sanitize_context(context)

    assert "BKG-2026-0001" not in sanitized.current_message.text
    assert "0101" not in sanitized.current_message.text
    assert "[REDACTED]" in sanitized.current_message.text
    assert sanitized.state.room_number is None
    assert "BKG-2026-0001" not in redact_sensitive_text(message.text)


def test_ac_maintenance_arguments_resolve_general_to_hvac() -> None:
    text = "المكيف في الغرفة 304 لا يعمل، أريد فتح طلب صيانة."
    parameters = extract_parameters(
        text,
        ConversationState(language="ar"),
        idempotency_seed="maintenance-ac-1003",
    )

    arguments = _tool_arguments(
        IntentCode.MAINTENANCE_REQUEST,
        parameters,
    )

    assert arguments["room_number"] == "304"
    assert arguments["category"] == "hvac"
    assert arguments["description"] == text


def test_unknown_maintenance_category_requires_clarification_before_confirmation() -> None:
    prediction = IntentPrediction(
        intent=IntentCode.MAINTENANCE_REQUEST,
        confidence=0.99,
        margin=0.80,
        classifier_version="test-v1",
        scores={IntentCode.MAINTENANCE_REQUEST: 0.99},
        source=PredictionSource.CLASSIFIER,
    )
    routing = RoutingResult(
        prediction=prediction,
        decision=RoutingDecision.ACTION_CANDIDATE,
        requires_confirmation=True,
        reason_code="test_action",
    )
    parameters: dict[str, object] = {
        "room_number": "304",
        "category": "general",
        "description": "يوجد شيء لا يعمل بالشكل الصحيح في الغرفة.",
    }

    resolved = _resolve_service_request_routing(
        routing,
        parameters,
    )

    assert resolved.decision is RoutingDecision.CLARIFY
    assert resolved.missing_parameters == ("category",)
    assert resolved.requires_confirmation is False
    assert parameters["category"] == "general"
