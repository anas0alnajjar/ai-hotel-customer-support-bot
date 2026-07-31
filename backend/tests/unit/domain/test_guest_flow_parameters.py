"""Deterministic guest-parameter extraction and prompt-redaction tests."""

from datetime import date, datetime
from uuid import uuid4

from hotel_bot.application.guest_flows import (
    _command_reply,
    _forced_routing,
    _recover_availability_state,
    _resolve_service_request_routing,
    _state_with_parameters,
    _tool_arguments,
    extract_parameters,
    redact_sensitive_text,
    sanitize_context,
)
from hotel_bot.application.hotel_tools import RoomServiceRequestInput
from hotel_bot.domain.conversation.enums import (
    ActiveWorkflow,
    MessageDirection,
)
from hotel_bot.domain.conversation.models import (
    ContextEnvelope,
    ConversationState,
    ConversationTurn,
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


def test_bare_booking_verification_is_current_workflow_only_and_redacted() -> None:
    booking_state = ConversationState(
        language="ar",
        active_workflow=ActiveWorkflow.BOOKING_LOOKUP,
    )

    parameters = extract_parameters(
        "0101",
        booking_state,
        idempotency_seed="booking-verification",
    )
    unrelated = extract_parameters(
        "0101",
        ConversationState(language="ar"),
        idempotency_seed="unrelated-number",
    )
    message = MessageSnapshot(
        id=uuid4(),
        conversation_id=uuid4(),
        sequence_number=1,
        direction=MessageDirection.INBOUND,
        text="0101",
        language="ar",
        correlation_id="bare-verification-redaction",
        created_at=datetime(2026, 7, 30, 12, 0, 0),
    )
    context = ContextEnvelope(
        state=booking_state,
        current_message=message,
        turns=(),
        evidence=(),
        summary=None,
        estimated_tokens=1,
        truncated=False,
    )

    sanitized = sanitize_context(
        context,
        verification_value="0101",
    )

    assert parameters["verification_value"] == "0101"
    assert "verification_value" not in unrelated
    assert "0101" not in sanitized.current_message.text
    assert sanitized.current_message.text == "[VERIFICATION_REDACTED]"


def test_verification_value_is_removed_from_summary_and_complete_turns() -> None:
    secret = "Verify-Secret-9281"
    conversation_id = uuid4()
    current = MessageSnapshot(
        id=uuid4(),
        conversation_id=conversation_id,
        sequence_number=3,
        direction=MessageDirection.INBOUND,
        text=f"verification code: {secret}",
        language="en",
        correlation_id="summary-redaction",
        created_at=datetime(2026, 7, 30, 12, 2, 0),
    )
    inbound = current.model_copy(
        update={
            "id": uuid4(),
            "sequence_number": 1,
            "text": f"previous verification code: {secret}",
        }
    )
    outbound = current.model_copy(
        update={
            "id": uuid4(),
            "sequence_number": 2,
            "direction": MessageDirection.OUTBOUND,
            "text": f"Never echo {secret}",
        }
    )
    context = ContextEnvelope(
        state=ConversationState(language="en"),
        current_message=current,
        turns=(ConversationTurn(inbound=inbound, outbound=outbound),),
        evidence=(),
        summary=f"Guest provided {secret}.",
        estimated_tokens=30,
        truncated=False,
    )

    sanitized = sanitize_context(context, verification_value=secret)
    serialized = sanitized.model_dump_json()

    assert secret not in serialized
    assert sanitized.summary is not None
    assert "[REDACTED]" in sanitized.summary


def test_room_service_extracts_natural_room_phrase_and_short_followups() -> None:
    one_message = extract_parameters(
        "أريد وجبة فطور لغرفتي 101",
        ConversationState(language="ar"),
        idempotency_seed="room-service-natural",
    )
    room_service_state = ConversationState(
        language="ar",
        room_number="101",
        active_workflow=ActiveWorkflow.ROOM_SERVICE,
    )

    assert one_message["room_number"] == "101"
    assert one_message["category"] == "food_and_beverage"
    assert one_message["description"] == "أريد وجبة فطور لغرفتي"

    for reply in (
        "food",
        "breakfast",
        "lunch",
        "dinner",
        "drinks",
        "water",
        "coffee",
        "wine",
        "طعام",
        "أكل",
        "فطور",
        "غداء",
        "عشاء",
        "مشروبات",
        "ماء",
        "قهوة",
    ):
        parameters = extract_parameters(
            reply,
            room_service_state,
            idempotency_seed=f"short-{reply}",
        )
        assert parameters["category"] == "food_and_beverage"
        assert len(str(parameters["description"])) >= 10


def test_bare_room_number_does_not_become_service_description() -> None:
    parameters = extract_parameters(
        "101",
        ConversationState(
            language="ar",
            active_workflow=ActiveWorkflow.ROOM_SERVICE,
        ),
        idempotency_seed="room-only",
    )

    assert parameters["room_number"] == "101"
    assert "description" not in parameters


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


def test_multiturn_availability_merges_dates_with_arabic_adult_count() -> None:
    state = ConversationState(
        language="ar",
        active_workflow=ActiveWorkflow.AVAILABILITY,
    )
    check_in = extract_parameters(
        "2026-01-01",
        state,
        idempotency_seed="availability-check-in",
    )
    state = _state_with_parameters(
        state,
        IntentCode.ROOM_AVAILABILITY,
        check_in,
        active_workflow=ActiveWorkflow.AVAILABILITY,
    )

    check_out = extract_parameters(
        "2026-01-10",
        state,
        idempotency_seed="availability-check-out",
    )
    state = _state_with_parameters(
        state,
        IntentCode.ROOM_AVAILABILITY,
        check_out,
        active_workflow=ActiveWorkflow.AVAILABILITY,
    )

    adults = extract_parameters(
        "14",
        state,
        idempotency_seed="availability-adults",
    )

    assert str(check_in["check_in"]) == "2026-01-01"
    assert "check_out" not in check_in
    assert str(check_out["check_in"]) == "2026-01-01"
    assert str(check_out["check_out"]) == "2026-01-10"
    assert adults["adults"] == 14


def test_multivalue_availability_extracts_dates_and_bare_adults_together() -> None:
    parameters = extract_parameters(
        "2026-01-01\n2026-01-10\n14",
        ConversationState(
            language="ar",
            active_workflow=ActiveWorkflow.AVAILABILITY,
        ),
        idempotency_seed="availability-multiple-values",
    )

    assert str(parameters["check_in"]) == "2026-01-01"
    assert str(parameters["check_out"]) == "2026-01-10"
    assert parameters["adults"] == 14


def test_past_arrival_recovery_clears_dates_but_preserves_collected_occupancy() -> None:
    state = ConversationState(
        language="ar",
        check_in=date(2020, 1, 1),
        check_out=date(2020, 1, 3),
        adults=2,
        children=0,
        active_workflow=ActiveWorkflow.AVAILABILITY,
    )

    recovered = _recover_availability_state(state, "check_in_in_past")

    assert recovered.check_in is None
    assert recovered.check_out is None
    assert recovered.adults == 2
    assert recovered.children == 0
    assert recovered.active_workflow is ActiveWorkflow.AVAILABILITY


def test_room_service_followup_builds_valid_confirmable_arguments() -> None:
    first = extract_parameters(
        "بدي خدمة الطعام إلى الغرفة",
        ConversationState(language="ar"),
        idempotency_seed="room-service-start",
    )
    state = _state_with_parameters(
        ConversationState(language="ar"),
        IntentCode.ROOM_SERVICE_REQUEST,
        first,
        active_workflow=ActiveWorkflow.ROOM_SERVICE,
    )

    second = extract_parameters(
        "10 اريد طعام لغرفتي",
        state,
        idempotency_seed="room-service-followup",
    )
    routing = _resolve_service_request_routing(
        _forced_routing(
            IntentCode.ROOM_SERVICE_REQUEST,
            second,
        ),
        second,
    )

    arguments = _tool_arguments(
        IntentCode.ROOM_SERVICE_REQUEST,
        second,
    )

    assert second["room_number"] == "10"
    assert second["category"] == "food_and_beverage"
    assert second["description"] == "10 اريد طعام لغرفتي"
    assert routing.missing_parameters == ()
    assert routing.requires_confirmation is True
    assert RoomServiceRequestInput.model_validate(arguments)


def test_room_service_missing_slots_keep_workflow_order() -> None:
    parameters: dict[str, object] = {
        "category": "general",
    }
    routing = _resolve_service_request_routing(
        _forced_routing(
            IntentCode.ROOM_SERVICE_REQUEST,
            parameters,
        ),
        parameters,
    )

    assert routing.missing_parameters == (
        "room_number",
        "category",
        "description",
    )


def test_language_commands_acknowledge_without_replaying_onboarding() -> None:
    arabic = _command_reply("language_ar", "ar")
    english = _command_reply("language_en", "en")

    assert arabic == "تم تغيير اللغة إلى العربية."
    assert english == "Language changed to English."
    assert "مساعد فندق" not in arabic
    assert "virtual assistant" not in english


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
