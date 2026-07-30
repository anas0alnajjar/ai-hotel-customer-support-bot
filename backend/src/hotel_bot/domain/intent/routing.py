"""Safety-first hybrid routing policy; it never executes tools."""

from collections.abc import Mapping
from typing import Protocol

from hotel_bot.domain.intent.enums import (
    IntentCode,
    PredictionSource,
    RoutingDecision,
)
from hotel_bot.domain.intent.models import (
    IntentPrediction,
    RoutingResult,
    SupportedLanguage,
)
from hotel_bot.domain.intent.normalization import normalize_text
from hotel_bot.domain.intent.taxonomy import (
    ACTION_INTENTS,
    INTENT_DEFINITIONS,
    STATE_CHANGING_INTENTS,
)

RULES_VERSION = "intent-rules-v1.1.0"
HUMAN_PATTERNS = (
    "موظف",
    "الاستقبال",
    "شخص حقيقي",
    "مدير",
    "human agent",
    "real person",
    "reception",
    "manager",
)
EMERGENCY_PATTERNS = (
    "حريق",
    "دخان",
    "تماس كهربائي",
    "خطر",
    "fire",
    "smoke",
    "electric shock",
    "danger",
    "emergency",
)
GREETING_ONLY = frozenset(
    {
        "مرحبا",
        "اهلا",
        "السلام عليكم",
        "صباح الخير",
        "مساء الخير",
        "hello",
        "hi",
        "good morning",
        "good evening",
    }
)
AVAILABILITY_QUESTIONS = frozenset(
    {
        "في حجوزات",
        "هل في حجوزات",
        "في غرف فاضية",
        "هل في غرف فاضية",
        "في غرف متاحة",
        "هل في غرف متاحة",
        "هل توجد غرف متاحة",
        "بدي احجز غرفة",
        "اريد احجز غرفة",
        "any availability",
        "any rooms available",
        "are there rooms available",
        "do you have rooms available",
        "i want to book a room",
    }
)
BOOKING_LOOKUP_QUESTIONS = frozenset(
    {
        "بدي تابع حجزي",
        "اريد متابعة حجزي",
        "check my existing reservation",
        "track my existing booking",
    }
)
ROOM_SERVICE_QUESTIONS = frozenset(
    {
        "خدمة الطعام الي الغرف",
        "خدمة الطعام الي الغرفة",
        "بدي خدمة الطعام الي الغرف",
        "بدي خدمة الطعام الي الغرفة",
        "اريد خدمة الطعام الي الغرف",
        "اريد خدمة الطعام الي الغرفة",
        "خدمة الغرف",
        "خدمة الغرفة",
        "i need room service",
    }
)
ACTION_REQUEST_MARKERS = (
    "اريد",
    "بدي",
    "احتاج",
    "ابحث",
    "اعرض",
    "ارسل",
    "احضر",
    "اطلب",
    "i want",
    "i need",
    "find",
    "search",
    "show",
    "send",
    "bring",
    "order",
    "deliver",
)
INFORMATION_REQUEST_MARKERS = (
    "هل",
    "ما ",
    "ماذا",
    "سياسة",
    "شروط",
    "متطلبات",
    "معلومات",
    "معرفة",
    "what ",
    "does ",
    "is ",
    "policy",
    "requirements",
    "information",
)
ROOM_TERMS = ("غرفة", "غرف", "room", "rooms")
AVAILABILITY_TERMS = (
    "متاح",
    "متاحة",
    "فاضية",
    "شاغر",
    "شاغرة",
    "التوفر",
    "available",
    "availability",
    "vacant",
)
STAY_TIME_TERMS = (
    "الليلة",
    "اليوم",
    "غدا",
    "الاسبوع القادم",
    "الشهر القادم",
    "tonight",
    "tomorrow",
    "next weekend",
    "next week",
    "next month",
)
BOOKING_LOOKUP_TERMS = (
    "تابع حجزي",
    "متابعة حجزي",
    "تحقق من حجزي",
    "حجزي الحالي",
    "existing booking",
    "existing reservation",
    "my booking",
    "my reservation",
)
ROOM_SERVICE_ACTION_TERMS = (
    "خدمة الغرف",
    "خدمة الغرفة",
    "للغرفة",
    "الي الغرفة",
    "room service",
    "to my room",
)
MAINTENANCE_PROBLEM_TERMS = (
    "عطل",
    "عطلان",
    "مكسور",
    "مكسورة",
    "لا يعمل",
    "لا تعمل",
    "تسريب",
    "انسداد",
    "broken",
    "not working",
    "leak",
    "clogged",
)
SERVICE_STATUS_TERMS = (
    "حالة طلبي",
    "تابع طلبي",
    "متابعة طلبي",
    "طلب الخدمة",
    "service request status",
    "track my request",
)
ROOM_TYPE_ACTION_TERMS = (
    "اعرض انواع الغرف",
    "ما انواع الغرف",
    "ما هي انواع الغرف",
    "خيارات الغرف",
    "show room types",
    "what room types",
    "room categories",
)


