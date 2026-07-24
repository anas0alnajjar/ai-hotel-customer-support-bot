"""Correlation ID propagation for HTTP requests."""

import re
from uuid import uuid4

from starlette.datastructures import Headers, MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

CORRELATION_HEADER = "X-Correlation-ID"
VALID_CORRELATION_ID = re.compile(r"^[A-Za-z0-9._-]{1,128}$")


class CorrelationIdMiddleware:
    """Accept a safe correlation ID or generate one and return it to the caller."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        supplied_id = Headers(scope=scope).get(CORRELATION_HEADER)
        correlation_id = (
            supplied_id
            if supplied_id and VALID_CORRELATION_ID.fullmatch(supplied_id)
            else str(uuid4())
        )
        scope.setdefault("state", {})["correlation_id"] = correlation_id

        async def send_with_correlation_id(message: Message) -> None:
            if message["type"] == "http.response.start":
                MutableHeaders(scope=message)[CORRELATION_HEADER] = correlation_id
            await send(message)

        await self.app(scope, receive, send_with_correlation_id)
