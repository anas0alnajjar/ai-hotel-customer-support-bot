"""Deterministic text/Markdown normalization and bounded overlapping chunking."""

import re

from hotel_bot.domain.knowledge.errors import KnowledgeValidationError

WHITESPACE = re.compile(r"[ \t]+")
EXCESS_NEWLINES = re.compile(r"\n{3,}")


def normalize_content(content: str) -> str:
    normalized = content.replace("\r\n", "\n").replace("\r", "\n").strip()
    lines = [WHITESPACE.sub(" ", line).strip() for line in normalized.splitlines()]
    return EXCESS_NEWLINES.sub("\n\n", "\n".join(lines)).strip()


def validate_content(content: str) -> str:
    normalized = normalize_content(content)
    if len(normalized) < 20:
        raise KnowledgeValidationError(
            "knowledge_content_too_short", "knowledge content must contain at least 20 characters"
        )
    if len(normalized) > 200_000:
        raise KnowledgeValidationError(
            "knowledge_content_too_large", "knowledge content exceeds 200000 characters"
        )
    if "\x00" in normalized:
        raise KnowledgeValidationError(
            "knowledge_content_invalid", "knowledge content contains a null byte"
        )
    return normalized


def chunk_text(content: str, *, max_chars: int, overlap_chars: int) -> tuple[str, ...]:
    if max_chars < 50 or overlap_chars < 0 or overlap_chars >= max_chars:
        raise ValueError("invalid chunk configuration")
    normalized = validate_content(content)
    if len(normalized) <= max_chars:
        return (normalized,)

    chunks: list[str] = []
    start = 0
    while start < len(normalized):
        hard_end = min(len(normalized), start + max_chars)
        end = hard_end
        if hard_end < len(normalized):
            boundary = max(
                normalized.rfind("\n\n", start + max_chars // 2, hard_end),
                normalized.rfind(". ", start + max_chars // 2, hard_end),
                normalized.rfind("، ", start + max_chars // 2, hard_end),
                normalized.rfind(" ", start + max_chars // 2, hard_end),
            )
            if boundary > start:
                end = boundary + 1
        chunk = normalized[start:end].strip()
        if chunk:
            chunks.append(chunk)
        if end >= len(normalized):
            break
        next_start = max(0, end - overlap_chars)
        while next_start < end and normalized[next_start].isalnum() and next_start > 0:
            next_start -= 1
        start = next_start if next_start > start else end
    return tuple(chunks)