class IntentPredictor(Protocol):
    def predict(self, text: str, language: SupportedLanguage) -> IntentPrediction: ...


def _rule_prediction(intent: IntentCode) -> IntentPrediction:
    scores = {item: 0.0 for item in IntentCode}
    scores[intent] = 1.0
    return IntentPrediction(
        intent=intent,
        confidence=1.0,
        margin=1.0,
        classifier_version=RULES_VERSION,
        scores=scores,
        source=PredictionSource.RULE,
    )


def _contains_any(text: str, patterns: tuple[str, ...]) -> bool:
    return any(pattern in text for pattern in patterns)


def _is_substantive_question(text: str, normalized: str) -> bool:
    return "?" in text or "؟" in text or len(normalized.split()) >= 4


def _is_explicit_action(
    intent: IntentCode,
    normalized: str,
    parameters: Mapping[str, object],
) -> bool:
    if intent is IntentCode.ROOM_AVAILABILITY:
        has_dates = bool(parameters.get("check_in") or parameters.get("check_out"))
        asks_for_room = _contains_any(normalized, ACTION_REQUEST_MARKERS) and _contains_any(
            normalized, ROOM_TERMS
        )
        asks_availability = _contains_any(
            normalized, AVAILABILITY_TERMS
        ) and _contains_any(normalized, ROOM_TERMS)
        timed_availability = asks_availability and _contains_any(
            normalized, STAY_TIME_TERMS
        )
        return (
            normalized in AVAILABILITY_QUESTIONS
            or has_dates
            or asks_for_room
            or timed_availability
            or (asks_availability and len(normalized.split()) <= 4)
        )
    if intent is IntentCode.BOOKING_LOOKUP:
        return bool(parameters.get("booking_reference")) or (
            normalized in BOOKING_LOOKUP_QUESTIONS
            or _contains_any(normalized, BOOKING_LOOKUP_TERMS)
        )
    if intent is IntentCode.ROOM_SERVICE_REQUEST:
        has_room = bool(parameters.get("room_number"))
        requests_action = _contains_any(
            normalized, ACTION_REQUEST_MARKERS
        ) and not _contains_any(normalized, INFORMATION_REQUEST_MARKERS)
        return normalized in ROOM_SERVICE_QUESTIONS or requests_action or (
            _contains_any(normalized, ROOM_SERVICE_ACTION_TERMS) and has_room
        )
    if intent is IntentCode.MAINTENANCE_REQUEST:
        return _contains_any(normalized, MAINTENANCE_PROBLEM_TERMS)
    if intent is IntentCode.SERVICE_REQUEST_STATUS:
        return bool(parameters.get("tracking_code")) or _contains_any(
            normalized, SERVICE_STATUS_TERMS
        )
    if intent is IntentCode.ROOM_TYPES:
        return _contains_any(normalized, ROOM_TYPE_ACTION_TERMS)
    return False


