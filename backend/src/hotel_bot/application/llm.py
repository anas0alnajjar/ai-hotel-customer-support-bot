"""Audited LLM execution and safe hybrid orchestration."""

import asyncio
import re
from collections.abc import Mapping
from time import perf_counter
from typing import Protocol
from uuid import UUID

from pydantic import ValidationError

from hotel_bot.application.knowledge import KnowledgeRetrievalService
from hotel_bot.application.prompts import PROMPT_VERSION, PromptFactory
from hotel_bot.application.tools import ControlledToolExecutor
from hotel_bot.domain.conversation.models import ContextEnvelope
from hotel_bot.domain.intent.enums import IntentCode, RoutingDecision
from hotel_bot.domain.intent.models import RoutingResult
from hotel_bot.domain.intent.normalization import normalize_text
from hotel_bot.domain.intent.taxonomy import INTENT_DEFINITIONS
from hotel_bot.domain.knowledge.models import RetrievalEvidence, RetrievalResult
from hotel_bot.domain.llm.enums import AnswerBasis, LLMRunStatus
from hotel_bot.domain.llm.errors import (
    LLMAuditError,
    LLMBudgetExceededError,
    LLMContractError,
    LLMError,
    LLMTimeoutError,
)
from hotel_bot.domain.llm.models import (
    GroundedAnswer,
    KnowledgeSearchQuery,
    LLMRequest,
    LLMResponse,
    LLMRunRecord,
    LLMUsage,
    OrchestrationResult,
)
from hotel_bot.domain.tools.enums import ToolCaller, ToolExecutionStatus
from hotel_bot.domain.tools.models import ToolCall, ToolExecutionContext, ToolExecutionResult
from hotel_bot.domain.tools.registry import ToolRegistry


class LLMProvider(Protocol):
    provider_name: str
    model_name: str

    async def generate(self, request: LLMRequest) -> LLMResponse: ...

    async def close(self) -> None: ...


class LLMRunRepository(Protocol):
    async def record_llm_run(self, record: LLMRunRecord) -> None: ...


class TurnBudget:
    """Conservative per-turn reservation using configured token and price ceilings."""

    def __init__(
        self,
        *,
        max_tokens: int,
        max_cost_usd: float,
        input_usd_per_million: float,
        output_usd_per_million: float,
    ) -> None:
        self._max_tokens = max_tokens
        self._max_cost_usd = max_cost_usd
        self._input_rate = input_usd_per_million
        self._output_rate = output_usd_per_million
        self._reserved_tokens = 0
        self._reserved_cost = 0.0

    def reserve(self, request: LLMRequest) -> None:
        tokens = request.estimated_input_tokens + request.max_output_tokens
        cost = self.estimate_cost(
            LLMUsage(
                input_tokens=request.estimated_input_tokens,
                output_tokens=request.max_output_tokens,
                total_tokens=tokens,
            )
        )
        if self._reserved_tokens + tokens > self._max_tokens:
            raise LLMBudgetExceededError("per-turn token budget exceeded")
        if self._reserved_cost + cost > self._max_cost_usd:
            raise LLMBudgetExceededError("per-turn cost budget exceeded")
        self._reserved_tokens += tokens
        self._reserved_cost += cost

    def estimate_cost(self, usage: LLMUsage) -> float:
        generated = usage.output_tokens + usage.thought_tokens
        return round(
            (usage.input_tokens * self._input_rate + generated * self._output_rate) / 1_000_000,
            8,
        )


