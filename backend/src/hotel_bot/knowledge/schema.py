"""Validated contracts for the frozen hotel knowledge and retrieval benchmark."""

from typing import Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from hotel_bot.domain.knowledge.enums import SourceFormat
from hotel_bot.domain.knowledge.models import SupportedLanguage


class KnowledgeSeedDocument(BaseModel):
    model_config = ConfigDict(frozen=True)

    key: str = Field(pattern=r"^[a-z0-9_]+$")
    title: str = Field(min_length=3, max_length=255)
    language: SupportedLanguage
    source_format: SourceFormat = SourceFormat.PLAIN_TEXT
    content: str = Field(min_length=20, max_length=200_000)


class RetrievalEvaluationCase(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: str = Field(pattern=r"^[a-z0-9_]+$")
    language: SupportedLanguage
    query: str = Field(min_length=2, max_length=500)
    relevant_document_keys: tuple[str, ...] = Field(min_length=1)


class KnowledgeDataset(BaseModel):
    model_config = ConfigDict(frozen=True)

    dataset_version: str
    hotel_code: str
    documents: tuple[KnowledgeSeedDocument, ...] = Field(min_length=1)
    evaluation_cases: tuple[RetrievalEvaluationCase, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_cross_references(self) -> Self:
        document_keys = [item.key for item in self.documents]
        case_ids = [item.id for item in self.evaluation_cases]
        if len(document_keys) != len(set(document_keys)):
            raise ValueError("knowledge document keys must be unique")
        if len(case_ids) != len(set(case_ids)):
            raise ValueError("retrieval evaluation case ids must be unique")
        by_key = {item.key: item for item in self.documents}
        for case in self.evaluation_cases:
            for key in case.relevant_document_keys:
                document = by_key.get(key)
                if document is None:
                    raise ValueError(f"evaluation case {case.id} references unknown document {key}")
                if document.language != case.language:
                    raise ValueError(f"evaluation case {case.id} crosses document languages")
        return self


class RetrievalEvaluationReport(BaseModel):
    model_config = ConfigDict(frozen=True)

    dataset_version: str
    dataset_sha256: str
    embedding_model: str
    sample_count: int
    top_k: int
    recall_at_k: float
    top_1_accuracy: float
    mean_reciprocal_rank: float
    traceability_rate: float
    passed: bool
    failed_case_ids: tuple[str, ...]
