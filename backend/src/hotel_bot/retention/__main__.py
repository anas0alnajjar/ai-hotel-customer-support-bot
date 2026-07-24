"""Run auditable 90-day conversation redaction in bounded transactions."""

import asyncio
import json
from datetime import UTC, datetime
from uuid import uuid4

from hotel_bot.application.conversations import RetentionCleanupService
from hotel_bot.core.config import load_settings
from hotel_bot.infrastructure.database import DatabaseManager
from hotel_bot.infrastructure.repositories.conversations import SQLAlchemyConversationRepository


async def run_cleanup() -> None:
    settings = load_settings()
    manager = DatabaseManager(settings)
    run_id = f"retention-{uuid4()}"
    now = datetime.now(UTC).replace(tzinfo=None)
    total_messages = 0
    total_batches = 0
    try:
        while True:
            total_batches += 1
            async with manager.transaction() as session:
                service = RetentionCleanupService(
                    SQLAlchemyConversationRepository(session),
                    retention_days=settings.conversation_retention_days,
                    batch_size=settings.retention_cleanup_batch_size,
                    clock=lambda: now,
                )
                result = await service.run(correlation_id=f"{run_id}-batch-{total_batches}")
            total_messages += result.redacted_messages
            if not result.has_more:
                break
    finally:
        await manager.dispose()

    print(
        json.dumps(
            {
                "event": "conversation_retention_cleanup_completed",
                "run_id": run_id,
                "cutoff": result.cutoff.isoformat(),
                "batches": total_batches,
                "redacted_messages": total_messages,
            },
            separators=(",", ":"),
            sort_keys=True,
        )
    )


def main() -> None:
    asyncio.run(run_cleanup())


if __name__ == "__main__":
    main()
