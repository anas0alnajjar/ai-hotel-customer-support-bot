"""Structured logging configuration."""

import json
import logging
import re
from datetime import UTC, datetime
from typing import Any

TELEGRAM_BOT_URL_PATTERN = re.compile(
    r"(https://api\.telegram\.org/bot)[^/\s\"']+",
    re.IGNORECASE,
)


def redact_telegram_bot_token(value: str) -> str:
    """Remove Telegram bot credentials while preserving the endpoint path."""

    return TELEGRAM_BOT_URL_PATTERN.sub(r"\1<REDACTED>", value)


class JsonFormatter(logging.Formatter):
    """Format application logs as single-line JSON records."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": datetime.now(UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": redact_telegram_bot_token(record.getMessage()),
        }
        correlation_id = getattr(record, "correlation_id", None)
        if correlation_id is not None:
            payload["correlation_id"] = correlation_id
        for field in (
            "http_method",
            "http_route",
            "http_status_code",
            "duration_ms",
            "error_code",
        ):
            value = getattr(record, field, None)
            if value is not None:
                payload[field] = value
        if record.exc_info:
            payload["exception"] = redact_telegram_bot_token(
                self.formatException(record.exc_info)
            )
        return json.dumps(payload, ensure_ascii=False)


def configure_logging(level: str) -> None:
    """Configure the root logger once for local and container runtimes."""

    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter())

    root_logger = logging.getLogger()
    root_logger.handlers.clear()
    root_logger.addHandler(handler)
    root_logger.setLevel(level)
