"""Offline contracts for confidence-gated semantic intent analysis."""

import asyncio
from collections.abc import Mapping
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast
from uuid import uuid4

import pytest

from hotel_bot.application.guest_flows import (
    _active_workflow_expected_reply,
    extract_parameters,
    sanitize_context,
)
from hotel_bot.application.intent_routing import HybridIntentRoutingService
from hotel_bot.application.llm import AuditedLLMService, HybridOrchestrator
from hotel_bot.application.prompts import PromptFactory
from hotel_bot.domain.conversation.enums import ActiveWorkflow, MessageDirection
from hotel_bot.domain.conversation.models import (
    ContextEnvelope,
    ConversationState,
    MessageSnapshot,
)
from hotel_bot.domain.intent.classifier import (
    ALGORITHM_VERSION,
    NaiveBayesIntentClassifier,
)
from hotel_bot.domain.intent.enums import (
    DatasetSplit,
    IntentCode,
    PredictionSource,
    RoutingDecision,
)
from hotel_bot.domain.intent.models import IntentPrediction, RoutingResult
from hotel_bot.domain.intent.routing import SafeIntentRouter
from hotel_bot.domain.llm.enums import AnswerBasis, LLMRequestKind, LLMRunStatus
from hotel_bot.domain.llm.errors import LLMUnavailableError
from hotel_bot.domain.llm.models import (
    HybridIntentDecision,
    HybridIntentEntities,
    LLMRequest,
    LLMResponse,
    LLMRunRecord,
    LLMUsage,
)
from hotel_bot.infrastructure.gemini import GeminiAdapter
from hotel_bot.infrastructure.intent_dataset import load_intent_dataset

NOW = datetime(2026, 7, 31, 12, 0, 0)


class OfflineProvider:
    provider_name = "offline_stub"
    model_name = "offline-model"

    def __init__(
        self,
        responses: list[LLMResponse | Exception],
        *,
        delay_seconds: float = 0,
    ) -> None:
        self.responses = responses
        self.delay_seconds = delay_seconds
        self.requests: list[LLMRequest] = []

    async def generate(self, request: LLMRequest) -> LLMResponse:
        self.requests.append(request)
        if self.delay_seconds:
            await asyncio.sleep(self.delay_seconds)
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response

    async def close(self) -> None:
        return None


class MemoryLLMAudit:
    def __init__(self) -> None:
        self.records: list[LLMRunRecord] = []

    async def record_llm_run(self, record: LLMRunRecord) -> None:
        self.records.append(record)


class UnusedRetrieval:
    async def retrieve(self, query: str) -> object:
        raise AssertionError(f"Knowledge retrieval was not expected: {query}")


@pytest.fixture(scope="module")
def production_router() -> SafeIntentRouter:
    path = (
        Path(__file__).parents[3]
        / "src"
        / "hotel_bot"
        / "intent"
        / "data"
        / "intent-dataset-v1.json"
    )
    loaded = load_intent_dataset(path)
    classifier = NaiveBayesIntentClassifier(
        classifier_version=f"{ALGORITHM_VERSION}+{loaded.sha256[:12]}"
    )
    classifier.fit(
        sample
        for sample in loaded.dataset.samples
        if sample.split is DatasetSplit.TRAIN
    )
    return SafeIntentRouter(classifier)


def response(decision: HybridIntentDecision | str) -> LLMResponse:
    return LLMResponse(
        text=(
            decision.model_dump_json()
            if isinstance(decision, HybridIntentDecision)
            else decision
        ),
        usage=LLMUsage(
            input_tokens=100,
            output_tokens=40,
            total_tokens=140,
        ),
        provider_request_id="offline-1",
        finish_reason="STOP",
    )


def envelope(
    text: str,
    *,
    language: str = "ar",
    state: ConversationState | None = None,
) -> ContextEnvelope:
    conversation_id = uuid4()
    return ContextEnvelope(
        state=state or ConversationState(language=cast(Any, language)),
        current_message=MessageSnapshot(
            id=uuid4(),
            conversation_id=conversation_id,
            sequence_number=1,
            direction=MessageDirection.INBOUND,
            text=text,
            language=cast(Any, language),
            correlation_id="hybrid-offline-test",
            created_at=NOW,
        ),
        turns=(),
        evidence=(),
        summary=None,
        estimated_tokens=30,
        truncated=False,
    )


