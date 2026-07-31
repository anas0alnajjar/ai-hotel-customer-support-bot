"""Classify one persisted inbound message and store its versioned routing evidence."""

import logging
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

from pydantic import ValidationError

from hotel_bot.application.llm import AuditedLLMService, TurnBudget
from hotel_bot.application.prompts import PromptFactory
from hotel_bot.domain.conversation.models import ContextEnvelope
from hotel_bot.domain.intent.enums import (
    IntentCode,
    PredictionSource,
    RoutingDecision,
)
from hotel_bot.domain.intent.models import (
    IntentPrediction,
    RoutingResult,
    StoredClassification,
    SupportedLanguage,
)
from hotel_bot.domain.intent.routing import SafeIntentRouter
from hotel_bot.domain.intent.taxonomy import (
    INTENT_DEFINITIONS,
    STATE_CHANGING_INTENTS,
)
from hotel_bot.domain.llm.errors import LLMError
from hotel_bot.domain.llm.models import HybridIntentDecision

HYBRID_ROUTER_VERSION = "hybrid-intent-v1.0.0"
LOGGER = logging.getLogger(__name__)
HYBRID_GATE_REASONS = frozenset(
    {
        "informational_or_ambiguous_knowledge_candidate",
        "operational_noun_without_explicit_action",
        "low_confidence_or_margin",
    }
)
HYBRID_SAFE_PARAMETER_NAMES = frozenset(
    {
        "check_in",
        "check_out",
        "adults",
        "children",
        "room_type_code",
        "room_number",
        "category",
        "description",
    }
)


class IntentClassificationRepository(Protocol):
    async def get_inbound_message_text(
        self, message_id: UUID
    ) -> tuple[str, SupportedLanguage] | None: ...

    async def store_classification(
        self, message_id: UUID, result: RoutingResult
    ) -> StoredClassification: ...


class IntentRoutingService:
    def __init__(
        self,
        repository: IntentClassificationRepository,
        router: SafeIntentRouter,
    ) -> None:
        self._repository = repository
        self._router = router

    async def classify_message(
        self,
        message_id: UUID,
        *,
        parameters: Mapping[str, object] | None = None,
    ) -> RoutingResult:
        message = await self._repository.get_inbound_message_text(message_id)
        if message is None:
            raise ValueError("inbound message was not found")
        text, language = message
        result = self._router.route(text, language, parameters=parameters)
        await self._repository.store_classification(message_id, result)
        return result

    async def store_result(
        self,
        message_id: UUID,
        result: RoutingResult,
    ) -> StoredClassification:
        """Persist a later authoritative hybrid decision for the same message."""

        return await self._repository.store_classification(message_id, result)


@dataclass(frozen=True, slots=True)
class HybridRoutingResolution:
    routing: RoutingResult
    entities: Mapping[str, object]
    ai_used: bool
    fallback_reason: str | None = None


