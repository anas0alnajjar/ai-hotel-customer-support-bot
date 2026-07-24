"""Classify one persisted inbound message and store its versioned routing evidence."""

from collections.abc import Mapping
from typing import Protocol
from uuid import UUID

from hotel_bot.domain.intent.models import (
    RoutingResult,
    StoredClassification,
    SupportedLanguage,
)
from hotel_bot.domain.intent.routing import SafeIntentRouter


class IntentClassificationRepository(Protocol):
    async def get_inbound_message_text(
        self, message_id: UUID
    ) -> tuple[str, SupportedLanguage] | None: ...

    async def store_classification(
        self, message_id: UUID, result: RoutingResult
    ) -> StoredClassification: ...


class IntentRoutingService:
    def __init__(
        self,
        repository: IntentClassificationRepository,
        router: SafeIntentRouter,
    ) -> None:
        self._repository = repository
        self._router = router

    async def classify_message(
        self,
        message_id: UUID,
        *,
        parameters: Mapping[str, object] | None = None,
    ) -> RoutingResult:
        message = await self._repository.get_inbound_message_text(message_id)
        if message is None:
            raise ValueError("inbound message was not found")
        text, language = message
        result = self._router.route(text, language, parameters=parameters)
        await self._repository.store_classification(message_id, result)
        return result
