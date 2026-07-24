"""LLM execution and grounded-answer enumerations."""

from enum import StrEnum


class LLMRunStatus(StrEnum):
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    TIMED_OUT = "timed_out"


class LLMRequestKind(StrEnum):
    TOOL_PROPOSAL = "tool_proposal"
    FINAL_ANSWER = "final_answer"


class AnswerBasis(StrEnum):
    CONTROLLED = "controlled"
    KNOWLEDGE = "knowledge"
    TOOL = "tool"
    UNAVAILABLE = "unavailable"
    ESCALATION = "escalation"
