"""Stable knowledge and retrieval domain failures."""


class KnowledgeError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class KnowledgeAuthorizationError(KnowledgeError):
    pass


class KnowledgeValidationError(KnowledgeError):
    pass


class IndexUnavailableError(KnowledgeError):
    pass
