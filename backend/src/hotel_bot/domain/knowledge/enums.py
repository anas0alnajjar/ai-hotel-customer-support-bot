"""Knowledge workflow and derived-index lifecycle enumerations."""

from enum import StrEnum


class KnowledgeStatus(StrEnum):
    DRAFT = "draft"
    APPROVED = "approved"
    ARCHIVED = "archived"


class IndexStatus(StrEnum):
    BUILDING = "building"
    ACTIVE = "active"
    FAILED = "failed"
    RETIRED = "retired"


class SourceFormat(StrEnum):
    PLAIN_TEXT = "plain_text"
    MARKDOWN = "markdown"