class AuditedLLMService:
    def __init__(self, provider: LLMProvider, repository: LLMRunRepository) -> None:
        self._provider = provider
        self._repository = repository

    async def generate(
        self,
        *,
        message_id: UUID,
        request: LLMRequest,
        budget: TurnBudget,
        timeout_seconds: float | None = None,
    ) -> LLMResponse:
        budget.reserve(request)
        started = perf_counter()
        try:
            if timeout_seconds is None:
                response = await self._provider.generate(request)
            else:
                async with asyncio.timeout(timeout_seconds):
                    response = await self._provider.generate(request)
        except TimeoutError as exc:
            await self._record(
                LLMRunRecord(
                    message_id=message_id,
                    provider=self._provider.provider_name,
                    model=self._provider.model_name,
                    prompt_version=PROMPT_VERSION,
                    request_kind=request.kind,
                    usage=None,
                    latency_ms=max(0, int((perf_counter() - started) * 1000)),
                    status=LLMRunStatus.TIMED_OUT,
                    error_code=LLMTimeoutError.code,
                )
            )
            raise LLMTimeoutError("LLM request exceeded the application timeout") from exc
        except LLMError as exc:
            await self._record(
                LLMRunRecord(
                    message_id=message_id,
                    provider=self._provider.provider_name,
                    model=self._provider.model_name,
                    prompt_version=PROMPT_VERSION,
                    request_kind=request.kind,
                    usage=None,
                    latency_ms=max(0, int((perf_counter() - started) * 1000)),
                    status=(
                        LLMRunStatus.TIMED_OUT
                        if isinstance(exc, LLMTimeoutError)
                        else LLMRunStatus.FAILED
                    ),
                    error_code=exc.code,
                )
            )
            raise
        cost = budget.estimate_cost(response.usage)
        await self._record(
            LLMRunRecord(
                message_id=message_id,
                provider=self._provider.provider_name,
                model=self._provider.model_name,
                prompt_version=PROMPT_VERSION,
                request_kind=request.kind,
                usage=response.usage,
                latency_ms=max(0, int((perf_counter() - started) * 1000)),
                status=LLMRunStatus.SUCCEEDED,
                estimated_cost_usd=cost,
                provider_request_id=response.provider_request_id,
            )
        )
        return response

    async def _record(self, record: LLMRunRecord) -> None:
        try:
            await self._repository.record_llm_run(record)
        except Exception as exc:
            raise LLMAuditError("LLM run could not be audited") from exc


ACTION_TOOL_BY_INTENT: dict[IntentCode, str] = {
    IntentCode.ROOM_TYPES: "list_room_types",
    IntentCode.ROOM_AVAILABILITY: "check_room_availability",
    IntentCode.BOOKING_LOOKUP: "lookup_booking",
    IntentCode.ROOM_SERVICE_REQUEST: "create_room_service_request",
    IntentCode.MAINTENANCE_REQUEST: "create_maintenance_request",
    IntentCode.SERVICE_REQUEST_STATUS: "get_service_request_status",
}
KNOWLEDGE_QUERY_REWRITE_TRIGGER_SCORE = 0.55
KNOWLEDGE_STRONG_SEMANTIC_SCORE = KNOWLEDGE_QUERY_REWRITE_TRIGGER_SCORE
GENERIC_RETRIEVAL_TERMS = frozenset(
    {
        "hotel",
        "guest",
        "guests",
        "information",
        "service",
        "فندق",
        "الفندق",
        "نزيل",
        "النزيل",
        "النزلاء",
        "معلومات",
        "خدمة",
    }
)

PARAMETER_LABELS = {
    "ar": {
        "check_in": "تاريخ الوصول بصيغة YYYY-MM-DD",
        "check_out": "تاريخ المغادرة بصيغة YYYY-MM-DD",
        "adults": "عدد البالغين",
        "booking_reference": "مرجع الحجز",
        "verification_value": "رمز التحقق",
        "room_number": "رقم الغرفة",
        "category": "نوع الخدمة",
        "description": "وصف الطلب",
        "tracking_code": "رمز تتبع الطلب",
    },
    "en": {
        "check_in": "check-in date (YYYY-MM-DD)",
        "check_out": "check-out date (YYYY-MM-DD)",
        "adults": "number of adults",
        "booking_reference": "booking reference",
        "verification_value": "verification code",
        "room_number": "room number",
        "category": "service category",
        "description": "request description",
        "tracking_code": "request tracking code",
    },
}

