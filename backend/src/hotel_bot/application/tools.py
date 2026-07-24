"""Controlled tool execution with allow-list, limits, timeout, and mandatory audit."""

import asyncio
from time import perf_counter
from typing import Any, Protocol

from pydantic import BaseModel, ValidationError

from hotel_bot.domain.hotel.errors import HotelDomainError
from hotel_bot.domain.tools.enums import ToolExecutionStatus
from hotel_bot.domain.tools.errors import ToolAuditError
from hotel_bot.domain.tools.models import (
    ToolAttemptRecord,
    ToolCall,
    ToolExecutionContext,
    ToolExecutionResult,
)
from hotel_bot.domain.tools.registry import ToolDefinition, ToolRegistry

REDACTED = "[REDACTED]"


class ToolAuditRepository(Protocol):
    async def record_tool_attempt(self, attempt: ToolAttemptRecord) -> None: ...


def _safe_tool_name(value: str) -> str:
    normalized = value.strip()
    return normalized[:128] if normalized else "invalid_tool"


def _unvalidated_argument_summary(arguments: object) -> dict[str, Any]:
    if not isinstance(arguments, dict):
        return {"provided_type": type(arguments).__name__[:64]}
    fields = sorted(str(key)[:64] for key in arguments)[:32]
    return {"provided_fields": fields, "values_redacted": True}


def _redacted_model(model: BaseModel, sensitive_fields: frozenset[str]) -> dict[str, Any]:
    payload = model.model_dump(mode="json")
    for field in sensitive_fields:
        if field in payload and payload[field] is not None:
            payload[field] = REDACTED
    return payload


class ControlledToolExecutor:
    """Executes only registered tools and returns controlled, non-throwing outcomes."""

    def __init__(
        self,
        registry: ToolRegistry,
        audit_repository: ToolAuditRepository,
        *,
        max_calls_per_turn: int = 3,
    ) -> None:
        if not 1 <= max_calls_per_turn <= 10:
            raise ValueError("max_calls_per_turn must contain 1 to 10 calls")
        self._registry = registry
        self._audit_repository = audit_repository
        self._max_calls_per_turn = max_calls_per_turn

    async def execute(self, call: ToolCall, context: ToolExecutionContext) -> ToolExecutionResult:
        started = perf_counter()
        safe_name = _safe_tool_name(call.name)
        registered = self._registry.resolve(call.name.strip())
        if registered is None:
            return await self._finish(
                context=context,
                tool_name=safe_name,
                arguments_redacted=_unvalidated_argument_summary(call.arguments),
                status=ToolExecutionStatus.REJECTED,
                output=None,
                result_redacted=None,
                error_code="unknown_tool",
                started=started,
            )

        definition = registered.definition
        if (
            context.allowed_tool_names is not None
            and definition.name not in context.allowed_tool_names
        ):
            return await self._reject_unvalidated(
                context, definition, call, "tool_outside_intent_scope", started
            )
        if context.call_index > self._max_calls_per_turn:
            return await self._reject_unvalidated(
                context, definition, call, "tool_call_limit_exceeded", started
            )
        if context.caller not in definition.allowed_callers:
            return await self._reject_unvalidated(
                context, definition, call, "tool_caller_unauthorized", started
            )
        try:
            arguments = definition.input_model.model_validate(dict(call.arguments))
        except (ValidationError, TypeError, ValueError):
            return await self._finish(
                context=context,
                tool_name=definition.name,
                arguments_redacted=_unvalidated_argument_summary(call.arguments),
                status=ToolExecutionStatus.REJECTED,
                output=None,
                result_redacted=None,
                error_code="invalid_tool_arguments",
                started=started,
            )
        arguments_redacted = _redacted_model(arguments, definition.sensitive_argument_fields)
        if definition.requires_confirmation and not context.confirmed:
            return await self._finish(
                context=context,
                tool_name=definition.name,
                arguments_redacted=arguments_redacted,
                status=ToolExecutionStatus.REJECTED,
                output=None,
                result_redacted=None,
                error_code="tool_confirmation_required",
                started=started,
            )

        try:
            output = await asyncio.wait_for(
                registered.handler(arguments), timeout=definition.timeout_ms / 1000
            )
            if not isinstance(output, definition.output_model):
                raise TypeError("tool returned an invalid output contract")
            return await self._finish(
                context=context,
                tool_name=definition.name,
                arguments_redacted=arguments_redacted,
                status=ToolExecutionStatus.SUCCEEDED,
                output=output,
                result_redacted=_redacted_model(output, definition.sensitive_result_fields),
                error_code=None,
                started=started,
            )
        except TimeoutError:
            return await self._finish(
                context=context,
                tool_name=definition.name,
                arguments_redacted=arguments_redacted,
                status=ToolExecutionStatus.TIMED_OUT,
                output=None,
                result_redacted=None,
                error_code="tool_execution_timed_out",
                started=started,
            )
        except HotelDomainError as exc:
            return await self._finish(
                context=context,
                tool_name=definition.name,
                arguments_redacted=arguments_redacted,
                status=ToolExecutionStatus.REJECTED,
                output=None,
                result_redacted=None,
                error_code=exc.code,
                started=started,
            )
        except Exception:
            return await self._finish(
                context=context,
                tool_name=definition.name,
                arguments_redacted=arguments_redacted,
                status=ToolExecutionStatus.FAILED,
                output=None,
                result_redacted=None,
                error_code="tool_execution_failed",
                started=started,
            )

    async def _reject_unvalidated(
        self,
        context: ToolExecutionContext,
        definition: ToolDefinition,
        call: ToolCall,
        error_code: str,
        started: float,
    ) -> ToolExecutionResult:
        return await self._finish(
            context=context,
            tool_name=definition.name,
            arguments_redacted=_unvalidated_argument_summary(call.arguments),
            status=ToolExecutionStatus.REJECTED,
            output=None,
            result_redacted=None,
            error_code=error_code,
            started=started,
        )

    async def _finish(
        self,
        *,
        context: ToolExecutionContext,
        tool_name: str,
        arguments_redacted: dict[str, Any],
        status: ToolExecutionStatus,
        output: BaseModel | None,
        result_redacted: dict[str, Any] | None,
        error_code: str | None,
        started: float,
    ) -> ToolExecutionResult:
        latency_ms = max(0, int((perf_counter() - started) * 1000))
        attempt = ToolAttemptRecord(
            message_id=context.message_id,
            tool_name=tool_name,
            arguments_redacted=arguments_redacted,
            result_status=status,
            result_redacted=result_redacted,
            latency_ms=latency_ms,
            correlation_id=context.correlation_id,
            error_code=error_code,
        )
        try:
            await self._audit_repository.record_tool_attempt(attempt)
        except Exception as exc:
            raise ToolAuditError("tool attempt could not be audited") from exc
        return ToolExecutionResult(
            tool_name=tool_name,
            status=status,
            output=output,
            error_code=error_code,
            latency_ms=latency_ms,
        )