def parameters(text: str, state: ConversationState | None = None) -> dict[str, object]:
    return extract_parameters(
        text,
        state or ConversationState(language="ar"),
        idempotency_seed="hybrid-offline-test",
    )


def available(values: Mapping[str, object]) -> frozenset[str]:
    return frozenset(
        name
        for name, value in values.items()
        if value is not None and value != ""
    )


def hybrid_service(
    provider: OfflineProvider,
    *,
    timeout_seconds: float = 1,
    enabled: bool = True,
) -> tuple[HybridIntentRoutingService, MemoryLLMAudit]:
    audit = MemoryLLMAudit()
    service = HybridIntentRoutingService(
        llm=AuditedLLMService(provider, audit),
        prompt_factory=PromptFactory(max_output_tokens=512),
        enabled=enabled,
        confidence_threshold=0.75,
        margin_threshold=0.15,
        timeout_seconds=timeout_seconds,
        max_tokens_per_turn=10_000,
        max_cost_usd_per_turn=1,
        input_usd_per_million=0,
        output_usd_per_million=0,
    )
    return service, audit


def analyze(
    service: HybridIntentRoutingService,
    context: ContextEnvelope,
    routing: RoutingResult,
    values: Mapping[str, object],
    *,
    markers: frozenset[str] = frozenset(),
    active_expected_reply: bool = False,
):
    return asyncio.run(
        service.resolve(
            context,
            routing,
            available_parameters=available(values),
            safe_markers=markers,
            active_expected_reply=active_expected_reply,
        )
    )


def controlled_answer(context: ContextEnvelope, routing: RoutingResult) -> tuple[str, int]:
    provider = OfflineProvider([])
    llm_audit = MemoryLLMAudit()
    orchestrator = HybridOrchestrator(
        llm=AuditedLLMService(provider, llm_audit),
        retrieval=cast(Any, UnusedRetrieval()),
        registry=cast(Any, object()),
        tool_executor=cast(Any, object()),
        prompt_factory=PromptFactory(),
        max_tokens_per_turn=10_000,
        max_cost_usd_per_turn=1,
        input_usd_per_million=0,
        output_usd_per_million=0,
    )
    result = asyncio.run(orchestrator.handle(context, routing))
    assert result.answer.basis is AnswerBasis.CONTROLLED
    assert result.tool_executed is False
    return result.answer.text, 0


@pytest.mark.parametrize(
    "text",
    [
        "جيبلي الفطور لو سمحت",
        "فيك تأمنلي فطور عالسريع للغرفة؟",
    ],
)
def test_colloquial_breakfast_actions_enter_room_service_and_ask_only_for_room(
    production_router: SafeIntentRouter,
    text: str,
) -> None:
    values = parameters(text)
    initial = production_router.route(text, "ar", parameters=values)
    decision = HybridIntentDecision(
        mode="action",
        intent=IntentCode.ROOM_SERVICE_REQUEST,
        confidence=0.96,
        language="ar",
        entities=HybridIntentEntities(
            category="food_and_beverage",
            service_description="طلب تقديم وجبة فطور إلى الغرفة",
        ),
        missing_fields=("room_number",),
        needs_clarification=False,
    )
    provider = OfflineProvider([response(decision)])
    service, _ = hybrid_service(provider)

    resolved = analyze(service, envelope(text), initial, values)
    answer, tool_events = controlled_answer(envelope(text), resolved.routing)

    assert resolved.ai_used is True
    assert resolved.routing.prediction.intent is IntentCode.ROOM_SERVICE_REQUEST
    assert resolved.routing.prediction.source is PredictionSource.HYBRID_LLM
    assert resolved.routing.missing_parameters == ("room_number",)
    assert resolved.routing.decision is RoutingDecision.CLARIFY
    assert "رقم الغرفة" in answer
    assert tool_events == 0
    assert [item.kind for item in provider.requests] == [
        LLMRequestKind.HYBRID_INTENT_ANALYSIS
    ]