CLARIFICATION_QUESTIONS = {
    "ar": {
        (
            "check_in",
            "check_out",
            "adults",
        ): "ما تاريخ الوصول والمغادرة، وكم عدد البالغين؟",
        (
            "check_in",
            "check_out",
        ): "ما تاريخ الوصول والمغادرة؟",
        ("check_in",): "ما تاريخ الوصول؟",
        ("check_out",): "ما تاريخ المغادرة؟",
        ("adults",): "كم عدد البالغين؟",
        (
            "booking_reference",
            "verification_value",
        ): "ما مرجع الحجز ورمز التحقق؟",
        (
            "room_number",
            "category",
            "description",
        ): "ما رقم الغرفة ونوع الخدمة، وما تفاصيل الطلب؟",
        (
            "room_number",
            "description",
        ): "ما رقم الغرفة، وما وصف المشكلة؟",
        ("description",): "ما تفاصيل الطلب المطلوب؟",
        ("category",): "ما نوع الخدمة أو المشكلة؟",
    },
    "en": {
        (
            "check_in",
            "check_out",
            "adults",
        ): "What are the check-in and check-out dates, and how many adults?",
        (
            "check_in",
            "check_out",
        ): "What are the check-in and check-out dates?",
        ("check_in",): "What is the check-in date?",
        ("check_out",): "What is the check-out date?",
        ("adults",): "How many adults will stay?",
        (
            "booking_reference",
            "verification_value",
        ): "What are the booking reference and verification code?",
        (
            "room_number",
            "category",
            "description",
        ): "What are the room number, service category, and request details?",
        (
            "room_number",
            "description",
        ): "What are the room number and problem description?",
        ("description",): "What request details should I include?",
        ("category",): "What type of service or issue is this?",
    },
}

INTENT_PARAMETER_QUESTIONS = {
    "ar": {
        IntentCode.ROOM_AVAILABILITY: {
            "check_in": "ما تاريخ الوصول؟",
            "check_out": "ما تاريخ المغادرة؟",
            "adults": "كم عدد البالغين؟",
        },
        IntentCode.BOOKING_LOOKUP: {
            "booking_reference": "ما مرجع الحجز؟",
            "verification_value": "ما رمز التحقق؟",
        },
        IntentCode.ROOM_SERVICE_REQUEST: {
            "room_number": "ما رقم الغرفة؟",
            "category": (
                "ما نوع الخدمة المطلوبة؟ "
                "مثال: طعام، مشروبات، مناشف، تنظيف."
            ),
            "description": "ما الطلب الذي تريده بالتحديد؟",
        },
        IntentCode.MAINTENANCE_REQUEST: {
            "room_number": "ما رقم الغرفة؟",
            "category": "ما نوع مشكلة الصيانة؟",
            "description": "ما وصف مشكلة الصيانة؟",
        },
        IntentCode.SERVICE_REQUEST_STATUS: {
            "tracking_code": "ما رمز تتبع الطلب؟",
            "verification_value": "ما رمز التحقق؟",
        },
    },
    "en": {
        IntentCode.ROOM_AVAILABILITY: {
            "check_in": "What is the check-in date?",
            "check_out": "What is the check-out date?",
            "adults": "How many adults will stay?",
        },
        IntentCode.BOOKING_LOOKUP: {
            "booking_reference": "What is the booking reference?",
            "verification_value": "What is the verification code?",
        },
        IntentCode.ROOM_SERVICE_REQUEST: {
            "room_number": "What is the room number?",
            "category": (
                "What service do you need? "
                "For example: food, drinks, towels, or cleaning."
            ),
            "description": "What exactly would you like to request?",
        },
        IntentCode.MAINTENANCE_REQUEST: {
            "room_number": "What is the room number?",
            "category": "What type of maintenance issue is this?",
            "description": "Please describe the maintenance issue.",
        },
        IntentCode.SERVICE_REQUEST_STATUS: {
            "tracking_code": "What is the request tracking code?",
            "verification_value": "What is the verification code?",
        },
    },
}


