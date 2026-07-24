"""Deterministic guest-parameter extraction and prompt-redaction tests."""

from datetime import datetime
from uuid import uuid4

from hotel_bot.application.guest_flows import (
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
