"""CLI entry point for the safe ensure-only hotel seed process."""

import asyncio
import json

from hotel_bot.core.config import load_settings
from hotel_bot.infrastructure.database import DatabaseManager
from hotel_bot.seed.loader import HotelSeeder


async def run() -> None:
    database = DatabaseManager(load_settings())
    try:
        async with database.transaction() as session:
            result = await HotelSeeder(session).seed()
    finally:
        await database.dispose()
    print(
        json.dumps(
            {
                "dataset_version": result.dataset_version,
                "inserted": result.inserted,
                "existing": result.existing,
                "inserted_total": result.inserted_total,
                "existing_total": result.existing_total,
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    asyncio.run(run())
