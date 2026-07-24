"""Closed allow-list registry with strict schemas and provider-neutral declarations."""

import re
from dataclasses import dataclass

from pydantic import BaseModel

from hotel_bot.domain.tools.enums import ToolAuditPolicy, ToolCaller, ToolEffect
from hotel_bot.domain.tools.errors import ToolConfigurationError
from hotel_bot.domain.tools.models import RegisteredTool

TOOL_NAME_PATTERN = re.compile(r"^[a-z][a-z0-9_]{2,63}$")


@dataclass(frozen=True, slots=True)
class ToolDefinition:
    name: str
    description: str
    input_model: type[BaseModel]
    output_model: type[BaseModel]
    allowed_callers: frozenset[ToolCaller]
    timeout_ms: int
    effect: ToolEffect
    requires_confirmation: bool
    sensitive_argument_fields: frozenset[str] = frozenset()
    sensitive_result_fields: frozenset[str] = frozenset()
    audit_policy: ToolAuditPolicy = ToolAuditPolicy.ALWAYS

    def __post_init__(self) -> None:
        if not TOOL_NAME_PATTERN.fullmatch(self.name):
            raise ToolConfigurationError(f"invalid tool name: {self.name}")
        if not 20 <= len(self.description.strip()) <= 500:
            raise ToolConfigurationError(f"invalid description for tool: {self.name}")
        if not self.allowed_callers:
            raise ToolConfigurationError(f"tool has no authorized caller: {self.name}")
        if not 100 <= self.timeout_ms <= 30_000:
            raise ToolConfigurationError(f"invalid timeout for tool: {self.name}")
        if self.effect is ToolEffect.WRITE and not self.requires_confirmation:
            raise ToolConfigurationError(f"write tool requires confirmation: {self.name}")
        input_fields = set(self.input_model.model_fields)
        output_fields = set(self.output_model.model_fields)
        if not self.sensitive_argument_fields <= input_fields:
            raise ToolConfigurationError(f"unknown sensitive argument field: {self.name}")
        if not self.sensitive_result_fields <= output_fields:
            raise ToolConfigurationError(f"unknown sensitive result field: {self.name}")

    def declaration(self) -> dict[str, object]:
        return {
            "name": self.name,
            "description": self.description,
            "parameters": self.input_model.model_json_schema(mode="validation"),
        }


class ToolRegistry:
    def __init__(self, tools: tuple[RegisteredTool, ...]) -> None:
        by_name: dict[str, RegisteredTool] = {}
        for tool in tools:
            if tool.definition.name in by_name:
                raise ToolConfigurationError(f"duplicate tool: {tool.definition.name}")
            by_name[tool.definition.name] = tool
        if not by_name:
            raise ToolConfigurationError("tool registry cannot be empty")
        self._by_name = by_name

    def resolve(self, name: str) -> RegisteredTool | None:
        return self._by_name.get(name)

    @property
    def definitions(self) -> tuple[ToolDefinition, ...]:
        return tuple(tool.definition for tool in self._by_name.values())

    def declarations(self) -> tuple[dict[str, object], ...]:
        return tuple(definition.declaration() for definition in self.definitions)