def _meaningful_retrieval_tokens(text: str) -> frozenset[str]:
    return frozenset(
        token
        for token in re.findall(r"[\w\u0600-\u06ff]+", normalize_text(text))
        if len(token) >= 3 and token not in GENERIC_RETRIEVAL_TERMS
    )


def _validate_retrieval_evidence(
    result: RetrievalResult,
    *,
    query: str,
    material_conditions: tuple[str, ...],
) -> RetrievalResult:
    """Reject weak unrelated chunks and rank candidates by generic condition coverage."""

    query_tokens = _meaningful_retrieval_tokens(query)
    condition_tokens = tuple(
        _meaningful_retrieval_tokens(condition)
        for condition in material_conditions
    )
    ranked: list[tuple[int, int, float, RetrievalEvidence]] = []
    for evidence in result.evidence:
        evidence_tokens = _meaningful_retrieval_tokens(
            f"{evidence.title}\n{evidence.text}"
        )
        lexical_overlap = len(query_tokens & evidence_tokens)
        condition_coverage = sum(
            bool(tokens & evidence_tokens)
            for tokens in condition_tokens
            if tokens
        )
        if (
            evidence.score < KNOWLEDGE_STRONG_SEMANTIC_SCORE
            and lexical_overlap == 0
            and condition_coverage == 0
        ):
            continue
        ranked.append(
            (
                condition_coverage,
                lexical_overlap,
                evidence.score,
                evidence,
            )
        )
    ranked.sort(
        key=lambda item: (item[0], item[1], item[2]),
        reverse=True,
    )
    validated_evidence = tuple(
        item[3].model_copy(update={"rank": rank})
        for rank, item in enumerate(ranked, start=1)
    )
    return result.model_copy(
        update={
            "evidence": validated_evidence,
            "sufficient": bool(validated_evidence),
            "reason_code": (
                "evidence_found"
                if validated_evidence
                else "evidence_relevance_rejected"
            ),
        }
    )


