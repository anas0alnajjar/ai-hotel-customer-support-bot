"""Allow-list, schema, authorization, timeout, privacy, and audit contracts."""

import asyncio
from typing import Any, cast
from uuid import uuid4

import pytest
from pydantic import BaseModel, ConfigDict

from hotel_bot.application.hotel_tools import (
    AvailabilityInput,
    HotelToolService,
    MaintenanceRequestInput,
    RoomServiceRequestInput,
    build_hotel_tool_registry,
)
from hotel_bot.application.tools import ControlledToolExecutor
from hotel_bot.domain.hotel.errors import VerificationFailed
from hotel_bot.domain.tools.enums import (
    ToolAuditPolicy,
    ToolCaller,
    ToolEffect,
    ToolExecutionStatus,
)
from hotel_bot.domain.tools.errors import ToolAuditError, ToolConfigurationError
from hotel_bot.domain.tools.models import (
    RegisteredTool,
    ToolAttemptRecord,
    ToolCall,
    ToolExecutionContext,
)
from hotel_bot.domain.tools.registry import ToolDefinition, ToolRegistry


class ExampleInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    value: str
    secret: str


class ExampleOutput(BaseModel):
    value: str
    private_result: str


class MemoryAudit:
    def __init__(self, *, fail: bool = False) -> None:
        self.attempts: list[ToolAttemptRecord] = []
        self.fail = fail

    async def record_tool_attempt(self, attempt: ToolAttemptRecord) -> None:
        if self.fail:
            raise RuntimeError("simulated audit failure")
        self.attempts.append(attempt)


def context(
    *,
    caller: ToolCaller = ToolCaller.ASSISTANT,
    confirmed: bool = True,
    call_index: int = 1,
    allowed_tool_names: frozenset[str] | None = None,
) -> ToolExecutionContext:
    return ToolExecutionContext(
        message_id=uuid4(),
        correlation_id="tool-test-correlation",
        caller=caller,
        confirmed=confirmed,
        call_index=call_index,
        allowed_tool_names=allowed_tool_names,
    )


def registry_for(handler: Any, *, effect: ToolEffect = ToolEffect.WRITE) -> ToolRegistry:
    return ToolRegistry(
        (
            RegisteredTool(
                ToolDefinition(
                    name="example_tool",
                    description="Execute a controlled example operation for contract testing.",
                    input_model=ExampleInput,
                    output_model=ExampleOutput,
                    allowed_callers=frozenset({ToolCaller.ASSISTANT}),
                    timeout_ms=100,
                    effect=effect,
                    requires_confirmation=effect is ToolEffect.WRITE,
                    sensitive_argument_fields=frozenset({"secret"}),
                    sensitive_result_fields=frozenset({"private_result"}),
                ),
                handler,
            ),
        )
    )


def test_hotel_registry_exposes_exact_strict_contracts() -> None:
    registry = build_hotel_tool_registry(cast(HotelToolService, object()))
    expected_names = {
        "lookup_booking",
        "check_room_availability",
        "list_room_types",
        "create_room_service_request",
        "create_maintenance_request",
        "get_service_request_status",
    }

    assert {item.name for item in registry.definitions} == expected_names
    assert len(registry.declarations()) == 6
    for definition in registry.definitions:
        assert definition.audit_policy is ToolAuditPolicy.ALWAYS
        assert definition.allowed_callers == frozenset({ToolCaller.ASSISTANT})
        assert definition.timeout_ms > 0
        assert definition.input_model.model_config["extra"] == "forbid"
        assert definition.declaration()["parameters"]
        if definition.effect is ToolEffect.WRITE:
            assert definition.requires_confirmation is True


def test_tool_input_schemas_reject_extra_wrong_type_and_incomplete_verification() -> None:
    with pytest.raises(ValueError):
        AvailabilityInput.model_validate(
            {
                "check_in": "2026-08-10",
                "check_out": "2026-08-12",
                "adults": "2",
                "unexpected": True,
            }
        )
    with pytest.raises(ValueError):
        RoomServiceRequestInput.model_validate(
            {
                "category": "amenities",
                "room_number": "101",
                "description": "Deliver two additional towels.",
                "idempotency_key": "tool-schema-test-0001",
                "booking_reference": "BKG-2026-0001",
            }
        )
    emergency = MaintenanceRequestInput.model_validate(
        {
            "category": "safety",
            "room_number": "304",
            "description": "A smoke alarm requires immediate staff inspection.",
            "idempotency_key": "tool-schema-test-0002",
            "urgency": "emergency",
        }
    )
    assert emergency.urgency.value == "emergency"


