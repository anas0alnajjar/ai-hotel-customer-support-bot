"""MySQL-backed conversation ordering, idempotency, session, and retention tests."""

import asyncio
import hashlib
import os
from datetime import datetime
from pathlib import Path

import pytest
from pydantic import SecretStr
from sqlalchemy import delete, select

from hotel_bot.application.conversations import ConversationService, RetentionCleanupService
from hotel_bot.application.intent_routing import IntentRoutingService
from hotel_bot.core.config import Settings
from hotel_bot.domain.conversation.enums import ConversationStatus
from hotel_bot.domain.conversation.errors import IdempotencyConflict
from hotel_bot.domain.intent.classifier import ALGORITHM_VERSION, NaiveBayesIntentClassifier
from hotel_bot.domain.intent.enums import DatasetSplit, IntentCode, RoutingDecision
from hotel_bot.domain.intent.routing import SafeIntentRouter
from hotel_bot.infrastructure.database import DatabaseManager
from hotel_bot.infrastructure.intent_dataset import load_intent_dataset
from hotel_bot.infrastructure.repositories.conversations import SQLAlchemyConversationRepository
from hotel_bot.infrastructure.repositories.intent_routing import (
    SQLAlchemyIntentClassificationRepository,
)
from hotel_bot.persistence import AuditEvent, ChannelUpdate, Conversation, Guest, Message

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


def identity_hash(label: str) -> str:
    return hashlib.sha256(label.encode()).hexdigest()


async def remove_guest_data(manager: DatabaseManager, guest_hashes: list[str]) -> None:
    async with manager.transaction() as session:
        guest_ids = (
            await session.scalars(
                select(Guest.id).where(Guest.telegram_user_hash.in_(guest_hashes))
            )
        ).all()
        if guest_ids:
            await session.execute(
                delete(ChannelUpdate).where(ChannelUpdate.guest_id.in_(guest_ids))
            )
            await session.execute(delete(Conversation).where(Conversation.guest_id.in_(guest_ids)))
            await session.execute(delete(Guest).where(Guest.id.in_(guest_ids)))


def test_message_order_idempotency_and_inactivity_session_rotation() -> None:
    async def exercise() -> None:
        manager = DatabaseManager(mysql_settings())
        guest_hash = identity_hash("step-04-lifecycle-guest")
        first_time = datetime(2026, 7, 13, 12, 0, 0)
        try:
            await remove_guest_data(manager, [guest_hash])
            async with manager.transaction() as session:
                service = ConversationService(
                    SQLAlchemyConversationRepository(session), clock=lambda: first_time
                )
                inbound = await service.record_inbound(
                    channel="telegram",
                    external_update_id="step04-update-1",
                    guest_identity_hash=guest_hash,
                    text="مرحبا، ما أنواع الغرف؟",
                    language="ar",
                    correlation_id="step04-correlation-1",
                )
                outbound = await service.record_outbound(
                    channel="telegram",
                    external_update_id="step04-update-1",
                    text="تتوفر عدة أنواع من الغرف.",
                    language="ar",
                    correlation_id="step04-correlation-1",
                )
                assert inbound.message.sequence_number == 1
                assert outbound.sequence_number == 2

            async with manager.transaction() as session:
                service = ConversationService(
                    SQLAlchemyConversationRepository(session), clock=lambda: first_time
                )
                duplicate = await service.record_inbound(
                    channel="telegram",
                    external_update_id="step04-update-1",
                    guest_identity_hash=guest_hash,
                    text="مرحبا، ما أنواع الغرف؟",
                    language="ar",
                    correlation_id="delivery-retry-correlation",
                )
                assert duplicate.duplicate is True
                assert duplicate.message.id == inbound.message.id

            with pytest.raises(IdempotencyConflict):
                async with manager.transaction() as session:
                    service = ConversationService(
                        SQLAlchemyConversationRepository(session), clock=lambda: first_time
                    )
                    await service.record_inbound(
                        channel="telegram",
                        external_update_id="step04-update-1",
                        guest_identity_hash=guest_hash,
                        text="different payload",
                        language="en",
                        correlation_id="conflicting-delivery",
                    )

            later = datetime(2026, 7, 13, 12, 31, 0)
            async with manager.transaction() as session:
                service = ConversationService(
                    SQLAlchemyConversationRepository(session), clock=lambda: later
                )
                rotated = await service.record_inbound(
                    channel="telegram",
                    external_update_id="step04-update-2",
                    guest_identity_hash=guest_hash,
                    text="ابدأ محادثة جديدة",
                    language="ar",
                    correlation_id="step04-correlation-2",
                )
                assert rotated.conversation.id != inbound.conversation.id
                assert rotated.message.sequence_number == 1

            async with manager.session() as session:
                messages = (
                    await session.scalars(
                        select(Message)
                        .where(Message.conversation_id == inbound.conversation.id)
                        .order_by(Message.sequence_number)
                    )
                ).all()
                old_conversation = await session.get(Conversation, inbound.conversation.id)
                assert [row.sequence_number for row in messages] == [1, 2]
                assert old_conversation is not None
                assert old_conversation.status is ConversationStatus.CLOSED
        finally:
            await remove_guest_data(manager, [guest_hash])
            await manager.dispose()

    asyncio.run(exercise())