class HybridIntentRoutingService:
    """One-call advisory analyzer behind deterministic confidence and context gates."""

    def __init__(
        self,
        *,
        llm: AuditedLLMService,
        prompt_factory: PromptFactory,
        enabled: bool = True,
        confidence_threshold: float = 0.75,
        margin_threshold: float = 0.15,
        timeout_seconds: float = 5.0,
        max_tokens_per_turn: int = 10_000,
        max_cost_usd_per_turn: float = 0.05,
        input_usd_per_million: float = 1.5,
        output_usd_per_million: float = 9.0,
        cache_size: int = 2048,
    ) -> None:
        if not 0 <= confidence_threshold <= 1:
            raise ValueError("hybrid confidence threshold must be between zero and one")
        if not 0 <= margin_threshold <= 1:
            raise ValueError("hybrid margin threshold must be between zero and one")
        if timeout_seconds <= 0:
            raise ValueError("hybrid timeout must be positive")
        if cache_size < 1:
            raise ValueError("hybrid cache size must be positive")
        self._llm = llm
        self._prompts = prompt_factory
        self._enabled = enabled
        self._confidence_threshold = confidence_threshold
        self._margin_threshold = margin_threshold
        self._timeout_seconds = timeout_seconds
        self._max_tokens_per_turn = max_tokens_per_turn
        self._max_cost_usd_per_turn = max_cost_usd_per_turn
        self._input_usd_per_million = input_usd_per_million
        self._output_usd_per_million = output_usd_per_million
        self._cache_size = cache_size
        self._cache: dict[UUID, HybridRoutingResolution] = {}

    async def resolve(
        self,
        context: ContextEnvelope,
        routing: RoutingResult,
        *,
        available_parameters: frozenset[str] = frozenset(),
        safe_markers: frozenset[str] = frozenset(),
        active_expected_reply: bool = False,
    ) -> HybridRoutingResolution:
        cached = self._cache.get(context.current_message.id)
        if cached is not None:
            return cached
        if not self._should_analyze(
            context,
            routing,
            available_parameters=available_parameters,
            safe_markers=safe_markers,
            active_expected_reply=active_expected_reply,
        ):
            return HybridRoutingResolution(routing=routing, entities={}, ai_used=False)

        budget = TurnBudget(
            max_tokens=self._max_tokens_per_turn,
            max_cost_usd=self._max_cost_usd_per_turn,
            input_usd_per_million=self._input_usd_per_million,
            output_usd_per_million=self._output_usd_per_million,
        )
        expected_missing = self._expected_missing(routing, available_parameters)
        request = self._prompts.hybrid_intent_analysis(
            context,
            routing,
            expected_missing_fields=expected_missing,
            safe_markers=tuple(sorted(safe_markers)),
        )
        try:
            response = await self._llm.generate(
                message_id=context.current_message.id,
                request=request,
                budget=budget,
                timeout_seconds=self._timeout_seconds,
            )
            if not response.text:
                raise ValueError("hybrid analyzer returned no structured decision")
            decision = HybridIntentDecision.model_validate_json(response.text)
            if decision.language != context.current_message.language:
                raise ValueError("hybrid analyzer changed the guest language")
            resolution = self._apply_decision(
                context,
                decision,
                available_parameters=available_parameters,
            )
        except (LLMError, ValidationError, ValueError):
            resolution = HybridRoutingResolution(
                routing=self._fallback_clarification(context),
                entities={},
                ai_used=True,
                fallback_reason="hybrid_analyzer_unavailable_or_invalid",
            )
        self._remember(context.current_message.id, resolution)
        LOGGER.info(
            "hybrid intent routing completed",
            extra={
                "message_id": str(context.current_message.id),
                "routing_source": "hybrid_llm",
                "selected_intent": resolution.routing.prediction.intent.value,
                "confidence": resolution.routing.prediction.confidence,
                "ai_used": True,
                "routing_decision": resolution.routing.decision.value,
                "fallback_reason": resolution.fallback_reason,
            },
        )
        return resolution

    def _should_analyze(
        self,
        context: ContextEnvelope,
        routing: RoutingResult,
        *,
        available_parameters: frozenset[str],
        safe_markers: frozenset[str],
        active_expected_reply: bool,
    ) -> bool:
        if not self._enabled or active_expected_reply:
            return False
        if routing.reason_code in {
            "deterministic_greeting",
            "explicit_human_or_safety_escalation",
            "classified_human_escalation",
        }:
            return False
        if context.state.active_workflow is not None:
            return True
        if {"BOOKING_REFERENCE_PRESENT", "SERVICE_TRACKING_CODE_PRESENT"} & safe_markers:
            return False
        if (
            routing.prediction.intent is IntentCode.ROOM_AVAILABILITY
            and {"check_in", "check_out", "adults"} <= available_parameters
        ):
            return False
        prediction = routing.prediction
        if routing.reason_code in HYBRID_GATE_REASONS:
            return True
        if (
            routing.decision is RoutingDecision.KNOWLEDGE_CANDIDATE
            and len(context.current_message.text.split()) <= 2
        ):
            return True
        if (
            prediction.confidence < self._confidence_threshold
            or prediction.margin < self._margin_threshold
        ):
            return routing.decision not in {
                RoutingDecision.CONTROLLED_RESPONSE,
                RoutingDecision.ESCALATE,
            }
        return False

    def _apply_decision(
        self,
        context: ContextEnvelope,
        decision: HybridIntentDecision,
        *,
        available_parameters: frozenset[str],
    ) -> HybridRoutingResolution:
        entities = {
            name: value
            for name, value in decision.entities.model_dump().items()
            if value is not None
        }
        if "service_description" in entities:
            entities["description"] = entities.pop("service_description")
        entities = {
            name: value
            for name, value in entities.items()
            if name in HYBRID_SAFE_PARAMETER_NAMES
        }
        if decision.confidence < self._confidence_threshold:
            return HybridRoutingResolution(
                routing=self._clarification(
                    context,
                    clarification=decision.clarification_question,
                    reason_code="hybrid_low_confidence",
                ),
                entities={},
                ai_used=True,
                fallback_reason="hybrid_low_confidence",
            )
        if decision.mode == "ambiguous":
            return HybridRoutingResolution(
                routing=self._clarification(
                    context,
                    clarification=decision.clarification_question,
                    reason_code="hybrid_ambiguity",
                ),
                entities={},
                ai_used=True,
            )
        if decision.mode == "unsupported":
            return HybridRoutingResolution(
                routing=RoutingResult(
                    prediction=self._prediction(
                        IntentCode.UNSUPPORTED,
                        decision.confidence,
                    ),
                    decision=RoutingDecision.FALLBACK,
                    reason_code="hybrid_unsupported",
                ),
                entities={},
                ai_used=True,
            )
        if decision.mode == "knowledge":
            return HybridRoutingResolution(
                routing=RoutingResult(
                    prediction=self._prediction(
                        IntentCode.HOTEL_INFO,
                        decision.confidence,
                    ),
                    decision=RoutingDecision.KNOWLEDGE_CANDIDATE,
                    reason_code="hybrid_knowledge_candidate",
                    normalized_knowledge_query=decision.normalized_knowledge_query,
                    material_conditions=decision.material_conditions,
                ),
                entities={},
                ai_used=True,
            )

        assert decision.intent is not None
        available = available_parameters | frozenset(entities)
        missing = tuple(
            name
            for name in INTENT_DEFINITIONS[decision.intent].required_parameters
            if name not in available
        )
        return HybridRoutingResolution(
            routing=RoutingResult(
                prediction=self._prediction(decision.intent, decision.confidence),
                decision=(
                    RoutingDecision.CLARIFY
                    if missing or decision.needs_clarification
                    else RoutingDecision.ACTION_CANDIDATE
                ),
                missing_parameters=missing,
                requires_confirmation=decision.intent in STATE_CHANGING_INTENTS,
                allow_tool_execution=False,
                reason_code=(
                    "hybrid_missing_required_parameters"
                    if missing
                    else "hybrid_requires_orchestrator_validation"
                ),
                clarification_question=(
                    decision.clarification_question
                    if decision.needs_clarification
                    else None
                ),
            ),
            entities=entities,
            ai_used=True,
        )

    def _fallback_clarification(
        self,
        context: ContextEnvelope,
    ) -> RoutingResult:
        subject = " ".join(context.current_message.text.split())[:100]
        if context.current_message.language == "ar":
            question = (
                f"تعذر تحديد المقصود من «{subject}». "
                "هل تريد تنفيذ خدمة فندقية أم معرفة معلومات عنها؟"
            )
        else:
            question = (
                f'I could not determine the intent of "{subject}". '
                "Do you want a hotel service performed or information about it?"
            )
        return self._clarification(
            context,
            clarification=question,
            reason_code="hybrid_analyzer_fallback",
        )

    @staticmethod
    def _clarification(
        context: ContextEnvelope,
        *,
        clarification: str | None,
        reason_code: str,
    ) -> RoutingResult:
        language = context.current_message.language
        question = clarification or (
            "هل تريد تنفيذ خدمة فندقية أم معرفة معلومات عنها؟"
            if language == "ar"
            else "Do you want a hotel service performed or information about it?"
        )
        return RoutingResult(
            prediction=HybridIntentRoutingService._prediction(
                IntentCode.HOTEL_INFO,
                0.0,
            ),
            decision=RoutingDecision.CLARIFY,
            reason_code=reason_code,
            clarification_question=question,
        )

    @staticmethod
    def _prediction(intent: IntentCode, confidence: float) -> IntentPrediction:
        scores = {candidate: 0.0 for candidate in IntentCode}
        scores[intent] = confidence
        return IntentPrediction(
            intent=intent,
            confidence=confidence,
            margin=confidence,
            classifier_version=HYBRID_ROUTER_VERSION,
            scores=scores,
            source=PredictionSource.HYBRID_LLM,
        )

    @staticmethod
    def _expected_missing(
        routing: RoutingResult,
        available_parameters: frozenset[str],
    ) -> tuple[str, ...]:
        required = INTENT_DEFINITIONS[routing.prediction.intent].required_parameters
        return tuple(name for name in required if name not in available_parameters)

    def _remember(
        self,
        message_id: UUID,
        resolution: HybridRoutingResolution,
    ) -> None:
        if len(self._cache) >= self._cache_size:
            self._cache.pop(next(iter(self._cache)))
        self._cache[message_id] = resolution