def test_clear_breakfast_information_bypasses_ai_and_remains_knowledge(
    production_router: SafeIntentRouter,
) -> None:
    text = "شو وقت تقديم الفطور؟"
    values = parameters(text)
    initial = production_router.route(text, "ar", parameters=values)
    provider = OfflineProvider([])
    service, _ = hybrid_service(provider)

    resolved = analyze(service, envelope(text), initial, values)

    assert resolved.ai_used is False
    assert resolved.routing.prediction.intent is IntentCode.HOTEL_INFO
    assert resolved.routing.decision is RoutingDecision.KNOWLEDGE_CANDIDATE
    assert provider.requests == []


def test_one_word_breakfast_is_focused_ambiguity(
    production_router: SafeIntentRouter,
) -> None:
    text = "الفطور؟"
    values = parameters(text)
    initial = production_router.route(text, "ar", parameters=values)
    decision = HybridIntentDecision(
        mode="ambiguous",
        confidence=0.93,
        language="ar",
        needs_clarification=True,
        clarification_question="هل تريد معرفة مواعيد الفطور أم طلب فطور للغرفة؟",
    )
    provider = OfflineProvider([response(decision)])
    service, _ = hybrid_service(provider)

    resolved = analyze(service, envelope(text), initial, values)
    answer, tool_events = controlled_answer(envelope(text), resolved.routing)

    assert resolved.routing.decision is RoutingDecision.CLARIFY
    assert answer == decision.clarification_question
    assert tool_events == 0
    assert len(provider.requests) == 1


def test_conflicting_room_policy_is_resolved_to_knowledge_without_tool(
    production_router: SafeIntentRouter,
) -> None:
    text = "هل تسمحون بحجز غرفة لشاب وفتاة غير متزوجين؟"
    values = parameters(text)
    initial = production_router.route(text, "ar", parameters=values)
    decision = HybridIntentDecision(
        mode="knowledge",
        intent=IntentCode.HOTEL_INFO,
        confidence=0.97,
        language="ar",
        normalized_knowledge_query="سياسة ومتطلبات حجز غرفة مشتركة لضيفين غير متزوجين",
        material_conditions=("غرفة مشتركة", "ضيفان غير متزوجين"),
    )
    provider = OfflineProvider([response(decision)])
    service, _ = hybrid_service(provider)

    resolved = analyze(service, envelope(text), initial, values)

    assert initial.reason_code == "informational_or_ambiguous_knowledge_candidate"
    assert resolved.routing.decision is RoutingDecision.KNOWLEDGE_CANDIDATE
    assert resolved.routing.prediction.intent is IntentCode.HOTEL_INFO
    assert resolved.routing.normalized_knowledge_query == decision.normalized_knowledge_query
    assert resolved.routing.prediction.intent is not IntentCode.ROOM_AVAILABILITY
    assert len(provider.requests) == 1


def test_clear_airport_information_bypasses_ai_as_high_confidence_knowledge(
    production_router: SafeIntentRouter,
) -> None:
    text = "هل يوفر الفندق خدمة نقل من المطار؟"
    values = parameters(text)
    initial = production_router.route(text, "ar", parameters=values)
    provider = OfflineProvider([])
    service, _ = hybrid_service(provider)

    resolved = analyze(service, envelope(text), initial, values)

    assert resolved.ai_used is False
    assert resolved.routing.decision is RoutingDecision.KNOWLEDGE_CANDIDATE
    assert provider.requests == []


def test_dated_availability_is_a_deterministic_fast_path(
    production_router: SafeIntentRouter,
) -> None:
    text = "أريد غرفة من 2026-08-10 إلى 2026-08-12 لشخصين"
    values = parameters(text)
    initial = production_router.route(text, "ar", parameters=values)
    provider = OfflineProvider([])
    service, _ = hybrid_service(provider)

    resolved = analyze(service, envelope(text), initial, values)

    assert initial.prediction.intent is IntentCode.ROOM_AVAILABILITY
    assert initial.decision is RoutingDecision.ACTION_CANDIDATE
    assert {"check_in", "check_out", "adults"} <= available(values)
    assert resolved.ai_used is False
    assert provider.requests == []


