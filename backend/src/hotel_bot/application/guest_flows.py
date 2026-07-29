"""Session-aware Telegram guest flows over existing conversation, intent, and LLM services."""

import re
from collections.abc import Mapping
from datetime import date
from typing import Literal
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
from hotel_bot.domain.hotel.enums import ServiceRequestType
from hotel_bot.domain.hotel.policies import resolve_service_category
from hotel_bot.domain.intent.enums import (
    IntentCode,
    PredictionSource,
    RoutingDecision,
)
from hotel_bot.domain.intent.models import IntentPrediction, RoutingResult
from hotel_bot.domain.intent.normalization import normalize_text
from hotel_bot.domain.intent.taxonomy import INTENT_DEFINITIONS
from hotel_bot.domain.telegram.models import (
    TelegramGuestReply,
    TelegramInboundCallback,
    TelegramInboundMessage,
    TelegramInlineKeyboardButton,
    TelegramInlineKeyboardMarkup,
)

DATE_PATTERN = re.compile(r"\b20\d{2}-\d{2}-\d{2}\b")
BOOKING_PATTERN = re.compile(
    r"\bBKG-[A-Z0-9-]{4,28}\b",
    re.IGNORECASE,
)
TRACKING_PATTERN = re.compile(
    r"\bSR-[A-Z0-9-]{3,28}\b",
    re.IGNORECASE,
)
ROOM_PATTERN = re.compile(
    r"(?:room|الغرف(?:ة|ه))\s*[:#-]?\s*([A-Za-z0-9-]{1,16})",
    re.IGNORECASE,
)
LEADING_ROOM_PATTERN = re.compile(r"^\s*(\d{1,4})\b")
BARE_COUNT_PATTERN = re.compile(r"^\s*(\d{1,2})\s*$")
ADULTS_PATTERN = re.compile(
    (
        r"(?:(?:adults?|بالغ(?:ين)?)\s*[:=-]?\s*(\d{1,2})"
        r"|(\d{1,2})\s*(?:adults?|بالغ(?:ين)?|أشخاص|اشخاص|شخص))"
    ),
    re.IGNORECASE,
)
CHILDREN_PATTERN = re.compile(
    (
        r"(?:(?:children|child|kids|أطفال|اطفال|طفل)"
        r"\s*[:=-]?\s*(\d{1,2})"
        r"|(\d{1,2})\s*(?:children|child|kids|أطفال|اطفال|طفل))"
    ),
    re.IGNORECASE,
)
VERIFY_PATTERN = re.compile(
    (
        r"(?:verification(?:\s+code)?|verify|رمز\s+التحقق|كود\s+التحقق)"
        r"\s*[:=#-]?\s*([A-Za-z0-9_-]{4,128})"
    ),
    re.IGNORECASE,
)
GENERIC_ROOM_SERVICE_REQUESTS = frozenset(
    {
        "بدي خدمة الطعام الي الغرف",
        "بدي خدمة الطعام الي الغرفة",
        "اريد خدمة الطعام الي الغرف",
        "اريد خدمة الطعام الي الغرفة",
        "خدمة الطعام الي الغرف",
        "خدمة الطعام الي الغرفة",
        "i need room service",
        "room service",
    }
)


CONFIRMATIONS = frozenset(
    {
        "confirm",
        "confirmed",
        "yes",
        "yes confirm",
        "تأكيد",
        "اكد",
        "أكد",
        "اكده",
        "أكده",
        "اكدها",
        "أكدها",
        "نعم",
        "نعم اكد",
        "نعم أكد",
        "نعم اكده",
        "نعم أكده",
        "أكد الطلب",
        "اكد الطلب",
    }
)

CANCELLATIONS = frozenset(
    {
        "cancel",
        "no",
        "الغاء",
        "إلغاء",
        "الغيه",
        "ألغيه",
        "لا",
    }
)


CALLBACK_CONFIRM = "workflow:confirm"
CALLBACK_CANCEL = "workflow:cancel"

