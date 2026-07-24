"""Health endpoint contract tests."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Protocol

import pytest
from fastapi import FastAPI, status
from fastapi.testclient import TestClient

from hotel_bot.dependencies import get_admin_runtime, get_database_manager


class Pingable(Protocol):
    async def ping(self) -> bool: ...


class FakeDatabase:
    def __init__(self, ready: bool) -> None:
        self.ready = ready

    async def ping(self) -> bool:
        return self.ready

    @asynccontextmanager
    async def session(self) -> AsyncIterator[object]:
        yield object()


class FakeAdminRuntime:
    async def active_index_status(self, session: object) -> str:
        return "ok"


def test_liveness_does_not_require_database(client: TestClient) -> None:
    response = client.get("/api/v1/health/live")

    assert response.status_code == status.HTTP_200_OK
    assert response.json()["status"] == "ok"
    assert response.json()["checks"] == {"application": "ok"}
    assert response.headers["X-Correlation-ID"]


@pytest.mark.parametrize(
    ("database_ready", "expected_status", "expected_body_status"),
    [
        (True, status.HTTP_200_OK, "degraded"),
        (False, status.HTTP_503_SERVICE_UNAVAILABLE, "not_ready"),
    ],
)
def test_readiness_reflects_database_state(
    app: FastAPI,
    database_ready: bool,
    expected_status: int,
    expected_body_status: str,
) -> None:
    app.dependency_overrides[get_database_manager] = lambda: FakeDatabase(database_ready)
    app.dependency_overrides[get_admin_runtime] = lambda: FakeAdminRuntime()

    with TestClient(app) as client:
        response = client.get("/api/v1/health/ready")

    assert response.status_code == expected_status
    assert response.json()["status"] == expected_body_status
    if database_ready:
        assert response.json()["checks"] == {
            "database": "ok",
            "faiss": "ok",
            "embedding_model": "configured",
            "llm_provider": "unavailable",
        }
    else:
        assert response.json()["checks"] == {
            "database": "failed",
            "faiss": "unavailable",
            "embedding_model": "configured",
            "llm_provider": "unavailable",
        }


def test_valid_correlation_id_is_preserved(client: TestClient) -> None:
    response = client.get(
        "/api/v1/health/live",
        headers={"X-Correlation-ID": "telegram-update_123"},
    )

    assert response.headers["X-Correlation-ID"] == "telegram-update_123"


def test_invalid_correlation_id_is_replaced(client: TestClient) -> None:
    response = client.get(
        "/api/v1/health/live",
        headers={"X-Correlation-ID": "unsafe id with spaces"},
    )

    assert response.headers["X-Correlation-ID"] != "unsafe id with spaces"


def test_metrics_expose_bounded_route_counts_and_latency(client: TestClient) -> None:
    client.get("/api/v1/health/live")
    client.get("/missing")

    response = client.get("/api/v1/metrics")

    assert response.status_code == status.HTTP_200_OK
    assert response.headers["content-type"].startswith("text/plain")
    assert 'hotel_build_info{environment="test",version="0.1.0"} 1' in response.text
    assert (
        'hotel_http_requests_total{method="GET",route="/api/v1/health/live",status_class="2xx"} 1'
    ) in response.text
    assert (
        'hotel_http_requests_total{method="GET",route="unmatched",status_class="4xx"} 1'
        in response.text
    )
    assert "hotel_http_request_duration_seconds_bucket" in response.text
    assert 'le="10"' in response.text


def test_security_headers_are_present_on_success_and_error(client: TestClient) -> None:
    for path in ("/api/v1/health/live", "/missing"):
        response = client.get(path)
        assert response.headers["X-Content-Type-Options"] == "nosniff"
        assert response.headers["X-Frame-Options"] == "DENY"
        assert response.headers["Referrer-Policy"] == "no-referrer"
        assert response.headers["Cross-Origin-Opener-Policy"] == "same-origin"
