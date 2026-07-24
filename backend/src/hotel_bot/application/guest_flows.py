"""Session-aware Telegram guest flows over existing conversation, intent, and LLM services."""

import re
from collections.abc import Mapping
from datetime import date
from uuid import UUID

from hotel_bot.application.conversations import ConversationService
from hotel_bot.application.intent_routing import IntentRoutingService
from hotel_bot.application.llm import HybridOrchestrator
from hotel_bot.application.telegram import telegram_identity_hash
from hotel_bot.domain.conversation.enums import ActiveWorkflow
from hotel_bot.domain.conversation.models import (
    ContextEnvelope,
    ConversationState,
    SupportedLanguage,
)
from hotel_bot.domain.intent.enums import IntentCode, PredictionSource, RoutingDecision
from hotel_bot.domain.intent.models import IntentPrediction, RoutingResult
from hotel_bot.domain.intent.taxonomy import INTENT_DEFINITIONS
from hotel_bot.domain.telegram.models import (
    TelegramGuestReply,
    TelegramInboundMessage,
)

DATE_PATTERN = re.compile(r"\b20\d{2}-\d{2}-\d{2}\b")
BOOKING_PATTERN = re.compile(r"\bBKG-[A-Z0-9-]{4,28}\b", re.IGNORECASE)
TRACKING_PATTERN = re.compile(r"\bSR-[A-Z0-9-]{3,28}\b", re.IGNORECASE)
ROOM_PATTERN = re.compile(r"(?:room|الغرف(?:ة|ه))\s*[:#-]?\s*([A-Za-z0-9-]{1,16})", re.IGNORECASE)
ADULTS_PATTERN = re.compile(
    r"(?:(?:adults?|بالغ(?:ين)?)\s*[:=-]?\s*(\d{1,2})|(\d{1,2})\s*(?:adults?|بالغ(?:ين)?))",
    re.IGNORECASE,
)
CHILDREN_PATTERN = re.compile(
    r"(?:(?:children|child|kids|أطفال|اطفال|طفل)\s*[:=-]?\s*(\d{1,2})|(\d{1,2})\s*(?:children|child|kids|أطفال|اطفال|طفل))",
    re.IGNORECASE,
)
VERIFY_PATTERN = re.compile(
    r"(?:verification(?:\s+code)?|verify|رمز\s+التحقق|كود\s+التحقق)\s*[:=#-]?\s*([A-Za-z0-9_-]{4,128})",
    re.IGNORECASE,
)
CONFIRMATIONS = frozenset(
    {"confirm", "confirmed", "yes confirm", "تأكيد", "اكد", "أكد", "نعم اكد", "نعم أكد"}
)
CANCELLATIONS = frozenset({"cancel", "no", "الغاء", "إلغاء", "لا"})

WORKFLOW_INTENT = {
    ActiveWorkflow.AVAILABILITY: IntentCode.ROOM_AVAILABILITY,
    ActiveWorkflow.BOOKING_LOOKUP: IntentCode.BOOKING_LOOKUP,
    ActiveWorkflow.ROOM_SERVICE: IntentCode.ROOM_SERVICE_REQUEST,
    ActiveWorkflow.MAINTENANCE: IntentCode.MAINTENANCE_REQUEST,
    ActiveWorkflow.REQUEST_STATUS: IntentCode.SERVICE_REQUEST_STATUS,
}
INTENT_WORKFLOW = {value: key for key, value in WORKFLOW_INTENT.items()}


def _first(pattern: re.Pattern[str], text: str) -> str | None:
    match = pattern.search(text)
    if match is None:
        return None
    return next((value for value in match.groups() if value is not None), None)


