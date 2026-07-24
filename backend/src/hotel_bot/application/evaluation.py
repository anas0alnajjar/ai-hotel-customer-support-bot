"""Versioned offline and operational evaluation aggregation."""

import hashlib
import json
from pathlib import Path
from typing import Any, Protocol

from hotel_bot.domain.admin.errors import AdminValidationError
from hotel_bot.domain.admin.models import AdminPrincipal, EvaluationAdminItem

BASELINE_DATASET_VERSION = "hotel-support-baseline-v1"


class EvaluationRepository(Protocol):
    async def operational_evaluation_metrics(self) -> dict[str, Any]: ...

    async def create_evaluation(
        self,
        *,
        dataset_version: str,
        system_versions: dict[str, Any],
        metrics: dict[str, Any],
        principal: AdminPrincipal,
        correlation_id: str,
    ) -> EvaluationAdminItem: ...


class OfflineEvaluationService:
    def __init__(self, repository: EvaluationRepository, *, backend_root: Path) -> None:
        self._repository = repository
        self._backend_root = backend_root.resolve()

    async def run(
        self,
        *,
        dataset_version: str,
        principal: AdminPrincipal,
        correlation_id: str,
        app_version: str,
        llm_model: str,
    ) -> EvaluationAdminItem:
        if dataset_version != BASELINE_DATASET_VERSION:
            raise AdminValidationError(
                "unsupported_evaluation_dataset",
                f"dataset_version must be {BASELINE_DATASET_VERSION}",
            )
        intent_path = self._backend_root / "artifacts/evaluation/intent-evaluation-v1.json"
        retrieval_path = self._backend_root / "reports/knowledge-retrieval-v1.json"
        intent, intent_sha = self._load_artifact(intent_path)
        retrieval, retrieval_sha = self._load_artifact(retrieval_path)
        operational = await self._repository.operational_evaluation_metrics()
        metrics: dict[str, Any] = {
            "intent": {
                "sample_count": intent.get("sample_count"),
                "accuracy": intent.get("accuracy"),
                "macro_f1": intent.get("macro_f1"),
                "coverage": intent.get("coverage"),
                "report_sha256": intent_sha,
            },
            "retrieval": {
                "sample_count": retrieval.get("sample_count"),
                "recall_at_k": retrieval.get("recall_at_k"),
                "top_1_accuracy": retrieval.get("top_1_accuracy"),
                "mean_reciprocal_rank": retrieval.get("mean_reciprocal_rank"),
                "traceability_rate": retrieval.get("traceability_rate"),
                "report_sha256": retrieval_sha,
            },
            **operational,
        }
        system_versions = {
            "application": app_version,
            "intent_classifier": intent.get("classifier_version"),
            "intent_report": intent.get("report_version"),
            "retrieval_dataset": retrieval.get("dataset_version"),
            "embedding_model": retrieval.get("embedding_model"),
            "llm_model": llm_model,
        }
        return await self._repository.create_evaluation(
            dataset_version=dataset_version,
            system_versions=system_versions,
            metrics=metrics,
            principal=principal,
            correlation_id=correlation_id,
        )

    @staticmethod
    def _load_artifact(path: Path) -> tuple[dict[str, Any], str]:
        try:
            payload = path.read_bytes()
            if not payload or len(payload) > 2_000_000:
                raise ValueError("evaluation artifact size is invalid")
            value = json.loads(payload)
            if not isinstance(value, dict):
                raise ValueError("evaluation artifact must be an object")
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            raise AdminValidationError(
                "evaluation_artifact_unavailable", "versioned evaluation artifact is unavailable"
            ) from exc
        return value, hashlib.sha256(payload).hexdigest()