def test_executor_rejects_unknown_unauthorized_over_limit_and_unconfirmed_calls() -> None:
    async def exercise() -> None:
        executed = 0

        async def handler(arguments: BaseModel) -> BaseModel:
            nonlocal executed
            executed += 1
            values = cast(ExampleInput, arguments)
            return ExampleOutput(value=values.value, private_result="internal")

        audit = MemoryAudit()
        executor = ControlledToolExecutor(registry_for(handler), audit)
        calls = [
            (
                ToolCall("hidden_shell", {"secret": "do-not-store"}),
                context(),
                "unknown_tool",
            ),
            (
                ToolCall("example_tool", {"value": "safe", "secret": "do-not-store"}),
                context(caller=ToolCaller.ADMIN),
                "tool_caller_unauthorized",
            ),
            (
                ToolCall("example_tool", {"value": "safe", "secret": "do-not-store"}),
                context(call_index=4),
                "tool_call_limit_exceeded",
            ),
            (
                ToolCall("example_tool", {"value": "safe", "secret": "do-not-store"}),
                context(confirmed=False),
                "tool_confirmation_required",
            ),
            (
                ToolCall("example_tool", {"value": "safe", "secret": "do-not-store"}),
                context(allowed_tool_names=frozenset({"different_tool"})),
                "tool_outside_intent_scope",
            ),
        ]
        for call, execution_context, expected_error in calls:
            result = await executor.execute(call, execution_context)
            assert result.status is ToolExecutionStatus.REJECTED
            assert result.error_code == expected_error
        assert executed == 0
        assert len(audit.attempts) == 5
        assert "do-not-store" not in str([item.arguments_redacted for item in audit.attempts])

    asyncio.run(exercise())


def test_executor_redacts_success_and_business_rejection_audits() -> None:
    async def exercise() -> None:
        async def success(arguments: BaseModel) -> BaseModel:
            values = cast(ExampleInput, arguments)
            return ExampleOutput(value=values.value, private_result="sensitive-output")

        success_audit = MemoryAudit()
        succeeded = await ControlledToolExecutor(registry_for(success), success_audit).execute(
            ToolCall("example_tool", {"value": "public", "secret": "sensitive-input"}),
            context(),
        )
        assert succeeded.status is ToolExecutionStatus.SUCCEEDED
        assert cast(ExampleOutput, succeeded.output).private_result == "sensitive-output"
        assert success_audit.attempts[0].arguments_redacted["secret"] == "[REDACTED]"
        assert success_audit.attempts[0].result_redacted == {
            "value": "public",
            "private_result": "[REDACTED]",
        }

        async def rejected(_arguments: BaseModel) -> BaseModel:
            raise VerificationFailed("verification_failed", "private diagnostic")

        rejected_audit = MemoryAudit()
        result = await ControlledToolExecutor(registry_for(rejected), rejected_audit).execute(
            ToolCall("example_tool", {"value": "public", "secret": "sensitive-input"}),
            context(),
        )
        assert result.status is ToolExecutionStatus.REJECTED
        assert result.error_code == "verification_failed"
        assert rejected_audit.attempts[0].result_redacted is None
        assert "private diagnostic" not in str(rejected_audit.attempts[0])

    asyncio.run(exercise())


def test_executor_times_out_and_fails_closed_when_audit_is_unavailable() -> None:
    async def exercise() -> None:
        async def slow(_arguments: BaseModel) -> BaseModel:
            await asyncio.sleep(0.2)
            return ExampleOutput(value="late", private_result="late")

        audit = MemoryAudit()
        result = await ControlledToolExecutor(
            registry_for(slow, effect=ToolEffect.READ), audit
        ).execute(
            ToolCall("example_tool", {"value": "safe", "secret": "secret"}),
            context(confirmed=False),
        )
        assert result.status is ToolExecutionStatus.TIMED_OUT
        assert result.error_code == "tool_execution_timed_out"
        assert audit.attempts[0].result_status is ToolExecutionStatus.TIMED_OUT

        async def success(_arguments: BaseModel) -> BaseModel:
            return ExampleOutput(value="safe", private_result="private")

        with pytest.raises(ToolAuditError):
            await ControlledToolExecutor(registry_for(success), MemoryAudit(fail=True)).execute(
                ToolCall("example_tool", {"value": "safe", "secret": "secret"}),
                context(),
            )

    asyncio.run(exercise())


def test_registry_rejects_unconfirmed_write_configuration() -> None:
    with pytest.raises(ToolConfigurationError, match="requires confirmation"):
        ToolDefinition(
            name="unsafe_write",
            description="This deliberately invalid write definition has no confirmation policy.",
            input_model=ExampleInput,
            output_model=ExampleOutput,
            allowed_callers=frozenset({ToolCaller.ASSISTANT}),
            timeout_ms=100,
            effect=ToolEffect.WRITE,
            requires_confirmation=False,
        )