def extract_parameters(
    text: str,
    state: ConversationState,
    *,
    idempotency_seed: str,
) -> dict[str, object]:
    values: dict[str, object] = {}
    dates = DATE_PATTERN.findall(text)
    if dates or state.check_in:
        values["check_in"] = date.fromisoformat(dates[0]) if dates else state.check_in
    if len(dates) >= 2 or state.check_out:
        values["check_out"] = date.fromisoformat(dates[1]) if len(dates) >= 2 else state.check_out
    adults = _first(ADULTS_PATTERN, text)
    children = _first(CHILDREN_PATTERN, text)
    if adults or state.adults:
        values["adults"] = int(adults) if adults else state.adults
    values["children"] = int(children) if children else (state.children or 0)
    if state.room_type_code:
        values["room_type_code"] = state.room_type_code

    room_number = _first(ROOM_PATTERN, text) or state.room_number
    if room_number:
        values["room_number"] = room_number
    booking = BOOKING_PATTERN.search(text)
    verification = _first(VERIFY_PATTERN, text)
    tracking = TRACKING_PATTERN.search(text)
    if booking:
        values["booking_reference"] = booking.group(0).upper()
    if verification:
        values["verification_value"] = verification
    if tracking:
        values["tracking_code"] = tracking.group(0).upper()

    normalized = text.casefold()
    if any(token in normalized for token in ("towel", "منشف", "blanket", "بطاني", "وساد")):
        category = "amenities"
    elif any(
        token in normalized
        for token in ("food", "meal", "dinner", "breakfast", "وجبة", "عشاء", "فطور")
    ):
        category = "food"
    elif any(token in normalized for token in ("clean", "housekeeping", "تنظيف")):
        category = "housekeeping"
    elif any(token in normalized for token in ("electric", "power", "مقبس", "كهرب")):
        category = "electrical"
    elif any(
        token in normalized for token in ("water", "leak", "toilet", "مياه", "تسريب", "مرحاض")
    ):
        category = "plumbing"
    else:
        category = "general"
    values["category"] = category
    values["description"] = redact_sensitive_text(text)
    values["urgency"] = (
        "emergency"
        if any(token in normalized for token in ("fire", "smoke", "danger", "حريق", "دخان", "خطر"))
        else "high"
        if any(token in normalized for token in ("urgent", "عاجل"))
        else "normal"
    )
    values["idempotency_key"] = f"telegram-{idempotency_seed}"[:128]
    return values


def redact_sensitive_text(text: str) -> str:
    redacted = BOOKING_PATTERN.sub("[BOOKING_REFERENCE]", text)
    redacted = TRACKING_PATTERN.sub("[TRACKING_CODE]", redacted)
    redacted = VERIFY_PATTERN.sub("verification=[REDACTED]", redacted)
    return redacted


def sanitize_context(context: ContextEnvelope) -> ContextEnvelope:
    current = context.current_message.model_copy(
        update={"text": redact_sensitive_text(context.current_message.text)}
    )
    turns = tuple(
        turn.model_copy(
            update={
                "inbound": turn.inbound.model_copy(
                    update={"text": redact_sensitive_text(turn.inbound.text)}
                )
            }
        )
        for turn in context.turns
    )
    state = context.state.model_copy(update={"room_number": None})
    return context.model_copy(update={"current_message": current, "turns": turns, "state": state})


def _forced_routing(intent: IntentCode, parameters: Mapping[str, object]) -> RoutingResult:
    scores = {item: 0.0 for item in IntentCode}
    scores[intent] = 1.0
    prediction = IntentPrediction(
        intent=intent,
        confidence=1.0,
        margin=1.0,
        classifier_version="session-workflow-v1.0.0",
        scores=scores,
        source=PredictionSource.RULE,
    )
    definition = INTENT_DEFINITIONS[intent]
    missing = tuple(
        name
        for name in definition.required_parameters
        if parameters.get(name) is None or parameters.get(name) == ""
    )
    return RoutingResult(
        prediction=prediction,
        decision=RoutingDecision.CLARIFY if missing else RoutingDecision.ACTION_CANDIDATE,
        missing_parameters=missing,
        requires_confirmation=definition.state_changing and not missing,
        reason_code="session_workflow",
    )


