"""Structured logging redaction contracts."""

import json
import logging

from hotel_bot.core.logging import JsonFormatter, redact_telegram_bot_token


def test_telegram_bot_token_is_redacted_without_losing_http_context() -> None:
    token = "123456789:example-secret-token"
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    record = logging.LogRecord(
        name="httpx",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg='HTTP Request: POST %s "HTTP/1.1 200 OK"',
        args=(url,),
        exc_info=None,
    )

    payload = json.loads(JsonFormatter().format(record))

    assert token not in payload["message"]
    assert "bot<REDACTED>/sendMessage" in payload["message"]
    assert "POST" in payload["message"]
    assert "200 OK" in payload["message"]
    assert redact_telegram_bot_token(url).endswith(
        "/bot<REDACTED>/sendMessage"
    )