CallbackAction = Literal["confirm", "cancel"]


WORKFLOW_INTENT = {
    ActiveWorkflow.AVAILABILITY: IntentCode.ROOM_AVAILABILITY,
    ActiveWorkflow.BOOKING_LOOKUP: IntentCode.BOOKING_LOOKUP,
    ActiveWorkflow.ROOM_SERVICE: IntentCode.ROOM_SERVICE_REQUEST,
    ActiveWorkflow.MAINTENANCE: IntentCode.MAINTENANCE_REQUEST,
    ActiveWorkflow.REQUEST_STATUS: IntentCode.SERVICE_REQUEST_STATUS,
}

INTENT_WORKFLOW = {
    value: key
    for key, value in WORKFLOW_INTENT.items()
}

SERVICE_REQUEST_TYPE_BY_INTENT = {
    IntentCode.ROOM_SERVICE_REQUEST: ServiceRequestType.ROOM_SERVICE,
    IntentCode.MAINTENANCE_REQUEST: ServiceRequestType.MAINTENANCE,
}


def _confirmation_markup(
    language: SupportedLanguage,
) -> TelegramInlineKeyboardMarkup:
    """Build localized confirmation and cancellation buttons."""

    if language == "ar":
        confirm_text = "✅ تأكيد الطلب"
        cancel_text = "❌ إلغاء"
    else:
        confirm_text = "✅ Confirm request"
        cancel_text = "❌ Cancel"

    return TelegramInlineKeyboardMarkup(
        inline_keyboard=(
            (
                TelegramInlineKeyboardButton(
                    text=confirm_text,
                    callback_data=CALLBACK_CONFIRM,
                ),
                TelegramInlineKeyboardButton(
                    text=cancel_text,
                    callback_data=CALLBACK_CANCEL,
                ),
            ),
        ),
    )


def _confirmation_text(
    language: SupportedLanguage,
    workflow: ActiveWorkflow,
    parameters: Mapping[str, object],
) -> str:
    """Build a readable summary before executing a write operation."""

    room_number = str(
        parameters.get("room_number") or "-"
    )
    description = str(
        parameters.get("description") or "-"
    )

    if language == "ar":
        request_type = (
            "صيانة"
            if workflow == ActiveWorkflow.MAINTENANCE
            else "خدمة غرف"
        )

        return (
            "يرجى تأكيد إنشاء الطلب:\n\n"
            f"نوع الطلب: {request_type}\n"
            f"رقم الغرفة: {room_number}\n"
            f"التفاصيل: {description}"
        )

    request_type = (
        "Maintenance"
        if workflow == ActiveWorkflow.MAINTENANCE
        else "Room service"
    )

    return (
        "Please confirm creating this request:\n\n"
        f"Request type: {request_type}\n"
        f"Room number: {room_number}\n"
        f"Details: {description}"
    )


def _expired_callback_text(
    language: SupportedLanguage,
) -> str:
    """Return a safe response for stale or invalid buttons."""

    if language == "ar":
        return (
            "هذا الزر غير صالح أو انتهت صلاحيته. "
            "ابدأ الطلب من جديد."
        )

    return (
        "This button is invalid or has expired. "
        "Please start the request again."
    )


def _first(
    pattern: re.Pattern[str],
    text: str,
) -> str | None:
    match = pattern.search(text)

    if match is None:
        return None

    return next(
        (
            value
            for value in match.groups()
            if value is not None
        ),
        None,
    )


def _service_description(text: str) -> str | None:
    normalized = normalize_text(text)
    without_leading_room = re.sub(
        r"^\d{1,4}\s+",
        "",
        normalized,
    )
    if without_leading_room in GENERIC_ROOM_SERVICE_REQUESTS:
        return None
    return redact_sensitive_text(text)


