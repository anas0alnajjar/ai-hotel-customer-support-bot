"""Liveness and readiness endpoints."""

from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Response, status
from pydantic import BaseModel

from hotel_bot.core.config import Settings
from hotel_bot.dependencies import get_admin_runtime, get_database_manager, get_settings
from hotel_bot.infrastructure.admin_runtime import AdminApplicationRuntime
from hotel_bot.infrastructure.database import DatabaseManager

router = APIRouter()


class HealthResponse(BaseModel):
    """Public health response without infrastructure secrets."""

    status: Literal["ok", "degraded", "not_ready"]
    service: str
    version: str
    checks: dict[str, Literal["ok", "configured", "unavailable", "failed"]]


@router.get("/live", response_model=HealthResponse)
async def liveness(
    settings: Annotated[Settings, Depends(get_settings)],
) -> HealthResponse:
    """Return process liveness without checking external dependencies."""

    return HealthResponse(
        status="ok",
        service=settings.app_name,
        version=settings.app_version,
        checks={"application": "ok"},
    )


@router.get(
    "/ready",
    response_model=HealthResponse,
    responses={status.HTTP_503_SERVICE_UNAVAILABLE: {"model": HealthResponse}},
)
async def readiness(
    response: Response,
    settings: Annotated[Settings, Depends(get_settings)],
    database: Annotated[DatabaseManager, Depends(get_database_manager)],
    admin_runtime: Annotated[AdminApplicationRuntime, Depends(get_admin_runtime)],
) -> HealthResponse:
    """Expose dependency state without making optional degraded paths fail liveness."""

    database_is_ready = await database.ping()
    if not database_is_ready:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        return HealthResponse(
            status="not_ready",
            service=settings.app_name,
            version=settings.app_version,
            checks={
                "database": "failed",
                "faiss": "unavailable",
                "embedding_model": "configured",
                "llm_provider": "configured" if settings.gemini_api_key else "unavailable",
            },
        )

    async with database.session() as session:
        faiss_status = await admin_runtime.active_index_status(session)
    degraded = faiss_status != "ok" or settings.gemini_api_key is None

    return HealthResponse(
        status="degraded" if degraded else "ok",
        service=settings.app_name,
        version=settings.app_version,
        checks={
            "database": "ok",
            "faiss": faiss_status,
            "embedding_model": "configured",
            "llm_provider": "configured" if settings.gemini_api_key else "unavailable",
        },
    )
