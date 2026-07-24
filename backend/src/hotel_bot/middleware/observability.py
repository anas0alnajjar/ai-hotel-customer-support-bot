"""HTTP metrics and structured completion logging."""

import logging
import re
from time import perf_counter
from typing import Any

from starlette.types import ASGIApp, Message, Receive, Scope, Send

from hotel_bot.core.metrics import HttpMetrics

logger = logging.getLogger("hotel_bot.http")
UUID_PATH_SEGMENT = re.compile(
    r"(?<=/)[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}(?=/|$)",
    re.IGNORECASE,
)


def _route(scope: Scope) -> str:
    route = scope.get("route")
    path = getattr(route, "path", None)
    raw_path = scope.get("path")
    if (
        isinstance(path, str)
        and path.startswith("/")
        and isinstance(raw_path, str)
        and raw_path.startswith("/")
    ):
        return UUID_PATH_SEGMENT.sub("{id}", raw_path)
    return "unmatched"


class HttpObservabilityMiddleware:
    """Record bounded route metrics without guest IDs, query strings, or request bodies."""

    def __init__(self, app: ASGIApp, *, metrics: HttpMetrics) -> None:
        self.app = app
        self.metrics = metrics

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        started_at = perf_counter()
        status_code = 500
        self.metrics.started()

        async def capture_status(message: Message) -> None:
            nonlocal status_code
            if message["type"] == "http.response.start":
                status_code = int(message["status"])
            await send(message)

        try:
            await self.app(scope, receive, capture_status)
        finally:
            duration = perf_counter() - started_at
            method = str(scope.get("method", "UNKNOWN")).upper()
            route = _route(scope)
            self.metrics.finished(
                method=method,
                route=route,
                status_code=status_code,
                duration=duration,
            )
            state: dict[str, Any] = scope.get("state", {})
            logger.info(
                "http_request_completed",
                extra={
                    "correlation_id": state.get("correlation_id"),
                    "http_method": method,
                    "http_route": route,
                    "http_status_code": status_code,
                    "duration_ms": round(duration * 1000, 3),
                },
            )