def extract_parameters(
    text: str,
    state: ConversationState,
    *,
    idempotency_seed: str,
) -> dict[str, object]:
    """Extract trusted tool parameters from the guest message and state."""

    values: dict[str, object] = {}

    dates = DATE_PATTERN.findall(text)

    check_in = state.check_in
    check_out = state.check_out
    if len(dates) >= 2:
        check_in = check_in or date.fromisoformat(dates[0])
        check_out = check_out or date.fromisoformat(dates[1])
    elif dates:
        if check_in is None:
            check_in = date.fromisoformat(dates[0])
        elif check_out is None:
            check_out = date.fromisoformat(dates[0])

    if check_in is not None:
        values["check_in"] = check_in
    if check_out is not None:
        values["check_out"] = check_out

    adults = _first(
        ADULTS_PATTERN,
        text,
    )
    if adults is None and "شخصين" in normalize_text(text):
        adults = "2"
    if (
        adults is None
        and state.active_workflow is ActiveWorkflow.AVAILABILITY
        and check_in is not None
        and check_out is not None
        and state.adults is None
    ):
        adults = _first(
            BARE_COUNT_PATTERN,
            DATE_PATTERN.sub(" ", text),
        )
    children = _first(
        CHILDREN_PATTERN,
        text,
    )

    if adults or state.adults:
        values["adults"] = (
            int(adults)
            if adults
            else state.adults
        )

    values["children"] = (
        int(children)
        if children
        else (state.children or 0)
    )

    if state.room_type_code:
        values["room_type_code"] = state.room_type_code

    room_number = (
        _first(
            ROOM_PATTERN,
            text,
        )
    )
    if (
        room_number is None
        and state.active_workflow
        in {
            ActiveWorkflow.ROOM_SERVICE,
            ActiveWorkflow.MAINTENANCE,
        }
    ):
        room_number = _first(
            LEADING_ROOM_PATTERN,
            text,
        )
    room_number = room_number or state.room_number

    if room_number:
        values["room_number"] = room_number

    booking = BOOKING_PATTERN.search(text)

    verification = _first(
        VERIFY_PATTERN,
        text,
    )

    tracking = TRACKING_PATTERN.search(text)

    if booking:
        values["booking_reference"] = (
            booking.group(0).upper()
        )

    if verification:
        values["verification_value"] = verification

    if tracking:
        values["tracking_code"] = (
            tracking.group(0).upper()
        )

    normalized = text.casefold()

    if any(
        token in normalized
        for token in (
            "towel",
            "منشف",
            "blanket",
            "بطاني",
            "وساد",
        )
    ):
        category = "amenities"

    elif any(
        token in normalized
        for token in (
            "food",
            "meal",
            "dinner",
            "breakfast",
            "طعام",
            "أكل",
            "اكل",
            "وجبة",
            "غداء",
            "عشاء",
            "فطور",
            "مشروب",
        )
    ):
        category = "food_and_beverage"

    elif any(
        token in normalized
        for token in (
            "clean",
            "housekeeping",
            "تنظيف",
        )
    ):
        category = "housekeeping"

    elif any(
        token in normalized
        for token in (
            "electric",
            "power",
            "مقبس",
            "كهرب",
        )
    ):
        category = "electrical"

    elif any(
        token in normalized
        for token in (
            "water",
            "leak",
            "toilet",
            "مياه",
            "تسريب",
            "مرحاض",
        )
    ):
        category = "plumbing"

    else:
        category = state.service_category or "general"

    values["category"] = category

    description = _service_description(text)
    if description:
        values["description"] = description
    elif state.service_description:
        values["description"] = state.service_description

    values["urgency"] = (
        "emergency"
        if any(
            token in normalized
            for token in (
                "fire",
                "smoke",
                "danger",
                "حريق",
                "دخان",
                "خطر",
            )
        )
        else "high"
        if any(
            token in normalized
            for token in (
                "urgent",
                "عاجل",
            )
        )
        else "normal"
    )

    values["idempotency_key"] = (
        f"telegram-{idempotency_seed}"[:128]
    )

    return values