class SafeIntentRouter:
    def __init__(
        self,
        classifier: IntentPredictor,
        *,
        general_confidence_threshold: float = 0.60,
        action_confidence_threshold: float = 0.80,
        confidence_margin_threshold: float = 0.15,
    ) -> None:
        self._classifier = classifier
        self._general_threshold = general_confidence_threshold
        self._action_threshold = action_confidence_threshold
        self._margin_threshold = confidence_margin_threshold

    def route(
        self,
        text: str,
        language: SupportedLanguage,
        *,
        parameters: Mapping[str, object] | None = None,
    ) -> RoutingResult:
        normalized = normalize_text(text)
        if any(pattern in normalized for pattern in HUMAN_PATTERNS + EMERGENCY_PATTERNS):
            prediction = _rule_prediction(IntentCode.HUMAN_ESCALATION)
            return RoutingResult(
                prediction=prediction,
                decision=RoutingDecision.ESCALATE,
                reason_code="explicit_human_or_safety_escalation",
            )
        if normalized in GREETING_ONLY:
            prediction = _rule_prediction(IntentCode.GREETING_SMALLTALK)
            return RoutingResult(
                prediction=prediction,
                decision=RoutingDecision.CONTROLLED_RESPONSE,
                reason_code="deterministic_greeting",
            )

        alias_intent = (
            IntentCode.ROOM_AVAILABILITY
            if normalized in AVAILABILITY_QUESTIONS
            else IntentCode.BOOKING_LOOKUP
            if normalized in BOOKING_LOOKUP_QUESTIONS
            else IntentCode.ROOM_SERVICE_REQUEST
            if normalized in ROOM_SERVICE_QUESTIONS
            else None
        )
        prediction = (
            _rule_prediction(alias_intent)
            if alias_intent is not None
            else self._classifier.predict(text, language)
        )
        values = parameters or {}
        substantive_question = _is_substantive_question(text, normalized)

        if prediction.intent in ACTION_INTENTS and not _is_explicit_action(
            prediction.intent,
            normalized,
            values,
        ):
            knowledge_prediction = _rule_prediction(IntentCode.HOTEL_INFO)
            return RoutingResult(
                prediction=knowledge_prediction,
                decision=(
                    RoutingDecision.KNOWLEDGE_CANDIDATE
                    if substantive_question
                    else RoutingDecision.CLARIFY
                ),
                reason_code=(
                    "informational_or_ambiguous_knowledge_candidate"
                    if substantive_question
                    else "operational_noun_without_explicit_action"
                ),
            )
        if prediction.intent is IntentCode.HUMAN_ESCALATION:
            if substantive_question:
                return RoutingResult(
                    prediction=_rule_prediction(IntentCode.HOTEL_INFO),
                    decision=RoutingDecision.KNOWLEDGE_CANDIDATE,
                    reason_code="informational_or_ambiguous_knowledge_candidate",
                )
            return RoutingResult(
                prediction=prediction,
                decision=RoutingDecision.ESCALATE,
                reason_code="classified_human_escalation",
            )
        if prediction.intent is IntentCode.UNSUPPORTED:
            if substantive_question:
                return RoutingResult(
                    prediction=_rule_prediction(IntentCode.HOTEL_INFO),
                    decision=RoutingDecision.KNOWLEDGE_CANDIDATE,
                    reason_code="informational_or_ambiguous_knowledge_candidate",
                )
            return RoutingResult(
                prediction=prediction,
                decision=RoutingDecision.FALLBACK,
                reason_code="unsupported_request",
            )
        if prediction.intent is IntentCode.GREETING_SMALLTALK:
            if substantive_question:
                return RoutingResult(
                    prediction=_rule_prediction(IntentCode.HOTEL_INFO),
                    decision=RoutingDecision.KNOWLEDGE_CANDIDATE,
                    reason_code="informational_or_ambiguous_knowledge_candidate",
                )
            return RoutingResult(
                prediction=prediction,
                decision=RoutingDecision.CONTROLLED_RESPONSE,
                reason_code="classified_greeting",
            )

        definition = INTENT_DEFINITIONS[prediction.intent]
        missing = tuple(
            name
            for name in definition.required_parameters
            if values.get(name) is None or values.get(name) == ""
        )
        threshold = (
            self._action_threshold
            if prediction.intent in ACTION_INTENTS
            else self._general_threshold
        )
        if (
            prediction.intent is not IntentCode.HOTEL_INFO
            and (
                prediction.confidence < threshold
                or prediction.margin < self._margin_threshold
            )
        ):
            return RoutingResult(
                prediction=prediction,
                decision=RoutingDecision.CLARIFY,
                missing_parameters=missing,
                reason_code="low_confidence_or_margin",
            )

        if prediction.intent is IntentCode.HOTEL_INFO:
            return RoutingResult(
                prediction=prediction,
                decision=RoutingDecision.KNOWLEDGE_CANDIDATE,
                reason_code=(
                    "informational_or_ambiguous_knowledge_candidate"
                    if substantive_question
                    else "classified_knowledge_candidate"
                ),
            )

        if missing:
            return RoutingResult(
                prediction=prediction,
                decision=RoutingDecision.CLARIFY,
                missing_parameters=missing,
                reason_code="missing_required_parameters",
            )
        return RoutingResult(
            prediction=prediction,
            decision=RoutingDecision.ACTION_CANDIDATE,
            requires_confirmation=prediction.intent in STATE_CHANGING_INTENTS,
            allow_tool_execution=False,
            reason_code="requires_orchestrator_validation",
        )
