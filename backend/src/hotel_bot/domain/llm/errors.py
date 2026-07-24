"""Controlled LLM boundary failures."""


class LLMError(RuntimeError):
    code = "llm_error"


class LLMUnavailableError(LLMError):
    code = "llm_unavailable"


class LLMTimeoutError(LLMError):
    code = "llm_timeout"


class LLMContractError(LLMError):
    code = "llm_contract_invalid"


class LLMBudgetExceededError(LLMError):
    code = "llm_budget_exceeded"


class LLMAuditError(LLMError):
    code = "llm_audit_failed"
