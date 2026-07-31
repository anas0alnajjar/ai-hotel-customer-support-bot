"""Offline evaluation identity and metric-semantics regression tests."""

import asyncio
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from hotel_bot.application.evaluation import OfflineEvaluationService
from hotel_bot.application.intent_routing import HYBRID_ROUTER_VERSION
from hotel_bot.domain.admin.models import AdminPrincipal, EvaluationAdminItem
from hotel_bot.persistence.enums import AdminRole, EvaluationStatus


class EvaluationRepositoryStub:
    def __init__(self) -> None:
        self.system_versions: dict[str, Any] | None = None
        self.metrics: dict[str, Any] | None = None

    async def operational_evaluation_metrics(self) -> dict[str, Any]:
        return {
            "answer_quality": {
                "evaluator_label_counts": {},
                "evaluator_sample_count": 0,
                "average_evaluator_rating": None,
                "ground_truth_policy": "evaluator_labels_are_distinct_from_guest_feedback",
            },
            "llm_reliability": {
                "status_counts": {"succeeded": 4},
                "sample_count": 4,
                "success_rate": 1.0,
            },
            "tool_execution": {
                "status_counts": {"succeeded": 8, "rejected": 6},
                "expected_rejection_error_counts": {"verification_failed": 6},
                "sample_count": 14,
                "valid_tool_requests_succeeded": 8,
                "expected_requests_rejected": 6,
                "unexpected_execution_failures": 0,
                "valid_request_success_rate": 1.0,
            },
        }

    async def create_evaluation(
        self,
        *,
        dataset_version: str,
        system_versions: dict[str, Any],
        metrics: dict[str, Any],
        principal: AdminPrincipal,
        correlation_id: str,
    ) -> EvaluationAdminItem:
        del principal, correlation_id
        self.system_versions = system_versions
        self.metrics = metrics
        now = datetime.now(UTC)
        return EvaluationAdminItem(
            id=uuid4(),
            dataset_version=dataset_version,
            system_versions=system_versions,
            metrics=metrics,
            status=EvaluationStatus.COMPLETED,
            started_at=now,
            finished_at=now,
            error_summary=None,
            created_at=now,
        )


def test_offline_run_records_frozen_identity_without_claiming_production(monkeypatch: Any) -> None:
    monkeypatch.setenv("APP_GIT_COMMIT", "offline-test-commit")
    repository = EvaluationRepositoryStub()
    backend_root = Path(__file__).resolve().parents[3]
    principal = AdminPrincipal(
        id=uuid4(),
        email="evaluator@example.invalid",
        username="offline_evaluator",
        role=AdminRole.EVALUATOR,
    )

    result = asyncio.run(
        OfflineEvaluationService(repository, backend_root=backend_root).run(
            dataset_version="hotel-support-baseline-v1",
            principal=principal,
            correlation_id="offline-evaluation-test",
            app_version="0.1.0",
            llm_model="gemini-2.5-flash",
        )
    )

    versions = result.system_versions
    assert versions["run_mode"] == "offline"
    assert versions["baseline_type"] == "frozen_baseline"
    assert versions["git_commit"] == "offline-test-commit"
    assert versions["router"] == HYBRID_ROUTER_VERSION
    assert versions["llm_called"] is False
    assert versions["intent_sample_count"] == 80
    assert versions["retrieval_sample_count"] == 44
    assert versions["evaluator_sample_count"] == 0
    assert versions["embedding_model"] == "hashing-test-v1:384"
    assert result.metrics is not None
    assert result.metrics["tool_execution"]["expected_requests_rejected"] == 6
    assert result.metrics["tool_execution"]["unexpected_execution_failures"] == 0