def test_retention_redacts_expired_text_clears_summary_and_writes_audit_event() -> None:
    async def exercise() -> None:
        manager = DatabaseManager(mysql_settings())
        old_hash = identity_hash("step-04-old-retention-guest")
        recent_hash = identity_hash("step-04-recent-retention-guest")
        cleanup_correlation = "step04-retention-cleanup"
        old_time = datetime(2026, 1, 1, 10, 0, 0)
        recent_time = datetime(2026, 7, 12, 10, 0, 0)
        cleanup_time = datetime(2026, 7, 13, 10, 0, 0)
        try:
            await remove_guest_data(manager, [old_hash, recent_hash])
            async with manager.transaction() as session:
                old_service = ConversationService(
                    SQLAlchemyConversationRepository(session), clock=lambda: old_time
                )
                old = await old_service.record_inbound(
                    channel="telegram",
                    external_update_id="step04-old-update",
                    guest_identity_hash=old_hash,
                    text="old-sensitive-message",
                    language="en",
                    correlation_id="step04-old-correlation",
                )
                await old_service.record_outbound(
                    channel="telegram",
                    external_update_id="step04-old-update",
                    text="old-sensitive-response",
                    language="en",
                    correlation_id="step04-old-correlation",
                )
                conversation = await session.get(Conversation, old.conversation.id)
                assert conversation is not None
                conversation.summary = "old-sensitive-summary"
                conversation.summary_through_message_id = old.message.id

                recent_service = ConversationService(
                    SQLAlchemyConversationRepository(session), clock=lambda: recent_time
                )
                recent = await recent_service.record_inbound(
                    channel="telegram",
                    external_update_id="step04-recent-update",
                    guest_identity_hash=recent_hash,
                    text="recent-message-must-remain",
                    language="en",
                    correlation_id="step04-recent-correlation",
                )

            async with manager.transaction() as session:
                cleanup = RetentionCleanupService(
                    SQLAlchemyConversationRepository(session),
                    retention_days=90,
                    batch_size=500,
                    clock=lambda: cleanup_time,
                )
                result = await cleanup.run(correlation_id=cleanup_correlation)
                assert result.redacted_messages == 2
                assert result.affected_conversations == 1
                assert result.has_more is False

            async with manager.session() as session:
                old_messages = (
                    await session.scalars(
                        select(Message).where(Message.conversation_id == old.conversation.id)
                    )
                ).all()
                recent_message = await session.get(Message, recent.message.id)
                old_conversation = await session.get(Conversation, old.conversation.id)
                audit = await session.scalar(
                    select(AuditEvent).where(AuditEvent.correlation_id == cleanup_correlation)
                )
                assert {row.text for row in old_messages} == {"[redacted:retention]"}
                assert all(row.redacted_at == cleanup_time for row in old_messages)
                assert all(row.retention_action == "anonymized" for row in old_messages)
                assert recent_message is not None
                assert recent_message.text == "recent-message-must-remain"
                assert old_conversation is not None
                assert old_conversation.summary is None
                assert old_conversation.summary_through_message_id is None
                assert audit is not None
                assert audit.metadata_redacted is not None
                assert audit.metadata_redacted["message_count"] == 2

            async with manager.transaction() as session:
                cleanup = RetentionCleanupService(
                    SQLAlchemyConversationRepository(session),
                    retention_days=90,
                    batch_size=500,
                    clock=lambda: cleanup_time,
                )
                rerun = await cleanup.run(correlation_id=f"{cleanup_correlation}-rerun")
                assert rerun.redacted_messages == 0

            async with manager.session() as session:
                rerun_audit = await session.scalar(
                    select(AuditEvent).where(
                        AuditEvent.correlation_id == f"{cleanup_correlation}-rerun"
                    )
                )
                assert rerun_audit is not None
                assert rerun_audit.metadata_redacted is not None
                assert rerun_audit.metadata_redacted["message_count"] == 0
        finally:
            await remove_guest_data(manager, [old_hash, recent_hash])
            async with manager.transaction() as session:
                await session.execute(
                    delete(AuditEvent).where(
                        AuditEvent.correlation_id.in_(
                            [cleanup_correlation, f"{cleanup_correlation}-rerun"]
                        )
                    )
                )
            await manager.dispose()

    asyncio.run(exercise())


