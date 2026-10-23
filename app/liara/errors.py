"""Liara-specific errors.

These are translated to :class:`app.core.errors.AppError` at the service
boundary so the rest of the application never depends on HTTP details.
"""

from __future__ import annotations


class LiaraError(Exception):
    """Base class for every Liara failure."""

    code = "liara_error"
    retryable = False

    def __init__(self, message: str, *, status_code: int | None = None,
                 details: dict | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code
        self.details = details or {}

    def __str__(self) -> str:  # pragma: no cover - trivial
        return self.message


class LiaraAuthError(LiaraError):
    code = "liara_auth_error"


class LiaraForbiddenError(LiaraAuthError):
    code = "liara_forbidden"


class LiaraNotFoundError(LiaraError):
    code = "liara_not_found"


class LiaraConflictError(LiaraError):
    code = "liara_conflict"


class LiaraValidationError(LiaraError):
    code = "liara_validation_error"


class LiaraRateLimitError(LiaraError):
    code = "liara_rate_limited"
    retryable = True


class LiaraServerError(LiaraError):
    code = "liara_server_error"
    retryable = True


class LiaraNetworkError(LiaraError):
    code = "liara_network_error"
    retryable = True


class LiaraTimeoutError(LiaraNetworkError):
    code = "liara_timeout"


class LiaraResponseError(LiaraError):
    code = "liara_invalid_response"
