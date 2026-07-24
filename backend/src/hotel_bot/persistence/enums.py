"""Persisted domain enumerations.

Values are stored as portable strings with CHECK constraints instead of MySQL-native
ENUMs, keeping future value changes migration-friendly.
"""

from enum import StrEnum

from hotel_bot.domain.conversation.enums import (
    ChannelUpdateStatus,
    ConversationStatus,
    MessageDirection,
)
from hotel_bot.domain.knowledge.enums import IndexStatus, KnowledgeStatus
from hotel_bot.domain.llm.enums import LLMRunStatus
from hotel_bot.domain.tools.enums import ToolExecutionStatus

__all__ = [
    "ChannelUpdateStatus",
    "ConversationStatus",
    "IndexStatus",
    "KnowledgeStatus",
    "MessageDirection",
    "LLMRunStatus",
    "ToolExecutionStatus",
]


class AdminRole(StrEnum):
    ADMIN = "admin"
    SUPPORT = "support"
    EVALUATOR = "evaluator"


class AdminStatus(StrEnum):
    ACTIVE = "active"
    DISABLED = "disabled"


class EscalationStatus(StrEnum):
    OPEN = "open"
    ASSIGNED = "assigned"
    RESOLVED = "resolved"
    CANCELLED = "cancelled"


class FeedbackSource(StrEnum):
    GUEST = "guest"
    EVALUATOR = "evaluator"


class EvaluationStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class ActorType(StrEnum):
    GUEST = "guest"
    ADMIN = "admin"
    SUPPORT = "support"
    EVALUATOR = "evaluator"
    SYSTEM = "system"