class HotelGuestProcessor:
    def __init__(
        self,
        *,
        conversations: ConversationService,
        intents: IntentRoutingService,
        orchestrator: HybridOrchestrator,
        identity_pepper: str,
    ) -> None:
        self._conversations = conversations
        self._intents = intents
        self._orchestrator = orchestrator
        self._identity_pepper = identity_pepper

    async def process(
        self, message: TelegramInboundMessage, *, correlation_id: str
    ) -> TelegramGuestReply:
        identity_hash = telegram_identity_hash(message.user_id, self._identity_pepper)
        language = await self._select_language(identity_hash, message)
        inbound = await self._conversations.record_inbound(
            channel="telegram",
            external_update_id=message.update_id,
            guest_identity_hash=identity_hash,
            text=message.text,
            language=language,
            correlation_id=correlation_id,
            force_new_conversation=message.command in {"start", "new"},
        )
        if inbound.duplicate:
            existing = await self._conversations.record_outbound(
                channel="telegram",
                external_update_id=message.update_id,
                text="duplicate",
                language=inbound.conversation.language,
                correlation_id=correlation_id,
            )
            return TelegramGuestReply(
                text=existing.text,
                language=existing.language,
                duplicate=True,
            )

        language = inbound.conversation.language
        if message.command in {"start", "help", "new", "language_ar", "language_en"}:
            reply_text = ConversationService.help_text(language)
        else:
            reply_text = await self._respond_to_guest(
                message,
                inbound.conversation.state,
                inbound.conversation.id,
                inbound.message.id,
            )
        outbound = await self._conversations.record_outbound(
            channel="telegram",
            external_update_id=message.update_id,
            text=reply_text,
            language=language,
            correlation_id=correlation_id,
        )
        return TelegramGuestReply(text=outbound.text, language=outbound.language)

    async def _select_language(
        self, identity_hash: str, message: TelegramInboundMessage
    ) -> SupportedLanguage:
        if message.command == "language_ar":
            return "ar"
        if message.command == "language_en":
            return "en"
        return await self._conversations.preferred_language(identity_hash, message.language)

    async def _respond_to_guest(
        self,
        message: TelegramInboundMessage,
        state: ConversationState,
        conversation_id: UUID,
        message_id: UUID,
    ) -> str:
        normalized = " ".join(message.text.casefold().split())
        if normalized in CANCELLATIONS and state.active_workflow is not None:
            await self._conversations.update_state(
                conversation_id, state.model_copy(update={"active_workflow": None})
            )
            return "تم إلغاء العملية." if state.language == "ar" else "The operation was cancelled."

        context = await self._conversations.assemble_context(
            conversation_id=conversation_id,
            current_message_id=message_id,
        )
        confirmed = normalized in CONFIRMATIONS and state.active_workflow in {
            ActiveWorkflow.ROOM_SERVICE,
            ActiveWorkflow.MAINTENANCE,
        }
        source_text = message.text
        if confirmed and context.turns:
            source_text = context.turns[-1].inbound.text
        parameters = extract_parameters(
            source_text,
            state,
            idempotency_seed=str(
                context.turns[-1].inbound.id if confirmed and context.turns else message_id
            ),
        )
        if confirmed and state.active_workflow is not None:
            routing = _forced_routing(WORKFLOW_INTENT[state.active_workflow], parameters)
        else:
            routing = await self._intents.classify_message(message_id, parameters=parameters)

        workflow = INTENT_WORKFLOW.get(routing.prediction.intent)
        if routing.requires_confirmation and workflow is not None and not confirmed:
            await self._conversations.update_state(
                conversation_id,
                state.model_copy(update={"active_workflow": workflow}),
            )
        result = await self._orchestrator.handle(
            sanitize_context(context),
            routing,
            confirmed=confirmed,
            trusted_tool_arguments=_tool_arguments(routing.prediction.intent, parameters),
        )
        if confirmed and result.tool_executed:
            await self._conversations.update_state(
                conversation_id,
                state.model_copy(update={"active_workflow": None}),
            )
        return result.answer.text


def _tool_arguments(intent: IntentCode, values: Mapping[str, object]) -> dict[str, object]:
    fields = {
        IntentCode.ROOM_TYPES: (),
        IntentCode.ROOM_AVAILABILITY: (
            "check_in",
            "check_out",
            "adults",
            "children",
            "room_type_code",
        ),
        IntentCode.BOOKING_LOOKUP: ("booking_reference", "verification_value"),
        IntentCode.ROOM_SERVICE_REQUEST: (
            "category",
            "room_number",
            "description",
            "urgency",
            "idempotency_key",
            "booking_reference",
            "verification_value",
        ),
        IntentCode.MAINTENANCE_REQUEST: (
            "category",
            "room_number",
            "description",
            "urgency",
            "idempotency_key",
            "booking_reference",
            "verification_value",
        ),
        IntentCode.SERVICE_REQUEST_STATUS: ("tracking_code", "verification_value"),
    }.get(intent, ())
    return {name: values[name] for name in fields if name in values}