def test_booking_reference_is_a_deterministic_fast_path_and_value_is_not_sent(
    production_router: SafeIntentRouter,
) -> None:
    text = "أريد متابعة الحجز BKG-2026-0001"
    values = parameters(text)
    initial = production_router.route(text, "ar", parameters=values)
    provider = OfflineProvider([])
    service, _ = hybrid_service(provider)

    resolved = analyze(
        service,
        envelope("[BOOKING_REFERENCE]"),
        initial,
        values,
        markers=frozenset({"BOOKING_REFERENCE_PRESENT"}),
    )

    assert resolved.ai_used is False
    assert resolved.routing.prediction.intent is IntentCode.BOOKING_LOOKUP
    assert provider.requests == []


def test_active_workflow_room_number_is_a_deterministic_fast_path() -> None:
    state = ConversationState(
        language="ar",
        active_workflow=ActiveWorkflow.ROOM_SERVICE,
        service_category="food_and_beverage",
        service_description="طلب تقديم وجبة فطور إلى الغرفة",
    )
    text = "101"
    values = parameters(text, state)
    initial = RoutingResult(
        prediction=IntentPrediction(
            intent=IntentCode.ROOM_SERVICE_REQUEST,
            confidence=1,
            margin=1,
            classifier_version="session-workflow-v1",
            scores={IntentCode.ROOM_SERVICE_REQUEST: 1},
            source=PredictionSource.RULE,
        ),
        decision=RoutingDecision.ACTION_CANDIDATE,
        requires_confirmation=True,
        reason_code="session_workflow",
    )
    provider = OfflineProvider([])
    service, _ = hybrid_service(provider)
    context = envelope(text, state=state)

    resolved = analyze(
        service,
        context,
        initial,
        values,
        active_expected_reply=_active_workflow_expected_reply(state, text),
    )

    assert values["room_number"] == "101"
    assert resolved.ai_used is False
    assert provider.requests == []


def test_high_confidence_maintenance_action_preserves_confirmation() -> None:
    initial = RoutingResult(
        prediction=IntentPrediction(
            intent=IntentCode.MAINTENANCE_REQUEST,
            confidence=0.98,
            margin=0.92,
            classifier_version="classifier-v1",
            scores={IntentCode.MAINTENANCE_REQUEST: 0.98},
        ),
        decision=RoutingDecision.ACTION_CANDIDATE,
        requires_confirmation=True,
        reason_code="requires_orchestrator_validation",
    )
    values = {
        "room_number": "204",
        "description": "The air conditioner is not working.",
        "category": "hvac",
    }
    provider = OfflineProvider([])
    service, _ = hybrid_service(provider)

    resolved = analyze(
        service,
        envelope("The air conditioner in room 204 is not working.", language="en"),
        initial,
        values,
    )

    assert resolved.ai_used is False
    assert resolved.routing.requires_confirmation is True
    assert provider.requests == []


@pytest.mark.parametrize(
    ("provider_response", "expected_status"),
    [
        (LLMUnavailableError("429 RESOURCE_EXHAUSTED"), LLMRunStatus.FAILED),
        ("not-json", LLMRunStatus.SUCCEEDED),
        (
            (
                '{"mode":"action","intent":"delete_database","confidence":0.99,'
                '"language":"ar","entities":{},"missing_fields":[],'
                '"needs_clarification":false,"clarification_question":null,'
                '"normalized_knowledge_query":null,"material_conditions":[]}'
            ),
            LLMRunStatus.SUCCEEDED,
        ),
        (
            (
                '{"mode":"action","intent":"room_service_request","confidence":0.99,'
                '"language":"ar","entities":{},"missing_fields":[],'
                '"needs_clarification":false,"clarification_question":null,'
                '"normalized_knowledge_query":null,"material_conditions":[],'
                '"tool":"delete_database"}'
            ),
            LLMRunStatus.SUCCEEDED,
        ),
    ],
)
def test_provider_or_schema_failure_never_guesses_a_tool(
    provider_response: LLMResponse | Exception | str,
    expected_status: LLMRunStatus,
) -> None:
    initial = RoutingResult(
        prediction=IntentPrediction(
            intent=IntentCode.HOTEL_INFO,
            confidence=1,
            margin=1,
            classifier_version="rule-v1",
            scores={IntentCode.HOTEL_INFO: 1},
            source=PredictionSource.RULE,
        ),
        decision=RoutingDecision.KNOWLEDGE_CANDIDATE,
        reason_code="informational_or_ambiguous_knowledge_candidate",
    )
    item = (
        response(provider_response)
        if isinstance(provider_response, str)
        else provider_response
    )
    provider = OfflineProvider([item])
    service, audit = hybrid_service(provider)

    resolved = analyze(
        service,
        envelope("ممكن تعملها؟"),
        initial,
        {},
    )
    answer, tool_events = controlled_answer(
        envelope("ممكن تعملها؟"),
        resolved.routing,
    )

    assert resolved.routing.decision is RoutingDecision.CLARIFY
    assert resolved.routing.allow_tool_execution is False
    assert resolved.routing.reason_code == "hybrid_analyzer_fallback"
    assert "تنفيذ خدمة" in answer
    assert tool_events == 0
    assert len(provider.requests) == 1
    assert audit.records[0].status is expected_status