def redact_sensitive_text(
    text: str,
) -> str:
    """Redact references and verification values before LLM use."""

    redacted = BOOKING_PATTERN.sub(
        "[BOOKING_REFERENCE]",
        text,
    )

    redacted = TRACKING_PATTERN.sub(
        "[TRACKING_CODE]",
        redacted,
    )

    redacted = VERIFY_PATTERN.sub(
        "verification=[REDACTED]",
        redacted,
    )

    return redacted


def sanitize_context(
    context: ContextEnvelope,
) -> ContextEnvelope:
    """Remove sensitive operational values from LLM context."""

    current = context.current_message.model_copy(
        update={
            "text": redact_sensitive_text(
                context.current_message.text
            )
        }
    )

    turns = tuple(
        turn.model_copy(
            update={
                "inbound": turn.inbound.model_copy(
                    update={
                        "text": redact_sensitive_text(
                            turn.inbound.text
                        )
                    }
                )
            }
        )
        for turn in context.turns
    )

    state = context.state.model_copy(
        update={
            "room_number": None,
        }
    )

    return context.model_copy(
        update={
            "current_message": current,
            "turns": turns,
            "state": state,
        }
    )


def _forced_routing(
    intent: IntentCode,
    parameters: Mapping[str, object],
) -> RoutingResult:
    """Reconstruct deterministic routing for a confirmed workflow."""

    scores = {
        item: 0.0
        for item in IntentCode
    }

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
        if (
            parameters.get(name) is None
            or parameters.get(name) == ""
        )
    )

    return RoutingResult(
        prediction=prediction,
        decision=(
            RoutingDecision.CLARIFY
            if missing
            else RoutingDecision.ACTION_CANDIDATE
        ),
        missing_parameters=missing,
        requires_confirmation=(
            definition.state_changing
            and not missing
        ),
        reason_code="session_workflow",
    )


def _resolve_service_request_routing(
    routing: RoutingResult,
    parameters: dict[str, object],
) -> RoutingResult:
    """Resolve an allowed service category before confirmation or execution."""

    request_type = SERVICE_REQUEST_TYPE_BY_INTENT.get(routing.prediction.intent)
    if request_type is None:
        return routing

    missing = list(routing.missing_parameters)
    description = " ".join(
        str(parameters.get("description", "")).split()
    )
    if description:
        if len(description) < 10:
            parameters.pop("description", None)
            if "description" not in missing:
                missing.append("description")
        else:
            parameters["description"] = description[:1000]

    category = resolve_service_category(
        request_type,
        str(parameters.get("category", "")),
        str(parameters.get("description", "")),
    )
    if category is not None:
        parameters["category"] = category
    elif "category" not in missing:
        missing.append("category")

    required_order = INTENT_DEFINITIONS[
        routing.prediction.intent
    ].required_parameters
    resolved_missing = (
        *(
            name
            for name in required_order
            if name in missing
        ),
        *(
            name
            for name in missing
            if name not in required_order
        ),
    )
    if resolved_missing == routing.missing_parameters:
        return routing

    return routing.model_copy(
        update={
            "decision": RoutingDecision.CLARIFY,
            "missing_parameters": resolved_missing,
            "requires_confirmation": False,
            "allow_tool_execution": False,
            "reason_code": "missing_service_parameters",
        }
    )


def _state_with_parameters(
    state: ConversationState,
    intent: IntentCode,
    parameters: Mapping[str, object],
    *,
    active_workflow: ActiveWorkflow | None,
) -> ConversationState:
    """Persist only bounded, non-secret parameters for the active intent."""

    updates: dict[str, object] = {
        "active_workflow": active_workflow,
    }

    if intent is IntentCode.ROOM_AVAILABILITY:
        for name in (
            "check_in",
            "check_out",
            "adults",
            "children",
            "room_type_code",
        ):
            value = parameters.get(name)
            if value is not None and value != "":
                updates[name] = value

    if intent in {
        IntentCode.ROOM_SERVICE_REQUEST,
        IntentCode.MAINTENANCE_REQUEST,
    }:
        room_number = parameters.get("room_number")
        if room_number is not None and room_number != "":
            updates["room_number"] = str(room_number)

        category = parameters.get("category")
        if category not in {
            None,
            "",
            "general",
        }:
            updates["service_category"] = str(category)

        description = parameters.get("description")
        if description is not None and description != "":
            updates["service_description"] = str(description)[:1000]

    if intent is IntentCode.SERVICE_REQUEST_STATUS:
        tracking_code = parameters.get("tracking_code")
        if tracking_code is not None and tracking_code != "":
            updates["active_request_tracking_code"] = str(tracking_code)

    return state.model_copy(update=updates)


