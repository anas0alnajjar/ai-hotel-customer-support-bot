"""MySQL engine, session, and transaction lifecycle support."""

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from hotel_bot.core.config import Settings

logger = logging.getLogger(__name__)


class DatabaseManager:
    """Own the SQLAlchemy async engine for the application lifetime."""

    def __init__(self, settings: Settings) -> None:
        self._engine: AsyncEngine = create_async_engine(
            settings.sqlalchemy_url,
            pool_pre_ping=True,
            pool_recycle=1800,
            pool_size=settings.db_pool_size,
            max_overflow=settings.db_max_overflow,
        )
        self._session_factory = async_sessionmaker(
            bind=self._engine,
            class_=AsyncSession,
            expire_on_commit=False,
            autoflush=False,
        )

    @property
    def engine(self) -> AsyncEngine:
        """Expose the engine for migration and operational integration boundaries."""

        return self._engine

    @asynccontextmanager
    async def session(self) -> AsyncIterator[AsyncSession]:
        """Yield a session without implicitly committing application work."""

        async with self._session_factory() as session:
            yield session

    @asynccontextmanager
    async def transaction(self) -> AsyncIterator[AsyncSession]:
        """Commit one use-case atomically, rolling back on any exception."""

        async with self._session_factory.begin() as session:
            yield session

    async def ping(self) -> bool:
        """Return whether MySQL can execute a minimal query."""

        try:
            async with self._engine.connect() as connection:
                await connection.execute(text("SELECT 1"))
        except (SQLAlchemyError, OSError, RuntimeError):
            logger.exception("Database readiness check failed")
            return False
        return True

    async def dispose(self) -> None:
        """Close all pooled connections."""

        await self._engine.dispose()
