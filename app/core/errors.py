"""Typed application errors and their HTTP mapping."""

from __future__ import annotations

from typing import Any


class AppError(Exception):
    """Base class for expected, user-facing errors."""

    code = "internal_error"
    http_status = 500

    def __init__(self, message: str, *, details: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.details = details or {}

    def to_dict(self) -> dict[str, Any]:
        from app.core.logging import redact_value

        body: dict[str, Any] = {"code": self.code, "message": redact_value(self.message)}
        if self.details:
            body["details"] = redact_value(self.details)
        return {"error": body}


class ConfigInvalid(AppError):
    code = "config_invalid"
    http_status = 500


class NotFoundError(AppError):
    code = "not_found"
    http_status = 404


class ValidationError(AppError):
    code = "validation_error"
    http_status = 422


class PolicyViolation(AppError):
    """A security policy (allowlist, writes disabled, TTL, ...) blocked an action."""

    code = "policy_violation"
    http_status = 403


class AuthRequired(AppError):
    code = "auth_required"
    http_status = 401


class ConflictError(AppError):
    code = "conflict"
    http_status = 409


class UpstreamUnavailable(AppError):
    code = "upstream_unavailable"
    http_status = 502


class WorkflowBusy(AppError):
    code = "workflow_busy"
    http_status = 409
