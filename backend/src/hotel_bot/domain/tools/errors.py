"""Stable failures for controlled tool registration and auditing."""


class ToolConfigurationError(ValueError):
    pass


class ToolAuditError(RuntimeError):
    pass