def _clear_completed_service_state(
    state: ConversationState,
) -> ConversationState:
    return state.model_copy(
        update={
            "active_workflow": None,
            "room_number": None,
            "service_category": None,
            "service_description": None,
        }
    )


def _recover_availability_state(
    state: ConversationState,
    reason_code: str,
) -> ConversationState:
    """Clear only invalid availability slots so the workflow can continue."""

    if reason_code in {
        "check_in_in_past",
        "check_in_too_far",
    }:
        return state.model_copy(
            update={
                "check_in": None,
                "check_out": None,
            }
        )
    if reason_code in {
        "invalid_date_range",
        "stay_too_long",
    }:
        return state.model_copy(
            update={
                "check_out": None,
            }
        )
    if reason_code == "adults_required":
        return state.model_copy(
            update={
                "adults": None,
            }
        )
    return state


def _command_reply(
    command: str,
    language: SupportedLanguage,
) -> str:
    if command in {
        "start",
        "help",
    }:
        return ConversationService.help_text(language)
    if command == "new":
        return (
            "بدأت محادثة جديدة. كيف يمكنني مساعدتك؟"
            if language == "ar"
            else "A new conversation has started. How may I help?"
        )
    if command == "language_ar":
        return "تم تغيير اللغة إلى العربية."
    return "Language changed to English."


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
        self,
        message: TelegramInboundMessage,
        *,
        correlation_id: str,
    ) -> TelegramGuestReply:
        """Process a regular Telegram text message."""

        return await self._process_message(
            message,
            correlation_id=correlation_id,
            callback_action=None,
        )

    async def process_callback(
        self,
        callback: TelegramInboundCallback,
        *,
        correlation_id: str,
    ) -> TelegramGuestReply:
        """Process an inline confirmation or cancellation button."""

        if callback.data == CALLBACK_CONFIRM:
            callback_action: CallbackAction = "confirm"

            action_text = (
                "تأكيد"
                if callback.language == "ar"
                else "confirm"
            )

        elif callback.data == CALLBACK_CANCEL:
            callback_action = "cancel"

            action_text = (
                "إلغاء"
                if callback.language == "ar"
                else "cancel"
            )

        else:
            return TelegramGuestReply(
                text=_expired_callback_text(
                    callback.language
                ),
                language=callback.language,
            )

        synthetic_message = TelegramInboundMessage(
            update_id=callback.update_id,
            chat_id=callback.chat_id,
            user_id=callback.user_id,
            message_id=callback.message_id,
            text=action_text,
            language=callback.language,
            command=None,
        )

        return await self._process_message(
            synthetic_message,
            correlation_id=correlation_id,
            callback_action=callback_action,
        )

    async def _process_message(
        self,
        message: TelegramInboundMessage,
        *,
        correlation_id: str,
        callback_action: CallbackAction | None,
    ) -> TelegramGuestReply:
        """Shared message pipeline for text messages and button callbacks."""

        identity_hash = telegram_identity_hash(
            message.user_id,
            self._identity_pepper,
        )

        language = await self._select_language(
            identity_hash,
            message,
        )

        inbound = await self._conversations.record_inbound(
            channel="telegram",
            external_update_id=message.update_id,
            guest_identity_hash=identity_hash,
            text=message.text,
            language=language,
            correlation_id=correlation_id,
            force_new_conversation=(
                message.command in {
                    "start",
                    "new",
                }
            ),
        )

        if inbound.duplicate:
            existing = (
                await self._conversations.record_outbound(
                    channel="telegram",
                    external_update_id=message.update_id,
                    text="duplicate",
                    language=inbound.conversation.language,
                    correlation_id=correlation_id,
                )
            )

            return TelegramGuestReply(
                text=existing.text,
                language=existing.language,
                duplicate=True,
            )

        language = inbound.conversation.language

        reply_markup: (
            TelegramInlineKeyboardMarkup | None
        ) = None

        if message.command in {
            "start",
            "help",
            "new",
            "language_ar",
            "language_en",
        }:
            reply_text = _command_reply(
                message.command,
                language,
            )

        else:
            (
                reply_text,
                reply_markup,
            ) = await self._respond_to_guest(
                message,
                inbound.conversation.state,
                inbound.conversation.id,
                inbound.message.id,
                callback_action=callback_action,
            )

        outbound = (
            await self._conversations.record_outbound(
                channel="telegram",
                external_update_id=message.update_id,
                text=reply_text,
                language=language,
                correlation_id=correlation_id,
            )
        )

        return TelegramGuestReply(
            text=outbound.text,
            language=outbound.language,
            reply_markup=reply_markup,
        )

    async def _select_language(
        self,
        identity_hash: str,
        message: TelegramInboundMessage,
    ) -> SupportedLanguage:
        if message.command == "language_ar":
            return "ar"

        if message.command == "language_en":
            return "en"

        return await self._conversations.preferred_language(
            identity_hash,
            message.language,
        )

    async def _respond_to_guest(
        self,
        message: TelegramInboundMessage,
        state: ConversationState,
        conversation_id: UUID,
        message_id: UUID,
        *,
        callback_action: CallbackAction | None,
    ) -> tuple[
        str,
        TelegramInlineKeyboardMarkup | None,
    ]:
        """Route, confirm, execute, and respond to one guest action."""

        normalized = " ".join(
            message.text.casefold().split()
        )

        cancellation_requested = (
            callback_action == "cancel"
            or normalized in CANCELLATIONS
        )

        if cancellation_requested:
            if state.active_workflow is None:
                if callback_action == "cancel":
                    return (
                        _expired_callback_text(
                            state.language
                        ),
                        None,
                    )

                return (
                    (
                        "لا توجد عملية معلّقة لإلغائها."
                        if state.language == "ar"
                        else (
                            "There is no pending operation "
                            "to cancel."
                        )
                    ),
                    None,
                )

            await self._conversations.update_state(
                conversation_id,
                _clear_completed_service_state(state),
            )

            return (
                (
                    "تم إلغاء العملية."
                    if state.language == "ar"
                    else "The operation was cancelled."
                ),
                None,
            )

        callback_confirm_requested = (
            callback_action == "confirm"
        )

        if (
            callback_confirm_requested
            and state.active_workflow
            not in {
                ActiveWorkflow.ROOM_SERVICE,
                ActiveWorkflow.MAINTENANCE,
            }
        ):
            return (
                _expired_callback_text(
                    state.language
                ),
                None,
            )

        context = (
            await self._conversations.assemble_context(
                conversation_id=conversation_id,
                current_message_id=message_id,
            )
        )

        confirmed = (
            (
                callback_confirm_requested
                or normalized in CONFIRMATIONS
            )
            and state.active_workflow
            in {
                ActiveWorkflow.ROOM_SERVICE,
                ActiveWorkflow.MAINTENANCE,
            }
        )

        source_text = message.text

        if confirmed and context.turns:
            source_text = (
                context.turns[-1].inbound.text
            )

        idempotency_source = (
            context.turns[-1].inbound.id
            if confirmed and context.turns
            else message_id
        )

        parameters = extract_parameters(
            source_text,
            state,
            idempotency_seed=str(
                idempotency_source
            ),
        )

        if (
            not confirmed
            and state.active_workflow
            in {
                ActiveWorkflow.BOOKING_LOOKUP,
                ActiveWorkflow.REQUEST_STATUS,
            }
            and context.turns
        ):
            previous = extract_parameters(
                context.turns[-1].inbound.text,
                ConversationState(
                    language=state.language,
                ),
                idempotency_seed=str(
                    context.turns[-1].inbound.id
                ),
            )
            for name, value in previous.items():
                if (
                    name not in parameters
                    or parameters[name] is None
                    or parameters[name] == ""
                ):
                    parameters[name] = value

        if state.active_workflow is not None:
            routing = _forced_routing(
                WORKFLOW_INTENT[
                    state.active_workflow
                ],
                parameters,
            )

        else:
            routing = (
                await self._intents.classify_message(
                    message_id,
                    parameters=parameters,
                )
            )

        routing = _resolve_service_request_routing(
            routing,
            parameters,
        )

        workflow = INTENT_WORKFLOW.get(
            routing.prediction.intent
        )

        active_workflow = state.active_workflow
        if (
            not confirmed
            and workflow is not None
            and routing.decision
            in {
                RoutingDecision.CLARIFY,
                RoutingDecision.ACTION_CANDIDATE,
            }
        ):
            active_workflow = workflow

        updated_state = _state_with_parameters(
            state,
            routing.prediction.intent,
            parameters,
            active_workflow=active_workflow,
        )
        if updated_state != state:
            await self._conversations.update_state(
                conversation_id,
                updated_state,
            )
        context = context.model_copy(
            update={
                "state": updated_state,
            }
        )

        result = await self._orchestrator.handle(
            sanitize_context(context),
            routing,
            confirmed=confirmed,
            trusted_tool_arguments=_tool_arguments(
                routing.prediction.intent,
                parameters,
            ),
        )

        if workflow is ActiveWorkflow.AVAILABILITY and not result.tool_executed:
            recovered_state = _recover_availability_state(
                updated_state,
                result.reason_code,
            )
            if recovered_state != updated_state:
                await self._conversations.update_state(
                    conversation_id,
                    recovered_state,
                )

        if result.tool_executed:
            completed_state = (
                _clear_completed_service_state(
                    updated_state
                )
                if workflow
                in {
                    ActiveWorkflow.ROOM_SERVICE,
                    ActiveWorkflow.MAINTENANCE,
                }
                else updated_state.model_copy(
                    update={
                        "active_workflow": None,
                    }
                )
            )
            await self._conversations.update_state(
                conversation_id,
                completed_state,
            )

        answer_text = result.answer.text

        reply_markup: (
            TelegramInlineKeyboardMarkup | None
        ) = None

        if (
            routing.requires_confirmation
            and workflow
            in {
                ActiveWorkflow.ROOM_SERVICE,
                ActiveWorkflow.MAINTENANCE,
            }
            and not confirmed
        ):
            answer_text = _confirmation_text(
                state.language,
                workflow,
                parameters,
            )

            reply_markup = _confirmation_markup(
                state.language
            )

        return (
            answer_text,
            reply_markup,
        )


def _tool_arguments(
    intent: IntentCode,
    values: Mapping[str, object],
) -> dict[str, object]:
    """Select only allow-listed tool arguments for the routed intent."""

    fields = {
        IntentCode.ROOM_TYPES: (),
        IntentCode.ROOM_AVAILABILITY: (
            "check_in",
            "check_out",
            "adults",
            "children",
            "room_type_code",
        ),
        IntentCode.BOOKING_LOOKUP: (
            "booking_reference",
            "verification_value",
        ),
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
        IntentCode.SERVICE_REQUEST_STATUS: (
            "tracking_code",
            "verification_value",
        ),
    }.get(
        intent,
        (),
    )

    selected = {
        name: values[name]
        for name in fields
        if name in values
    }

    request_type = SERVICE_REQUEST_TYPE_BY_INTENT.get(intent)
    if request_type is not None:
        category = resolve_service_category(
            request_type,
            str(selected.get("category", "")),
            str(selected.get("description", "")),
        )
        if category is None:
            selected.pop("category", None)
        else:
            selected["category"] = category

    return selected