def test_valid_but_low_confidence_ai_decision_cannot_select_an_action() -> None:
    initial = RoutingResult(
        prediction=IntentPrediction(
            intent=IntentCode.HOTEL_INFO,
            confidence=0.4,
            margin=0.01,
            classifier_version="classifier-v1",
            scores={
                IntentCode.HOTEL_INFO: 0.4,
                IntentCode.ROOM_SERVICE_REQUEST: 0.39,
            },
        ),
        decision=RoutingDecision.KNOWLEDGE_CANDIDATE,
        reason_code="informational_or_ambiguous_knowledge_candidate",
    )
    provider = OfflineProvider(
        [
            response(
                HybridIntentDecision(
                    mode="action",
                    intent=IntentCode.ROOM_SERVICE_REQUEST,
                    confidence=0.61,
                    language="en",
                    entities=HybridIntentEntities(
                        service_description="Bring the seasonal welcome tray."
                    ),
                )
            )
        ]
    )
    service, _ = hybrid_service(provider)

    resolved = analyze(
        service,
        envelope("Could you sort that thing for me?", language="en"),
        initial,
        {},
    )

    assert resolved.routing.decision is RoutingDecision.CLARIFY
    assert resolved.routing.allow_tool_execution is False
    assert resolved.routing.reason_code == "hybrid_low_confidence"
    assert resolved.entities == {}


def test_timeout_is_audited_and_returns_safe_clarification() -> None:
    initial = RoutingResult(
        prediction=IntentPrediction(
            intent=IntentCode.HOTEL_INFO,
            confidence=0.4,
            margin=0.02,
            classifier_version="classifier-v1",
            scores={IntentCode.HOTEL_INFO: 0.4},
        ),
        decision=RoutingDecision.KNOWLEDGE_CANDIDATE,
        reason_code="low_confidence_or_margin",
    )
    provider = OfflineProvider(
        [
            response(
                HybridIntentDecision(
                    mode="knowledge",
                    confidence=0.9,
                    language="en",
                    normalized_knowledge_query="late response",
                )
            )
        ],
        delay_seconds=0.05,
    )
    service, audit = hybrid_service(provider, timeout_seconds=0.005)

    resolved = analyze(
        service,
        envelope("Could you handle that?", language="en"),
        initial,
        {},
    )

    assert resolved.routing.decision is RoutingDecision.CLARIFY
    assert audit.records[0].status is LLMRunStatus.TIMED_OUT
    assert audit.records[0].error_code == "llm_timeout"


def test_provider_failure_during_active_subject_change_never_runs_old_action() -> None:
    state = ConversationState(
        language="ar",
        check_in=datetime(2026, 8, 10).date(),
        check_out=datetime(2026, 8, 12).date(),
        adults=2,
        active_workflow=ActiveWorkflow.AVAILABILITY,
    )
    initial = RoutingResult(
        prediction=IntentPrediction(
            intent=IntentCode.ROOM_AVAILABILITY,
            confidence=1,
            margin=1,
            classifier_version="session-workflow-v1",
            scores={IntentCode.ROOM_AVAILABILITY: 1},
            source=PredictionSource.RULE,
        ),
        decision=RoutingDecision.ACTION_CANDIDATE,
        reason_code="session_workflow",
    )
    provider = OfflineProvider([LLMUnavailableError("429 RESOURCE_EXHAUSTED")])
    service, _ = hybrid_service(provider)

    resolved = analyze(
        service,
        envelope("شو وقت تسجيل الخروج؟", state=state),
        initial,
        {
            "check_in": state.check_in,
            "check_out": state.check_out,
            "adults": state.adults,
        },
        active_expected_reply=False,
    )

    assert resolved.routing.decision is RoutingDecision.CLARIFY
    assert resolved.routing.allow_tool_execution is False
    assert resolved.routing.prediction.intent is not IntentCode.ROOM_AVAILABILITY


