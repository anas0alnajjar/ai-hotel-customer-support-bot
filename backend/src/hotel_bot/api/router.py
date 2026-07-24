"""Top-level API router."""

from fastapi import APIRouter

from hotel_bot.api.routes.admin import router as admin_router
from hotel_bot.api.routes.health import router as health_router
from hotel_bot.api.routes.metrics import router as metrics_router
from hotel_bot.api.routes.telegram import router as telegram_router

api_router = APIRouter()
api_router.include_router(health_router, prefix="/health", tags=["health"])
api_router.include_router(metrics_router, prefix="/metrics", tags=["operations"])
api_router.include_router(telegram_router, prefix="/telegram", tags=["telegram"])
api_router.include_router(admin_router, prefix="/admin", tags=["admin"])
