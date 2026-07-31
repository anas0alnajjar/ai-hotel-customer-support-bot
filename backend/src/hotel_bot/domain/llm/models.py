"""Immutable provider-neutral model requests, responses, and audit records."""

from collections.abc import Mapping
from datetime import date
from typing import Any, Literal, Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from hotel_bot.domain.intent.enums import IntentCode
from hotel_bot.domain.intent.taxonomy import ACTION_INTENTS
from hotel_bot.domain.llm.enums import AnswerBasis, LLMRequestKind, LLMRunStatus

SupportedLanguage = Literal["ar", "en"]
HybridRouteMode = Literal["action", "knowledge", "ambiguous", "unsupported"]
HybridMissingField = Literal[
    "check_in",
    "check_out",
    "adults",
    "children",
    "room_type_code",
    "booking_reference",
    "verification_value",
    "room_number",
    "category",
    "description",
    "tracking_code",
]


class LLMUsage(BaseModel):
    model_config = ConfigDict(frozen=True)

    input_tokens: int = Field(default=0, ge=0)
    output_tokens: int = Field(default=0, ge=0)
    thought_tokens: int = Field(default=0, ge=0)
    total_tokens: int = Field(default=0, ge=0)


class ProposedToolCall(BaseModel):
    model_config = ConfigDict(frozen=True)

    call_id: str = Field(min_length=1, max_length=128)
    name: str = Field(min_length=3, max_length=64)
    arguments: dict[str, Any]


class LLMRequest(BaseModel):
    model_config = ConfigDict(frozen=True)

    kind: LLMRequestKind
    system_instruction: str = Field(min_length=20, max_length=12_000)
    prompt: str = Field(min_length=1, max_length=50_000)
    tools: tuple[dict[str, object], ...] = ()
    response_schema: dict[str, Any] | None = None
    max_output_tokens: int = Field(ge=64, le=8192)
    estimated_input_tokens: int = Field(ge=1, le=100_000)


class LLMResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    text: str | None = None
    tool_calls: tuple[ProposedToolCall, ...] = ()
    usage: LLMUsage
    provider_request_id: str | None = Field(default=None, max_length=128)
    finish_reason: str | None = Field(default=None, max_length=64)


class GroundedAnswer(BaseModel):
    """Schema returned by Gemini and revalidated by the application."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    language: SupportedLanguage
    text: str = Field(min_length=1, max_length=2400)
    basis: AnswerBasis
    evidence_ids: tuple[str, ...] = Field(default=(), max_length=8)
    tool_names: tuple[str, ...] = Field(default=(), max_length=3)
    uncertainty: bool = False
    escalation: bool = False

    @model_validator(mode="after")
    def validate_grounding_claims(self) -> Self:
        if self.basis is AnswerBasis.KNOWLEDGE and not self.evidence_ids:
            raise ValueError("knowledge answers require evidence identifiers")
        if self.basis is AnswerBasis.TOOL and not self.tool_names:
            raise ValueError("tool answers require tool names")
        if self.basis is AnswerBasis.UNAVAILABLE and not self.uncertainty:
            raise ValueError("unavailable answers must disclose uncertainty")
        return self


class KnowledgeSearchQuery(BaseModel):
    """A fact-preserving standalone query used only for semantic retrieval."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    language: SupportedLanguage
    query: str = Field(min_length=2, max_length=1000)
    material_conditions: tuple[str, ...] = Field(
        min_length=1,
        max_length=12,
    )


class HybridIntentEntities(BaseModel):
    """Allow-listed, non-sensitive values the advisory analyzer may extract."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    room_number: str | None = Field(
        default=None,
        min_length=1,
        max_length=16,
        pattern=r"^[A-Za-z0-9-]+$",
    )
    check_in: date | None = None
    check_out: date | None = None
    adults: int | None = Field(default=None, ge=1, le=20)
    children: int | None = Field(default=None, ge=0, le=20)
    room_type_code: str | None = Field(
        default=None,
        min_length=1,
        max_length=32,
        pattern=r"^[A-Za-z0-9_-]+$",
    )
    category: str | None = Field(
        default=None,
        min_length=1,
        max_length=64,
        pattern=r"^[a-z][a-z0-9_]*$",
    )
    service_description: str | None = Field(default=None, min_length=2, max_length=1000)


class HybridIntentDecision(BaseModel):
    """Strict advisory intent contract; it contains no tool or authorization fields."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    mode: HybridRouteMode
    intent: IntentCode | None = None
    confidence: float = Field(ge=0, le=1)
    language: SupportedLanguage
    entities: HybridIntentEntities = Field(default_factory=HybridIntentEntities)
    missing_fields: tuple[HybridMissingField, ...] = Field(default=(), max_length=12)
    needs_clarification: bool = False
    clarification_question: str | None = Field(default=None, min_length=2, max_length=500)
    normalized_knowledge_query: str | None = Field(default=None, min_length=2, max_length=1000)
    material_conditions: tuple[str, ...] = Field(default=(), max_length=12)

    @model_validator(mode="after")
    def validate_advisory_policy(self) -> Self:
        if self.mode == "action":
            if self.intent not in ACTION_INTENTS:
                raise ValueError("action mode requires an existing action intent")
            if self.needs_clarification and self.clarification_question is None:
                raise ValueError("clarification text is required when clarification is requested")
        elif self.mode == "knowledge":
            if self.intent not in {None, IntentCode.HOTEL_INFO}:
                raise ValueError("knowledge mode may select only hotel_info")
            if self.needs_clarification:
                raise ValueError("knowledge mode cannot request clarification")
        elif self.mode == "ambiguous":
            if self.intent is not None:
                raise ValueError("ambiguous mode cannot select an intent")
            if not self.needs_clarification or self.clarification_question is None:
                raise ValueError("ambiguous mode requires a focused clarification")
        else:
            if self.intent not in {None, IntentCode.UNSUPPORTED}:
                raise ValueError("unsupported mode cannot select an executable intent")
            if self.needs_clarification:
                raise ValueError("unsupported mode cannot request clarification")
        return self


class LLMRunRecord(BaseModel):
    model_config = ConfigDict(frozen=True)

    message_id: UUID
    provider: str = Field(min_length=1, max_length=64)
    model: str = Field(min_length=1, max_length=128)
    prompt_version: str = Field(min_length=1, max_length=64)
    request_kind: LLMRequestKind
    usage: LLMUsage | None
    latency_ms: int = Field(ge=0)
    status: LLMRunStatus
    error_code: str | None = Field(default=None, max_length=64)
    estimated_cost_usd: float | None = Field(default=None, ge=0)
    provider_request_id: str | None = Field(default=None, max_length=128)


class OrchestrationResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    answer: GroundedAnswer
    tool_executed: bool = False
    model_used: bool = False
    reason_code: str


def immutable_mapping(value: Mapping[str, Any]) -> dict[str, Any]:
    """Copy a provider payload before validation crosses the domain boundary."""

    return dict(value)
