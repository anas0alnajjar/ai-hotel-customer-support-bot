"""Deterministic, provider-neutral five-turn context assembly."""

from collections.abc import Iterable
from math import ceil

from hotel_bot.domain.conversation.enums import MessageDirection
from hotel_bot.domain.conversation.models import (
    ContextEnvelope,
    ConversationState,
    ConversationTurn,
    MessageSnapshot,
)


def estimate_tokens(text: str) -> int:
    """Conservative provider-neutral estimate suitable before a Gemini adapter exists."""

    return max(1, ceil(len(text.encode("utf-8")) / 3))


def collect_complete_turns(
    messages: Iterable[MessageSnapshot], *, before_sequence: int
) -> tuple[ConversationTurn, ...]:
    """Pair inbound/outbound messages and exclude incomplete or redacted history."""

    pending: MessageSnapshot | None = None
    completed: list[ConversationTurn] = []
    for message in sorted(messages, key=lambda item: item.sequence_number):
        if message.sequence_number >= before_sequence or message.redacted_at is not None:
            continue
        if message.direction is MessageDirection.INBOUND:
            pending = message
        elif message.direction is MessageDirection.OUTBOUND and pending is not None:
            completed.append(ConversationTurn(inbound=pending, outbound=message))
            pending = None
    return tuple(completed)


def _turn_tokens(turn: ConversationTurn) -> int:
    return estimate_tokens(turn.inbound.text) + estimate_tokens(turn.outbound.text) + 8


def _state_tokens(state: ConversationState) -> int:
    return estimate_tokens(state.model_dump_json(exclude_none=True)) + 8


def build_context(
    *,
    state: ConversationState,
    current_message: MessageSnapshot,
    history: Iterable[MessageSnapshot],
    summary: str | None = None,
    evidence: Iterable[str] = (),
    max_turns: int = 5,
    max_tokens: int = 3000,
) -> ContextEnvelope:
    """Keep mandatory state/current input, then bounded evidence, summary, and recent turns."""

    all_turns = collect_complete_turns(history, before_sequence=current_message.sequence_number)
    candidate_turns = all_turns[-max_turns:]
    used = _state_tokens(state) + estimate_tokens(current_message.text) + 8
    truncated = len(all_turns) > len(candidate_turns)

    selected_evidence: list[str] = []
    for item in evidence:
        item_tokens = estimate_tokens(item) + 4
        if used + item_tokens <= max_tokens:
            selected_evidence.append(item)
            used += item_tokens
        else:
            truncated = True

    selected_summary: str | None = None
    if summary:
        summary_tokens = estimate_tokens(summary) + 4
        if used + summary_tokens <= max_tokens:
            selected_summary = summary
            used += summary_tokens
        else:
            truncated = True

    selected_reversed: list[ConversationTurn] = []
    for turn in reversed(candidate_turns):
        turn_tokens = _turn_tokens(turn)
        if used + turn_tokens <= max_tokens:
            selected_reversed.append(turn)
            used += turn_tokens
        else:
            truncated = True
            break

    return ContextEnvelope(
        state=state,
        current_message=current_message,
        turns=tuple(reversed(selected_reversed)),
        evidence=tuple(selected_evidence),
        summary=selected_summary,
        estimated_tokens=used,
        truncated=truncated,
    )
