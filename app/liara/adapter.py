"""Liara adapter contract.

``MockLiaraAdapter`` (demo mode) and ``LiveLiaraAdapter`` implement exactly the
same interface so that workflows, services, MCP tools and the UI never branch on
the data source - only on the explicit ``mode``/``simulated`` flags that are
surfaced in every report.
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from datetime import datetime
from typing import Any, Literal

from app.core.config import Settings
from app.core.errors import AuthRequired, PolicyViolation, UpstreamUnavailable
from app.core.utils import utcnow
from app.liara.client import LiaraClient
from app.liara.errors import LiaraAuthError, LiaraError, LiaraNotFoundError
from app.liara.schemas import (
    LogEntry,
    MetricSeries,
    ProjectDetails,
    ProjectSummary,
    ReleasePage,
)

logger = logging.getLogger(__name__)

AdapterMode = Literal["demo", "live"]


def to_app_error(exc: LiaraError) -> Exception:
    """Translate a Liara error into a user-facing application error."""
    from app.core.errors import NotFoundError
    from app.core.errors import ValidationError as AppValidationError

    if isinstance(exc, LiaraNotFoundError):
        return NotFoundError(exc.message, details=exc.details)
    if isinstance(exc, LiaraAuthError):
        return AuthRequired(
            "Liara authentication failed. Check LIARA_API_TOKEN and LIARA_AUTH_SCHEME.", details=exc.details
        )
    if isinstance(exc, LiaraError) and exc.code in {"liara_validation_error"}:
        return AppValidationError(exc.message, details=exc.details)
    return UpstreamUnavailable(exc.message, details=exc.details)


class LiaraAdapter(ABC):
    """Read/write contract shared by the demo and live adapters."""

    mode: AdapterMode = "demo"
    simulated: bool = False

    @abstractmethod
    async def list_projects(self) -> list[ProjectSummary]: ...

    @abstractmethod
    async def get_project(self, name: str) -> ProjectDetails: ...

    @abstractmethod
    async def get_logs(self, name: str, *, since: datetime | None = None) -> list[LogEntry]: ...

    @abstractmethod
    async def get_cpu_metrics(self, name: str, *, since: float | None = None) -> MetricSeries: ...

    @abstractmethod
    async def get_memory_metrics(self, name: str, *, since: float | None = None) -> MetricSeries: ...

    @abstractmethod
    async def get_releases(self, name: str, *, page: int = 1, count: int = 10) -> ReleasePage: ...

    @abstractmethod
    async def upload_source(self, name: str, *, archive: bytes, filename: str) -> str: ...

    @abstractmethod
    async def create_release(
        self, name: str, *, source_id: str, port: int, project_type: str
    ) -> str: ...

    async def ping(self) -> dict[str, Any]:
        projects = await self.list_projects()
        return {"ok": True, "project_count": len(projects)}

    async def aclose(self) -> None:  # pragma: no cover - overridden by live adapter
        return None

    def describe(self) -> dict[str, Any]:
        return {"mode": self.mode, "simulated": self.simulated}


class LiveLiaraAdapter(LiaraAdapter):
    """Thin, policy-free wrapper around :class:`LiaraClient`.

    Authorisation for write operations is intentionally **not** implemented
    here: it lives in the service layer so that it applies to every caller.
    """

    mode: AdapterMode = "live"
    simulated: bool = False

    def __init__(self, settings: Settings, *, audit_hook=None, transport=None) -> None:
        self.settings = settings
        self.client = LiaraClient(settings, audit_hook=audit_hook, transport=transport)

    def _ensure_token(self) -> None:
        if not self.settings.has_liara_token:
            raise AuthRequired(
                "No Liara API token configured. Set LIARA_API_TOKEN to use Live mode.",
                details={"reason": "missing_token"},
            )
        if self.settings.demo_mode:
            raise PolicyViolation(
                "Live adapter cannot be used while DEMO_MODE=true.",
                details={"reason": "demo_mode_enabled"},
            )

    async def list_projects(self) -> list[ProjectSummary]:
        self._ensure_token()
        try:
            return await self.client.list_projects()
        except LiaraError as exc:
            raise to_app_error(exc) from exc

    async def get_project(self, name: str) -> ProjectDetails:
        self._ensure_token()
        try:
            return await self.client.get_project(name)
        except LiaraError as exc:
            raise to_app_error(exc) from exc

    async def get_logs(self, name: str, *, since: datetime | None = None) -> list[LogEntry]:
        self._ensure_token()
        try:
            return await self.client.get_logs(name, since=since or utcnow())
        except LiaraError as exc:
            raise to_app_error(exc) from exc

    async def get_cpu_metrics(self, name: str, *, since: float | None = None) -> MetricSeries:
        self._ensure_token()
        try:
            return await self.client.get_cpu_metrics(name, since=since)
        except LiaraError as exc:
            raise to_app_error(exc) from exc

    async def get_memory_metrics(self, name: str, *, since: float | None = None) -> MetricSeries:
        self._ensure_token()
        try:
            return await self.client.get_memory_metrics(name, since=since)
        except LiaraError as exc:
            raise to_app_error(exc) from exc

    async def get_releases(self, name: str, *, page: int = 1, count: int = 10) -> ReleasePage:
        self._ensure_token()
        try:
            return await self.client.get_releases(name, page=page, count=count)
        except LiaraError as exc:
            raise to_app_error(exc) from exc

    async def upload_source(self, name: str, *, archive: bytes, filename: str) -> str:
        self._ensure_token()
        try:
            return await self.client.upload_source(name, archive=archive, filename=filename)
        except LiaraError as exc:
            raise to_app_error(exc) from exc

    async def create_release(
        self, name: str, *, source_id: str, port: int, project_type: str
    ) -> str:
        self._ensure_token()
        try:
            return await self.client.create_release(
                name, source_id=source_id, port=port, project_type=project_type
            )
        except LiaraError as exc:
            raise to_app_error(exc) from exc

    async def ping(self) -> dict[str, Any]:
        self._ensure_token()
        try:
            result = await self.client.ping()
            return {**result, "mode": "live", "simulated": False}
        except LiaraError as exc:
            raise to_app_error(exc) from exc

    async def aclose(self) -> None:
        await self.client.aclose()
