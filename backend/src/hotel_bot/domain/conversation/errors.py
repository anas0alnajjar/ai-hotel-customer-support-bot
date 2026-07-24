"""Stable conversation-domain errors for API and channel adapters."""


class ConversationError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class IdempotencyConflict(ConversationError):
    """The same external update identifier was reused for a different payload."""


class ConversationNotFound(ConversationError):
    """The requested conversation does not exist or is unavailable."""
