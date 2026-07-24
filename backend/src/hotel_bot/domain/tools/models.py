"""Immutable contracts for tool execution, limits, results, and audit records."""

from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any
from uuid import UUID

from pydantic import BaseModel

from hotel_bot.domain.tools.enums import ToolCaller, ToolExecutionStatus

if TYPE_CHECKING:
    from hotel_bot.domain.tools.registry import ToolDefinition

ToolHandler = Callable[[BaseModel], Awaitable[BaseModel]]


@dataclass(frozen=True, slots=True)
class RegisteredTool:
    definition: "ToolDefinition"
    handler: ToolHandler


@dataclass(frozen=True, slots=True)
class ToolCall:
    name: str
    arguments: Mapping[str, Any]


@dataclass(frozen=True, slots=True)
class ToolExecutionContext:
    message_id: UUID
    correlation_id: str
    caller: ToolCaller
    confirmed: bool
    call_index: int
    allowed_tool_names: frozenset[str] | None = None

    def __post_init__(self) -> None:
        if not 8 <= len(self.correlation_id) <= 128:
            raise ValueError("correlation_id must contain 8 to 128 characters")
        if self.call_index < 1:
            raise ValueError("tool call index must be positive")
        if self.allowed_tool_names is not None and not self.allowed_tool_names:
            raise ValueError("allowed tool names cannot be empty")


@dataclass(frozen=True, slots=True)
class ToolExecutionResult:
    tool_name: str
    status: ToolExecutionStatus
    output: BaseModel | None
    error_code: str | None
    latency_ms: int


@dataclass(frozen=True, slots=True)
class ToolAttemptRecord:
    message_id: UUID
    tool_name: str
    arguments_redacted: dict[str, Any]
    result_status: ToolExecutionStatus
    result_redacted: dict[str, Any] | None
    latency_ms: int
    correlation_id: str
    error_code: str | None
