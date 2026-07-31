"""Typed intent dataset, prediction, routing, and evaluation contracts."""

from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from hotel_bot.domain.intent.enums import (
    DatasetSplit,
    IntentCode,
    PredictionSource,
    RoutingDecision,
)

SupportedLanguage = Literal["ar", "en"]


class IntentSample(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str = Field(min_length=3, max_length=128)
    scenario_id: str = Field(min_length=3, max_length=128)
    split: DatasetSplit
    language: SupportedLanguage
    text: str = Field(min_length=2, max_length=1000)
    intent: IntentCode


class IntentDataset(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    dataset_version: str
    taxonomy_version: str
    description: str
    samples: tuple[IntentSample, ...]


class IntentPrediction(BaseModel):
    model_config = ConfigDict(frozen=True)

    intent: IntentCode
    confidence: float = Field(ge=0, le=1)
    margin: float = Field(ge=0, le=1)
    classifier_version: str
    scores: dict[IntentCode, float]
    source: PredictionSource = PredictionSource.CLASSIFIER


class RoutingResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    prediction: IntentPrediction
    decision: RoutingDecision
    missing_parameters: tuple[str, ...] = ()
    requires_confirmation: bool = False
    allow_tool_execution: bool = False
    reason_code: str
    clarification_question: str | None = Field(default=None, min_length=2, max_length=500)
    normalized_knowledge_query: str | None = Field(default=None, min_length=2, max_length=1000)
    material_conditions: tuple[str, ...] = Field(default=(), max_length=12)


class IntentMetric(BaseModel):
    model_config = ConfigDict(frozen=True)

    precision: float
    recall: float
    f1: float
    support: int


class IntentEvaluationReport(BaseModel):
    model_config = ConfigDict(frozen=True)

    report_version: str
    dataset_version: str
    dataset_sha256: str
    taxonomy_version: str
    classifier_version: str
    split: DatasetSplit
    sample_count: int
    accuracy: float
    macro_precision: float
    macro_recall: float
    macro_f1: float
    confidence_threshold: float
    confidence_margin_threshold: float
    accepted_count: int
    coverage: float
    accepted_accuracy: float
    per_intent: dict[IntentCode, IntentMetric]
    confusion_matrix: dict[IntentCode, dict[IntentCode, int]]


class StoredClassification(BaseModel):
    model_config = ConfigDict(frozen=True)

    message_id: UUID
    intent: IntentCode
    confidence: float
    classifier_version: str