def test_sensitive_verification_value_never_enters_ai_request_or_cache() -> None:
    secret = "Verify-Secret-9281"
    raw = envelope(
        f"رمز التحقق: {secret}",
        state=ConversationState(
            language="ar",
            active_workflow=ActiveWorkflow.BOOKING_LOOKUP,
            masked_booking_reference="BKG-***-0001",
        ),
    )
    sanitized = sanitize_context(raw, verification_value=secret)
    initial = RoutingResult(
        prediction=IntentPrediction(
            intent=IntentCode.BOOKING_LOOKUP,
            confidence=1,
            margin=1,
            classifier_version="session-workflow-v1",
            scores={IntentCode.BOOKING_LOOKUP: 1},
            source=PredictionSource.RULE,
        ),
        decision=RoutingDecision.CLARIFY,
        missing_parameters=("verification_value",),
        reason_code="session_workflow",
    )
    decision = HybridIntentDecision(
        mode="ambiguous",
        confidence=0.9,
        language="ar",
        needs_clarification=True,
        clarification_question="هل تريد متابعة الحجز الحالي أم بدء طلب جديد؟",
    )
    provider = OfflineProvider([response(decision)])
    service, _ = hybrid_service(provider)

    first = analyze(
        service,
        sanitized,
        initial,
        {},
        markers=frozenset({"VERIFICATION_VALUE_REDACTED"}),
    )
    second = analyze(
        service,
        sanitized,
        initial,
        {},
        markers=frozenset({"VERIFICATION_VALUE_REDACTED"}),
    )

    assert first == second
    assert len(provider.requests) == 1
    assert secret not in provider.requests[0].prompt
    assert "BKG-***-0001" not in provider.requests[0].prompt
    assert "VERIFICATION_VALUE_REDACTED" in provider.requests[0].prompt
    assert "verification_value" not in first.entities


@pytest.mark.parametrize(
    ("text", "language", "question"),
    [
        (
            "ترتيب الوسائد الموسمية؟",
            "ar",
            "هل تريد معلومات عن الترتيب أم طلب تنفيذه للغرفة؟",
        ),
        (
            "Seasonal pillow arrangement?",
            "en",
            "Do you want information about the arrangement or have it prepared?",
        ),
    ],
)
def test_language_is_preserved_for_focused_clarifications(
    text: str,
    language: str,
    question: str,
) -> None:
    initial = RoutingResult(
        prediction=IntentPrediction(
            intent=IntentCode.HOTEL_INFO,
            confidence=0.45,
            margin=0.03,
            classifier_version="classifier-v1",
            scores={IntentCode.HOTEL_INFO: 0.45},
        ),
        decision=RoutingDecision.KNOWLEDGE_CANDIDATE,
        reason_code="informational_or_ambiguous_knowledge_candidate",
    )
    decision = HybridIntentDecision(
        mode="ambiguous",
        confidence=0.91,
        language=cast(Any, language),
        needs_clarification=True,
        clarification_question=question,
    )
    provider = OfflineProvider([response(decision)])
    service, _ = hybrid_service(provider)

    resolved = analyze(
        service,
        envelope(text, language=language),
        initial,
        {},
    )

    assert resolved.routing.clarification_question == question
    assert resolved.routing.prediction.source is PredictionSource.HYBRID_LLM


