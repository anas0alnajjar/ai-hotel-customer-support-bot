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

RULES_VERSION = "intent-rules-v1.0.0"
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
        "بدي خدمة الطعام الي الغرف",
        "بدي خدمة الطعام الي الغرفة",
        "اريد خدمة الطعام الي الغرف",
        "اريد خدمة الطعام الي الغرفة",
        "i need room service",
    }
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
        if prediction.intent is IntentCode.HUMAN_ESCALATION:
            return RoutingResult(
                prediction=prediction,
                decision=RoutingDecision.ESCALATE,
                reason_code="classified_human_escalation",
            )
        if prediction.intent is IntentCode.UNSUPPORTED:
            return RoutingResult(
                prediction=prediction,
                decision=RoutingDecision.FALLBACK,
                reason_code="unsupported_request",
            )
        if prediction.intent is IntentCode.GREETING_SMALLTALK:
            return RoutingResult(
                prediction=prediction,
                decision=RoutingDecision.CONTROLLED_RESPONSE,
                reason_code="classified_greeting",
            )

        definition = INTENT_DEFINITIONS[prediction.intent]
        values = parameters or {}
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
        if prediction.confidence < threshold or prediction.margin < self._margin_threshold:
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
                reason_code="high_confidence_knowledge_candidate",
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
