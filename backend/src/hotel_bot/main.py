"""FastAPI application factory and runtime entry point."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from starlette.middleware.trustedhost import TrustedHostMiddleware

from hotel_bot.api.router import api_router
from hotel_bot.core.config import Settings, load_settings
from hotel_bot.core.logging import configure_logging
from hotel_bot.core.metrics import HttpMetrics
from hotel_bot.infrastructure.admin_runtime import AdminApplicationRuntime
from hotel_bot.infrastructure.database import DatabaseManager
from hotel_bot.infrastructure.telegram_runtime import TelegramApplicationRuntime
from hotel_bot.middleware.correlation import CorrelationIdMiddleware
from hotel_bot.middleware.observability import HttpObservabilityMiddleware
from hotel_bot.middleware.security_headers import SecurityHeadersMiddleware


def create_app(settings: Settings | None = None) -> FastAPI:
    """Create an isolated application instance."""

    app_settings = settings or load_settings()
    configure_logging(app_settings.log_level)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        database = DatabaseManager(app_settings)
        admin_runtime = AdminApplicationRuntime(app_settings)
        telegram_runtime = TelegramApplicationRuntime(app_settings)
        app.state.database = database
        app.state.admin_runtime = admin_runtime
        app.state.telegram_runtime = telegram_runtime
        try:
            yield
        finally:
            await telegram_runtime.close()
            await database.dispose()

    is_production = app_settings.environment == "production"
    app = FastAPI(
        title=app_settings.app_name,
        version=app_settings.app_version,
        debug=app_settings.debug,
        docs_url=None if is_production else "/docs",
        redoc_url=None,
        openapi_url=None if is_production else "/openapi.json",
        lifespan=lifespan,
    )
    app.state.settings = app_settings
    http_metrics = HttpMetrics(
        version=app_settings.app_version,
        environment=app_settings.environment,
    )
    app.state.http_metrics = http_metrics
    app.add_middleware(
        TrustedHostMiddleware,
        allowed_hosts=list(app_settings.trusted_host_list),
    )
    app.add_middleware(SecurityHeadersMiddleware)
    app.add_middleware(HttpObservabilityMiddleware, metrics=http_metrics)
    app.add_middleware(CorrelationIdMiddleware)
    app.include_router(api_router, prefix=app_settings.api_v1_prefix)
    return app


app = create_app()
