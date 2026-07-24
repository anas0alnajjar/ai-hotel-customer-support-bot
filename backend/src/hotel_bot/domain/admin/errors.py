"""Controlled administration errors safe for HTTP mapping."""


class AdminError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class AdminAuthenticationError(AdminError):
    """Authentication failed without disclosing which credential was wrong."""


class AdminAuthorizationError(AdminError):
    """An authenticated principal lacks the required role."""


class AdminRateLimitError(AdminError):
    """A login identifier exceeded the bounded attempt policy."""


class AdminResourceNotFoundError(AdminError):
    """An administration resource is unavailable to the caller."""


class AdminValidationError(AdminError):
    """An administration command violates an application invariant."""
