"""SQLAlchemy persistence adapter for versioned message intent results."""

from typing import cast
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from hotel_bot.domain.conversation.enums import MessageDirection
from hotel_bot.domain.intent.models import (
    RoutingResult,
    StoredClassification,
    SupportedLanguage,
)
from hotel_bot.persistence.models import Message


class SQLAlchemyIntentClassificationRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_inbound_message_text(
        self, message_id: UUID
    ) -> tuple[str, SupportedLanguage] | None:
        row = await self._session.scalar(
            select(Message).where(Message.id == message_id).with_for_update().limit(1)
        )
        if row is None or row.direction is not MessageDirection.INBOUND:
            return None
        return row.text, cast(SupportedLanguage, row.language)

    async def store_classification(
        self, message_id: UUID, result: RoutingResult
    ) -> StoredClassification:
        row = await self._session.scalar(
            select(Message).where(Message.id == message_id).with_for_update().limit(1)
        )
        if row is None or row.direction is not MessageDirection.INBOUND:
            raise ValueError("inbound message was not found")
        row.intent = result.prediction.intent.value
        row.confidence = result.prediction.confidence
        row.classifier_version = result.prediction.classifier_version
        await self._session.flush()
        return StoredClassification(
            message_id=row.id,
            intent=result.prediction.intent,
            confidence=float(row.confidence),
            classifier_version=result.prediction.classifier_version,
        )
