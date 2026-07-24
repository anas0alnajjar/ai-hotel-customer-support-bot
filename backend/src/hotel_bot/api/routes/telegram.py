"""Authenticated Telegram webhook endpoint with bounded raw-body validation."""

import secrets
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import ValidationError

from hotel_bot.core.config import Settings
from hotel_bot.dependencies import (
    get_database_manager,
    get_settings,
    get_telegram_runtime,
)
from hotel_bot.domain.telegram.errors import (
    TelegramConfigurationError,
    TelegramDeliveryError,
)
from hotel_bot.domain.telegram.models import TelegramUpdate, TelegramWebhookResult
from hotel_bot.infrastructure.database import DatabaseManager
from hotel_bot.infrastructure.telegram_runtime import TelegramApplicationRuntime

WEBHOOK_SECRET_HEADER = "X-Telegram-Bot-Api-Secret-Token"

router = APIRouter()


@router.post(
    "/webhook",
    response_model=TelegramWebhookResult,
    status_code=status.HTTP_200_OK,
)
async def telegram_webhook(
    request: Request,
    settings: Annotated[Settings, Depends(get_settings)],
    database: Annotated[DatabaseManager, Depends(get_database_manager)],
    runtime: Annotated[TelegramApplicationRuntime, Depends(get_telegram_runtime)],
) -> TelegramWebhookResult:
    if not runtime.configured or runtime.webhook_secret is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="telegram_not_configured",
        )
    supplied_secret = request.headers.get(WEBHOOK_SECRET_HEADER, "")
    if not secrets.compare_digest(supplied_secret, runtime.webhook_secret):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="invalid_webhook_secret",
        )
    content_type = request.headers.get("content-type", "").split(";", maxsplit=1)[0].lower()
    if content_type != "application/json":
        raise HTTPException(status_code=415, detail="telegram_content_type_unsupported")
    content_length = request.headers.get("content-length")
    if content_length is not None:
        try:
            declared_size = int(content_length)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail="invalid_content_length") from exc
        if declared_size > settings.telegram_max_update_bytes:
            raise HTTPException(status_code=413, detail="telegram_update_too_large")
    body = await request.body()
    if len(body) > settings.telegram_max_update_bytes:
        raise HTTPException(status_code=413, detail="telegram_update_too_large")
    try:
        update = TelegramUpdate.model_validate_json(body)
    except ValidationError as exc:
        raise HTTPException(status_code=400, detail="invalid_telegram_update") from exc

    correlation_id = str(request.state.correlation_id)
    try:
        async with database.transaction() as session:
            return await runtime.handle(session, update, correlation_id=correlation_id)
    except TelegramConfigurationError as exc:
        raise HTTPException(status_code=503, detail=exc.code) from exc
    except TelegramDeliveryError as exc:
        raise HTTPException(status_code=502, detail=exc.code) from exc
