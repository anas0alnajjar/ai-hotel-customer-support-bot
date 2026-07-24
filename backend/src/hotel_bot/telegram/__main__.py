"""Register the production HTTPS webhook without exposing secrets."""

import argparse
import asyncio

from hotel_bot.core.config import load_settings
from hotel_bot.infrastructure.telegram import TelegramBotAPIClient


async def configure(url: str, max_connections: int) -> int:
    settings = load_settings()
    if settings.telegram_bot_token is None or settings.telegram_webhook_secret is None:
        raise RuntimeError("TELEGRAM_BOT_TOKEN and TELEGRAM_WEBHOOK_SECRET are required")
    client = TelegramBotAPIClient(
        bot_token=settings.telegram_bot_token.get_secret_value(),
        base_url=settings.telegram_api_base_url,
        timeout_ms=settings.telegram_timeout_ms,
    )
    try:
        await client.set_webhook(
            url=url,
            secret_token=settings.telegram_webhook_secret.get_secret_value(),
            max_connections=max_connections,
        )
    finally:
        await client.close()
    print(f"Telegram webhook configured: url={url} allowed_updates=message")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Configure the Telegram bot webhook")
    parser.add_argument("url", help="Public HTTPS /api/v1/telegram/webhook URL")
    parser.add_argument("--max-connections", type=int, default=20)
    arguments = parser.parse_args()
    return asyncio.run(configure(arguments.url, arguments.max_connections))


if __name__ == "__main__":
    raise SystemExit(main())