def test_intent_result_is_versioned_and_persisted_on_inbound_message() -> None:
    dataset_path = (
        Path(__file__).resolve().parents[2]
        / "src"
        / "hotel_bot"
        / "intent"
        / "data"
        / "intent-dataset-v1.json"
    )
    loaded = load_intent_dataset(dataset_path)
    classifier_version = f"{ALGORITHM_VERSION}+{loaded.dataset.dataset_version}.{loaded.sha256[:8]}"
    classifier = NaiveBayesIntentClassifier(classifier_version=classifier_version)
    classifier.fit(
        sample for sample in loaded.dataset.samples if sample.split is DatasetSplit.TRAIN
    )

    async def exercise() -> None:
        manager = DatabaseManager(mysql_settings())
        guest_hash = identity_hash("step-05-intent-persistence-guest")
        try:
            await remove_guest_data(manager, [guest_hash])
            async with manager.transaction() as session:
                conversation_service = ConversationService(
                    SQLAlchemyConversationRepository(session),
                    clock=lambda: datetime(2026, 7, 13, 14, 0, 0),
                )
                inbound = await conversation_service.record_inbound(
                    channel="telegram",
                    external_update_id="step05-intent-update-1",
                    guest_identity_hash=guest_hash,
                    text="أريد العثور على حجزي باستخدام الرقم",
                    language="ar",
                    correlation_id="step05-intent-correlation-1",
                )
                routing_service = IntentRoutingService(
                    SQLAlchemyIntentClassificationRepository(session),
                    SafeIntentRouter(classifier),
                )
                result = await routing_service.classify_message(
                    inbound.message.id,
                    parameters={
                        "booking_reference": "NSH1001",
                        "verification_value": "synthetic-value",
                    },
                )
                assert result.prediction.intent is IntentCode.BOOKING_LOOKUP
                assert result.decision is RoutingDecision.ACTION_CANDIDATE
                assert result.allow_tool_execution is False

            async with manager.session() as session:
                stored = await session.get(Message, inbound.message.id)
                assert stored is not None
                assert stored.intent == IntentCode.BOOKING_LOOKUP.value
                assert float(stored.confidence or 0) >= 0.80
                assert stored.classifier_version == classifier_version
        finally:
            await remove_guest_data(manager, [guest_hash])
            await manager.dispose()

    asyncio.run(exercise())
