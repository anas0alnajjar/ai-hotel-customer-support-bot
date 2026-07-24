"""Provider-neutral controlled-tool states and policies."""

from enum import StrEnum


class ToolCaller(StrEnum):
    ASSISTANT = "assistant"
    ADMIN = "admin"
    SYSTEM = "system"


class ToolEffect(StrEnum):
    READ = "read"
    WRITE = "write"


class ToolAuditPolicy(StrEnum):
    ALWAYS = "always"


class ToolExecutionStatus(StrEnum):
    SUCCEEDED = "succeeded"
    REJECTED = "rejected"
    FAILED = "failed"
    TIMED_OUT = "timed_out"
