"""Database infrastructure behavior tests."""

import asyncio
from types import TracebackType
from typing import cast

from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from hotel_bot.infrastructure.database import DatabaseManager


class FailingConnectionContext:
    async def __aenter__(self) -> AsyncConnection:
        raise RuntimeError("simulated driver authentication failure")

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        return None


class FailingEngine:
    def connect(self) -> FailingConnectionContext:
        return FailingConnectionContext()

    async def dispose(self) -> None:
        return None


def test_ping_converts_driver_runtime_error_to_not_ready() -> None:
    manager = DatabaseManager.__new__(DatabaseManager)
    manager._engine = cast(AsyncEngine, FailingEngine())

    assert asyncio.run(manager.ping()) is False
