"""LLM execution and grounded-answer enumerations."""

from enum import StrEnum


class LLMRunStatus(StrEnum):
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    TIMED_OUT = "timed_out"


class LLMRequestKind(StrEnum):
    HYBRID_INTENT_ANALYSIS = "hybrid_intent_analysis"
    KNOWLEDGE_QUERY_REWRITE = "knowledge_query_rewrite"
    TOOL_PROPOSAL = "tool_proposal"
    FINAL_ANSWER = "final_answer"


class AnswerBasis(StrEnum):
    CONTROLLED = "controlled"
    KNOWLEDGE = "knowledge"
    TOOL = "tool"
    UNAVAILABLE = "unavailable"
    ESCALATION = "escalation"
