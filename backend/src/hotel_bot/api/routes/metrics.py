"""Prometheus-compatible internal metrics endpoint."""

from typing import cast

from fastapi import APIRouter, Request, Response

from hotel_bot.core.metrics import HttpMetrics

router = APIRouter()


@router.get("")
async def metrics(request: Request) -> Response:
    registry = cast(HttpMetrics, request.app.state.http_metrics)
    return Response(
        registry.render(),
        media_type="text/plain; version=0.0.4; charset=utf-8",
    )
