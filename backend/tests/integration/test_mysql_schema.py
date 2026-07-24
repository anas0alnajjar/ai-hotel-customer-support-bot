"""MySQL migration and transaction-boundary integration tests."""

import asyncio
import os
from pathlib import Path
from uuid import uuid4

import pytest
from pydantic import SecretStr
from sqlalchemy import delete, inspect, select, text

from hotel_bot.core.config import Settings
from hotel_bot.infrastructure.database import DatabaseManager
from hotel_bot.persistence import Guest

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        os.getenv("RUN_MYSQL_INTEGRATION") != "1",
        reason="set RUN_MYSQL_INTEGRATION=1 with the project MySQL container running",
    ),
]


def mysql_settings() -> Settings:
    project_root = Path(__file__).resolve().parents[3]
    values = {
        key: value
        for line in (project_root / ".env").read_text(encoding="utf-8").splitlines()
        if line and not line.lstrip().startswith("#") and "=" in line
        for key, value in [line.split("=", maxsplit=1)]
    }
    return Settings(
        APP_ENVIRONMENT="test",
        DB_HOST=values["DB_HOST"],
        DB_PORT=int(values["DB_PORT"]),
        DB_NAME=values["DB_NAME"],
        DB_USER=values["DB_USER"],
        DB_PASSWORD=SecretStr(values["DB_PASSWORD"]),
        _env_file=None,
    )  # type: ignore[call-arg]


def test_migrated_mysql_schema_matches_metadata() -> None:
    async def inspect_schema() -> tuple[set[str], str]:
        manager = DatabaseManager(mysql_settings())
        try:
            async with manager.engine.connect() as connection:
                tables = await connection.run_sync(
                    lambda sync_connection: set(inspect(sync_connection).get_table_names())
                )
                revision = await connection.scalar(text("SELECT version_num FROM alembic_version"))
                return tables, str(revision)
        finally:
            await manager.dispose()

    tables, revision = asyncio.run(inspect_schema())

    assert tables == {
        "admin_users",
        "alembic_version",
        "audit_events",
        "bookings",
        "channel_updates",
        "conversations",
        "escalations",
        "evaluation_runs",
        "feedback",
        "guests",
        "index_versions",
        "knowledge_chunks",
        "knowledge_documents",
        "knowledge_revisions",
        "llm_runs",
        "messages",
        "rooms",
        "room_types",
        "service_requests",
        "tool_executions",
    }
    assert revision == "b2d4e6f8091a"


def test_transaction_boundary_commits_and_rolls_back_atomically() -> None:
    async def exercise_transactions() -> None:
        manager = DatabaseManager(mysql_settings())
        committed_hash = f"integration-committed-{uuid4().hex}"
        rolled_back_hash = f"integration-rolled-back-{uuid4().hex}"

        try:
            async with manager.transaction() as session:
                session.add(Guest(telegram_user_hash=committed_hash, preferred_language="ar"))

            with pytest.raises(RuntimeError, match="force rollback"):
                async with manager.transaction() as session:
                    session.add(Guest(telegram_user_hash=rolled_back_hash, preferred_language="en"))
                    await session.flush()
                    raise RuntimeError("force rollback")

            async with manager.session() as session:
                rows = (
                    await session.scalars(
                        select(Guest.telegram_user_hash).where(
                            Guest.telegram_user_hash.in_([committed_hash, rolled_back_hash])
                        )
                    )
                ).all()

            assert rows == [committed_hash]
        finally:
            async with manager.transaction() as session:
                await session.execute(
                    delete(Guest).where(Guest.telegram_user_hash == committed_hash)
                )
            await manager.dispose()

    asyncio.run(exercise_transactions())