class HybridOrchestrator:
    """Routes deterministic, RAG, and tool flows while keeping Gemini non-authoritative."""

    def __init__(
        self,
        *,
        llm: AuditedLLMService,
        retrieval: KnowledgeRetrievalService,
        registry: ToolRegistry,
        tool_executor: ControlledToolExecutor,
        prompt_factory: PromptFactory,
        max_tokens_per_turn: int,
        max_cost_usd_per_turn: float,
        input_usd_per_million: float,
        output_usd_per_million: float,
    ) -> None:
        self._llm = llm
        self._retrieval = retrieval
        self._registry = registry
        self._tool_executor = tool_executor
        self._prompts = prompt_factory
        self._max_tokens_per_turn = max_tokens_per_turn
        self._max_cost_usd_per_turn = max_cost_usd_per_turn
        self._input_usd_per_million = input_usd_per_million
        self._output_usd_per_million = output_usd_per_million

    async def handle(
        self,
        context: ContextEnvelope,
        routing: RoutingResult,
        *,
        confirmed: bool = False,
        trusted_tool_arguments: Mapping[str, object] | None = None,
    ) -> OrchestrationResult:
        budget = TurnBudget(
            max_tokens=self._max_tokens_per_turn,
            max_cost_usd=self._max_cost_usd_per_turn,
            input_usd_per_million=self._input_usd_per_million,
            output_usd_per_million=self._output_usd_per_million,
        )
        if routing.decision is RoutingDecision.KNOWLEDGE_CANDIDATE:
            return await self._knowledge(context, routing, budget)
        if routing.decision is RoutingDecision.ACTION_CANDIDATE:
            return await self._action(
                context,
                routing,
                confirmed,
                budget,
                trusted_tool_arguments=trusted_tool_arguments,
            )
        return self._controlled(context, routing)

    async def _knowledge(
        self,
        context: ContextEnvelope,
        routing: RoutingResult,
        budget: TurnBudget,
    ) -> OrchestrationResult:
        search_query = (
            "\n".join(
                (
                    routing.normalized_knowledge_query,
                    *routing.material_conditions,
                )
            )
            if routing.normalized_knowledge_query
            else context.current_message.text
        )
        material_conditions = routing.material_conditions
        try:
            result = await self._retrieval.retrieve(search_query)
        except Exception:
            return self._unavailable(context, "knowledge_retrieval_failed")
        strongest_score = result.evidence[0].score if result.evidence else -1.0
        if (
            routing.normalized_knowledge_query is None
            and strongest_score < KNOWLEDGE_QUERY_REWRITE_TRIGGER_SCORE
        ):
            try:
                rewrite_response = await self._llm.generate(
                    message_id=context.current_message.id,
                    request=self._prompts.knowledge_search_query(context),
                    budget=budget,
                )
                if not rewrite_response.text:
                    raise LLMContractError("model returned no knowledge search query")
                rewritten = KnowledgeSearchQuery.model_validate_json(
                    rewrite_response.text
                )
                if rewritten.language != context.current_message.language:
                    raise LLMContractError(
                        "model changed the knowledge search query language"
                    )
                semantic_query = "\n".join(
                    (
                        rewritten.query,
                        *rewritten.material_conditions,
                    )
                )
                rewritten_result = await self._retrieval.retrieve(
                    semantic_query
                )
                if rewritten_result.sufficient:
                    result = rewritten_result
                    search_query = semantic_query
                    material_conditions = rewritten.material_conditions
            except (LLMError, ValidationError, ValueError):
                pass
        result = _validate_retrieval_evidence(
            result,
            query=search_query,
            material_conditions=material_conditions,
        )
        if not result.sufficient:
            return self._unavailable(context, result.reason_code)
        evidence_ids = tuple(str(item.chunk_id) for item in result.evidence)
        grounded_context = context.model_copy(
            update={
                "evidence": tuple(
                    f"[{item.chunk_id}] {item.title}\n{item.text}" for item in result.evidence
                )
            }
        )
        request = self._prompts.final_answer(
            grounded_context,
            basis=AnswerBasis.KNOWLEDGE,
            grounding_payload={"retrieval_reason": result.reason_code},
            allowed_evidence_ids=evidence_ids,
        )
        try:
            answer = await self._generate_answer(
                context.current_message.id,
                request,
                budget,
                expected_basis=AnswerBasis.KNOWLEDGE,
                evidence_ids=evidence_ids,
            )
            return OrchestrationResult(
                answer=answer,
                model_used=True,
                reason_code="grounded_knowledge_answer",
            )
        except (LLMError, ValidationError, ValueError):
            first = result.evidence[0]
            return OrchestrationResult(
                answer=GroundedAnswer(
                    language=context.state.language,
                    text=first.text,
                    basis=AnswerBasis.KNOWLEDGE,
                    evidence_ids=(str(first.chunk_id),),
                ),
                reason_code="knowledge_model_fallback",
            )

    async def _action(
        self,
        context: ContextEnvelope,
        routing: RoutingResult,
        confirmed: bool,
        budget: TurnBudget,
        *,
        trusted_tool_arguments: Mapping[str, object] | None,
    ) -> OrchestrationResult:
        tool_name = ACTION_TOOL_BY_INTENT.get(routing.prediction.intent)
        if tool_name is None:
            return self._unavailable(context, "action_tool_unmapped")
        if routing.requires_confirmation and not confirmed:
            text = (
                "يرجى تأكيد تنفيذ الطلب قبل إنشائه."
                if context.state.language == "ar"
                else "Please confirm before I create this request."
            )
            return OrchestrationResult(
                answer=GroundedAnswer(
                    language=context.state.language,
                    text=text,
                    basis=AnswerBasis.CONTROLLED,
                ),
                reason_code="confirmation_required",
            )
        definition = self._registry.resolve(tool_name)
        if definition is None:
            return self._unavailable(context, "action_tool_unavailable")
        if trusted_tool_arguments is not None:
            execution_name = tool_name
            execution_arguments = dict(trusted_tool_arguments)
        else:
            proposal_request = self._prompts.tool_proposal(
                context, (definition.definition.declaration(),)
            )
            try:
                proposal = await self._llm.generate(
                    message_id=context.current_message.id,
                    request=proposal_request,
                    budget=budget,
                )
            except LLMError:
                return self._unavailable(context, "tool_proposal_model_unavailable")
            if len(proposal.tool_calls) != 1:
                return self._unavailable(
                    context,
                    "invalid_tool_proposal_count",
                    model_used=True,
                )
            proposed = proposal.tool_calls[0]
            execution_name = proposed.name
            execution_arguments = proposed.arguments

        execution = await self._tool_executor.execute(
            ToolCall(name=execution_name, arguments=execution_arguments),
            ToolExecutionContext(
                message_id=context.current_message.id,
                correlation_id=context.current_message.correlation_id,
                caller=ToolCaller.ASSISTANT,
                confirmed=confirmed,
                call_index=1,
                allowed_tool_names=frozenset({tool_name}),
            ),
        )
        if execution.status is not ToolExecutionStatus.SUCCEEDED or execution.output is None:
            return self._tool_failure(context, execution)
        output_payload = execution.output.model_dump(mode="json")
        final_request = self._prompts.final_answer(
            context,
            basis=AnswerBasis.TOOL,
            grounding_payload={
                "tool_name": execution.tool_name,
                "validated_result": output_payload,
            },
            allowed_tool_names=(execution.tool_name,),
        )
        try:
            answer = await self._generate_answer(
                context.current_message.id,
                final_request,
                budget,
                expected_basis=AnswerBasis.TOOL,
                tool_names=(execution.tool_name,),
            )
            return OrchestrationResult(
                answer=answer,
                tool_executed=True,
                model_used=True,
                reason_code="validated_tool_answer",
            )
        except (LLMError, ValidationError, ValueError):
            return OrchestrationResult(
                answer=GroundedAnswer(
                    language=context.state.language,
                    text=self._tool_fallback_text(context, execution),
                    basis=AnswerBasis.TOOL,
                    tool_names=(execution.tool_name,),
                ),
                tool_executed=True,
                model_used=True,
                reason_code="tool_result_model_fallback",
            )

    async def _generate_answer(
        self,
        message_id: UUID,
        request: LLMRequest,
        budget: TurnBudget,
        *,
        expected_basis: AnswerBasis,
        evidence_ids: tuple[str, ...] = (),
        tool_names: tuple[str, ...] = (),
    ) -> GroundedAnswer:
        response = await self._llm.generate(message_id=message_id, request=request, budget=budget)
        if not response.text:
            raise LLMContractError("model returned no structured answer")
        try:
            answer = GroundedAnswer.model_validate_json(response.text)
        except ValidationError as exc:
            raise LLMContractError("structured answer validation failed") from exc
        if answer.basis is not expected_basis:
            raise LLMContractError("model changed the required answer basis")
        if not set(answer.evidence_ids) <= set(evidence_ids):
            raise LLMContractError("model cited evidence outside the allow-list")
        if not set(answer.tool_names) <= set(tool_names):
            raise LLMContractError("model cited tools outside the allow-list")
        return answer

    def _controlled(self, context: ContextEnvelope, routing: RoutingResult) -> OrchestrationResult:
        language = context.state.language
        if routing.decision is RoutingDecision.CLARIFY:
            if routing.clarification_question is not None:
                text = routing.clarification_question
            else:
                labels = PARAMETER_LABELS[language]
                all_missing_parameters = (
                    routing.missing_parameters
                    or INTENT_DEFINITIONS[routing.prediction.intent].required_parameters
                )
                missing_parameters = all_missing_parameters[:1]
                if missing_parameters:
                    candidate_text = INTENT_PARAMETER_QUESTIONS[language].get(
                        routing.prediction.intent,
                        {},
                    ).get(
                        missing_parameters[0]
                    )
                    if candidate_text is None:
                        candidate_text = CLARIFICATION_QUESTIONS[language].get(
                            missing_parameters
                        )
                    if candidate_text is None:
                        missing = labels.get(
                            missing_parameters[0],
                            missing_parameters[0],
                        )
                        candidate_text = (
                            f"ما {missing}؟"
                            if language == "ar"
                            else f"Please provide {missing}."
                        )
                    text = candidate_text
                else:
                    text = (
                        "هل يمكنك توضيح طلبك بمزيد من التفاصيل؟"
                        if language == "ar"
                        else "Could you clarify your request with a few more details?"
                    )
            reason = "clarification_required"
        elif routing.decision is RoutingDecision.ESCALATE:
            text = (
                "سأحوّل طلبك إلى موظف خدمة العملاء."
                if language == "ar"
                else "I will escalate this to a customer-support agent."
            )
            reason = "human_escalation"
        elif routing.decision is RoutingDecision.CONTROLLED_RESPONSE:
            text = (
                "أهلاً بك في فندق نور الشام. كيف يمكنني مساعدتك؟"
                if language == "ar"
                else "Welcome to Nour Al-Sham Hotel. How may I help?"
            )
            reason = "controlled_response"
        else:
            return self._unavailable(context, routing.reason_code)
        return OrchestrationResult(
            answer=GroundedAnswer(language=language, text=text, basis=AnswerBasis.CONTROLLED),
            reason_code=reason,
        )

    def _unavailable(
        self, context: ContextEnvelope, reason: str, *, model_used: bool = False
    ) -> OrchestrationResult:
        text = (
            "لا أملك معلومات موثوقة كافية للإجابة الآن. يمكنني تحويلك إلى موظف خدمة العملاء."
            if context.state.language == "ar"
            else (
                "I do not have enough reliable information to answer now. "
                "I can escalate this to support."
            )
        )
        return OrchestrationResult(
            answer=GroundedAnswer(
                language=context.state.language,
                text=text,
                basis=AnswerBasis.UNAVAILABLE,
                uncertainty=True,
                escalation=True,
            ),
            model_used=model_used,
            reason_code=reason,
        )

    def _tool_failure(
        self, context: ContextEnvelope, execution: ToolExecutionResult
    ) -> OrchestrationResult:
        messages = {
            "ar": {
                "check_in_in_past": (
                    "تاريخ الوصول يجب أن يكون اليوم أو لاحقاً. ما تاريخ الوصول الجديد؟"
                ),
                "check_in_too_far": (
                    "تاريخ الوصول بعيد أكثر من المدة المسموحة. ما تاريخ الوصول الجديد؟"
                ),
                "invalid_date_range": (
                    "تاريخ المغادرة يجب أن يكون بعد تاريخ الوصول. ما تاريخ المغادرة الجديد؟"
                ),
                "stay_too_long": ("مدة الإقامة تتجاوز الحد المسموح. ما تاريخ المغادرة الجديد؟"),
                "adults_required": "يجب أن تضم الإقامة بالغاً واحداً على الأقل. كم عدد البالغين؟",
                "booking_not_found_or_verification_failed": (
                    "تعذر التحقق من الحجز. تأكد من رمز التحقق وحاول مرة أخرى."
                ),
            },
            "en": {
                "check_in_in_past": (
                    "The arrival date must be today or later. What is the new arrival date?"
                ),
                "check_in_too_far": (
                    "The arrival date is beyond the allowed booking window. "
                    "What is the new arrival date?"
                ),
                "invalid_date_range": (
                    "The departure date must be after arrival. What is the new departure date?"
                ),
                "stay_too_long": (
                    "The stay exceeds the allowed length. What is the new departure date?"
                ),
                "adults_required": ("At least one adult is required. How many adults will stay?"),
                "booking_not_found_or_verification_failed": (
                    "The booking could not be verified. Check the verification code and try again."
                ),
            },
        }
        fallback = (
            "لم تُنفذ العملية. تحقق من البيانات أو حاول لاحقاً."
            if context.state.language == "ar"
            else "The operation was not executed. Check the details or try again later."
        )
        text = messages[context.state.language].get(
            execution.error_code or "",
            fallback,
        )
        return OrchestrationResult(
            answer=GroundedAnswer(
                language=context.state.language,
                text=text,
                basis=AnswerBasis.UNAVAILABLE,
                uncertainty=True,
            ),
            model_used=True,
            reason_code=execution.error_code or "tool_execution_failed",
        )

    @staticmethod
    def _tool_fallback_text(context: ContextEnvelope, execution: ToolExecutionResult) -> str:
        payload = execution.output.model_dump(mode="json") if execution.output else {}
        language = context.state.language
        if execution.tool_name == "check_room_availability":
            options = payload.get("options") or []
            if not options:
                return (
                    "لا توجد غرف متاحة وفق البيانات المدخلة. جرّب تواريخ أو فئة غرفة أخرى."
                    if language == "ar"
                    else (
                        "No rooms are available for those details. "
                        "Try different dates or another room type."
                    )
                )
            option = options[0]
            name = option.get("name_ar") if language == "ar" else option.get("name_en")
            amenities = tuple(option.get("amenities") or ())[:2]
            amenities_text = "، ".join(str(item) for item in amenities)
            capacity = int(option.get("capacity_adults", 0)) + int(
                option.get("capacity_children", 0)
            )
            available = option.get("available_rooms", 0)
            if language == "ar":
                amenity_clause = f"، وأبرز المزايا: {amenities_text}" if amenities_text else ""
                return (
                    f"متاح {name} بسعة {capacity} نزلاء ({available} غرف متوفرة)"
                    f"{amenity_clause}. أخبرني إذا أردت متابعة الحجز."
                )
            amenity_clause = f"; key amenities: {amenities_text}" if amenities_text else ""
            return (
                f"{name} is available for up to {capacity} guests "
                f"({available} rooms available){amenity_clause}. "
                "Tell me if you want to continue with a booking."
            )
        if execution.tool_name in {
            "create_room_service_request",
            "create_maintenance_request",
        }:
            tracking_code = payload.get("tracking_code", "")
            return (
                f"تم إنشاء الطلب بنجاح. رمز التتبع: {tracking_code}."
                if language == "ar"
                else f"The request was created. Tracking code: {tracking_code}."
            )
        if execution.tool_name == "get_service_request_status":
            tracking_code = payload.get("tracking_code", "")
            status = payload.get("status", "")
            return (
                f"حالة الطلب {tracking_code}: {status}."
                if language == "ar"
                else f"Request {tracking_code} is {status}."
            )
        if execution.tool_name == "lookup_booking":
            reference = payload.get("reference", "")
            status = payload.get("status", "")
            check_in = payload.get("check_in", "")
            check_out = payload.get("check_out", "")
            return (
                f"حالة الحجز {reference}: {status}، من {check_in} إلى {check_out}."
                if language == "ar"
                else f"Booking {reference} is {status}, from {check_in} to {check_out}."
            )
        if execution.tool_name == "list_room_types":
            room_types = payload.get("room_types") or []
            names = [
                str(item.get("name_ar") if language == "ar" else item.get("name_en"))
                for item in room_types[:3]
            ]
            rendered_names = "، ".join(names)
            return (
                f"فئات الغرف المتاحة: {rendered_names}."
                if language == "ar"
                else f"Available room types: {rendered_names}."
            )
        return "تم تنفيذ العملية بنجاح." if language == "ar" else "The operation succeeded."