def test_future_information_topic_requires_no_production_topic_rule() -> None:
    text = "متى يسمح باستخدام بطاقة الضوضاء البنفسجية في الردهة؟"
    initial = RoutingResult(
        prediction=IntentPrediction(
            intent=IntentCode.GREETING_SMALLTALK,
            confidence=0.42,
            margin=0.01,
            classifier_version="classifier-v1",
            scores={
                IntentCode.GREETING_SMALLTALK: 0.42,
                IntentCode.HOTEL_INFO: 0.41,
            },
        ),
        decision=RoutingDecision.KNOWLEDGE_CANDIDATE,
        reason_code="informational_or_ambiguous_knowledge_candidate",
    )
    decision = HybridIntentDecision(
        mode="knowledge",
        confidence=0.94,
        language="ar",
        normalized_knowledge_query="سياسة استخدام بطاقة الضوضاء البنفسجية في الردهة",
        material_conditions=("بطاقة الضوضاء البنفسجية", "الردهة"),
    )
    provider = OfflineProvider([response(decision)])
    service, _ = hybrid_service(provider)

    resolved = analyze(service, envelope(text), initial, {})

    assert resolved.routing.decision is RoutingDecision.KNOWLEDGE_CANDIDATE
    assert resolved.routing.normalized_knowledge_query == decision.normalized_knowledge_query
    assert len(provider.requests) == 1


def test_future_colloquial_action_maps_only_to_existing_allowlisted_workflow() -> None:
    text = "بدّي ياهن يزبطولي الستارة بالغرفة لو سمحت"
    initial = RoutingResult(
        prediction=IntentPrediction(
            intent=IntentCode.HOTEL_INFO,
            confidence=0.49,
            margin=0.02,
            classifier_version="classifier-v1",
            scores={
                IntentCode.HOTEL_INFO: 0.49,
                IntentCode.MAINTENANCE_REQUEST: 0.47,
            },
        ),
        decision=RoutingDecision.KNOWLEDGE_CANDIDATE,
        reason_code="informational_or_ambiguous_knowledge_candidate",
    )
    decision = HybridIntentDecision(
        mode="action",
        intent=IntentCode.MAINTENANCE_REQUEST,
        confidence=0.95,
        language="ar",
        entities=HybridIntentEntities(
            service_description="الستارة في الغرفة تحتاج إلى إصلاح",
        ),
        missing_fields=("room_number",),
    )
    provider = OfflineProvider([response(decision)])
    service, _ = hybrid_service(provider)

    resolved = analyze(service, envelope(text), initial, {})

    assert resolved.routing.prediction.intent is IntentCode.MAINTENANCE_REQUEST
    assert resolved.routing.missing_parameters == ("room_number",)
    assert resolved.routing.requires_confirmation is True
    assert resolved.routing.allow_tool_execution is False
    assert set(resolved.entities) == {"description"}


def test_hybrid_router_can_be_disabled_without_provider_use() -> None:
    initial = RoutingResult(
        prediction=IntentPrediction(
            intent=IntentCode.HOTEL_INFO,
            confidence=0.3,
            margin=0.01,
            classifier_version="classifier-v1",
            scores={IntentCode.HOTEL_INFO: 0.3},
        ),
        decision=RoutingDecision.KNOWLEDGE_CANDIDATE,
        reason_code="informational_or_ambiguous_knowledge_candidate",
    )
    provider = OfflineProvider([])
    service, _ = hybrid_service(provider, enabled=False)

    resolved = analyze(service, envelope("طلب عامي غير واضح"), initial, {})

    assert resolved.ai_used is False
    assert resolved.routing == initial
    assert provider.requests == []


def test_gemini_adapter_disables_transport_retries_for_hybrid_analysis() -> None:
    captured: dict[str, object] = {}

    class FakeModels:
        async def generate_content(self, **kwargs: object) -> object:
            captured.update(kwargs)
            return SimpleNamespace(
                usage_metadata=None,
                candidates=[],
                response_id="offline-adapter-test",
            )

    class FakeAio:
        def __init__(self) -> None:
            self.models = FakeModels()

        async def aclose(self) -> None:
            return None

    adapter = GeminiAdapter(
        api_key="offline-test-key",
        model="gemini-2.5-flash",
        retry_attempts=2,
    )
    asyncio.run(adapter.close())
    adapter._client = cast(Any, SimpleNamespace(aio=FakeAio()))
    request = LLMRequest(
        kind=LLMRequestKind.HYBRID_INTENT_ANALYSIS,
        system_instruction="A sufficiently long offline system instruction.",
        prompt="offline",
        response_schema=HybridIntentDecision.model_json_schema(mode="validation"),
        max_output_tokens=128,
        estimated_input_tokens=10,
    )

    asyncio.run(adapter.generate(request))

    config = cast(Any, captured["config"])
    assert config.http_options.retry_options.attempts == 1
