"""FastAPI dependency providers."""

from typing import cast

from fastapi import Request

from hotel_bot.core.config import Settings
from hotel_bot.infrastructure.admin_runtime import AdminApplicationRuntime
from hotel_bot.infrastructure.database import DatabaseManager
from hotel_bot.infrastructure.telegram_runtime import TelegramApplicationRuntime


def get_settings(request: Request) -> Settings:
    """Return application-scoped settings."""

    return cast(Settings, request.app.state.settings)


def get_database_manager(request: Request) -> DatabaseManager:
    """Return the application-scoped database manager."""

    return cast(DatabaseManager, request.app.state.database)


def get_telegram_runtime(request: Request) -> TelegramApplicationRuntime:
    return cast(TelegramApplicationRuntime, request.app.state.telegram_runtime)


def get_admin_runtime(request: Request) -> AdminApplicationRuntime:
    return cast(AdminApplicationRuntime, request.app.state.admin_runtime)
