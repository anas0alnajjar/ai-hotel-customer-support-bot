"""Conversation context contracts independent from Gemini and MySQL."""

from datetime import datetime
from uuid import UUID

import pytest
from pydantic import ValidationError

from hotel_bot.domain.conversation.context import build_context, collect_complete_turns
from hotel_bot.domain.conversation.enums import MessageDirection
from hotel_bot.domain.conversation.models import ConversationState, MessageSnapshot

CONVERSATION_ID = UUID("10000000-0000-0000-0000-000000000001")
NOW = datetime(2026, 7, 13, 12, 0, 0)


def message(
    sequence: int,
    direction: MessageDirection,
    text: str,
    *,
    redacted_at: datetime | None = None,
) -> MessageSnapshot:
    return MessageSnapshot(
        id=UUID(f"20000000-0000-0000-0000-{sequence:012d}"),
        conversation_id=CONVERSATION_ID,
        sequence_number=sequence,
        direction=direction,
        text=text,
        language="ar",
        correlation_id=f"correlation-{sequence}",
        created_at=NOW,
        redacted_at=redacted_at,
    )


def test_context_keeps_only_latest_five_complete_turns_before_current_message() -> None:
    history: list[MessageSnapshot] = []
    for turn_number in range(1, 8):
        history.extend(
            [
                message(turn_number * 2 - 1, MessageDirection.INBOUND, f"question-{turn_number}"),
                message(turn_number * 2, MessageDirection.OUTBOUND, f"answer-{turn_number}"),
            ]
        )
    current = message(15, MessageDirection.INBOUND, "current-question")
    history.append(current)

    context = build_context(
        state=ConversationState(language="ar", room_type_code="DLX"),
        current_message=current,
        history=history,
        max_turns=5,
        max_tokens=3000,
    )

    assert [turn.inbound.text for turn in context.turns] == [
        "question-3",
        "question-4",
        "question-5",
        "question-6",
        "question-7",
    ]
    assert all(turn.inbound.id != current.id for turn in context.turns)
    assert context.state.room_type_code == "DLX"
    assert context.current_message.text == "current-question"
    assert context.truncated is True


def test_turn_collection_ignores_system_incomplete_and_redacted_messages() -> None:
    messages = (
        message(1, MessageDirection.INBOUND, "complete"),
        message(2, MessageDirection.SYSTEM, "internal"),
        message(3, MessageDirection.OUTBOUND, "reply"),
        message(4, MessageDirection.INBOUND, "redacted question", redacted_at=NOW),
        message(5, MessageDirection.OUTBOUND, "orphan response"),
        message(6, MessageDirection.INBOUND, "incomplete"),
    )

    turns = collect_complete_turns(messages, before_sequence=7)

    assert len(turns) == 1
    assert turns[0].inbound.text == "complete"
    assert turns[0].outbound.text == "reply"


def test_token_budget_preserves_state_and_current_message_then_drops_history() -> None:
    state = ConversationState(language="en", active_request_tracking_code="SR-1001")
    current = message(5, MessageDirection.INBOUND, "current " * 40)
    history = (
        message(1, MessageDirection.INBOUND, "old question " * 30),
        message(2, MessageDirection.OUTBOUND, "old answer " * 30),
        message(3, MessageDirection.INBOUND, "latest question " * 30),
        message(4, MessageDirection.OUTBOUND, "latest answer " * 30),
        current,
    )

    context = build_context(
        state=state,
        current_message=current,
        history=history,
        summary="summary " * 100,
        evidence=("evidence " * 100,),
        max_turns=5,
        max_tokens=160,
    )

    assert context.state.active_request_tracking_code == "SR-1001"
    assert context.current_message.id == current.id
    assert context.turns == ()
    assert context.summary is None
    assert context.evidence == ()
    assert context.truncated is True


def test_structured_state_rejects_unknown_or_unbounded_sensitive_fields() -> None:
    with pytest.raises(ValidationError):
        ConversationState.model_validate(
            {"language": "ar", "guest_verification_value": "plaintext-secret"}
        )
