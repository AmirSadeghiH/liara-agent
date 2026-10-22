"""Centralised, testable HTTP client for the Liara PaaS API.

Implemented endpoints (verified against developers.liara.ir on 2026-10-22):

============================  =============================================
GET  /v1/projects             list projects
GET  /v1/projects/{name}      project details
GET  /v1/projects/{name}/logs logs (``since`` string query, required)
GET  /v1/projects/{name}/metrics/cpu      ``since`` epoch seconds
GET  /v1/projects/{name}/metrics/memory   ``since`` epoch seconds
GET  /v1/projects/{name}/metrics/summary
GET  /v1/projects/{name}/releases         ``page`` & ``count`` required
POST /v2/projects/{name}/sources          multipart ``file`` (.gz)
POST /v2/projects/{name}/releases         JSON ``{sourceID, port, type}``
============================  =============================================

Authentication: the OpenAPI security schemes declare both ``jwt`` (apiKey in
the ``Authorization`` header) and ``bearerAuth``, while every documented
request example sends the raw token as ``Authorization: <api-key>``.  We follow
the documented request examples by default (``LIARA_AUTH_SCHEME=token``) and
support ``Bearer`` as an opt-in.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable
from datetime import datetime
from typing import Any

import httpx
from pydantic import ValidationError as PydanticValidationError

from app.core.config import Settings
from app.core.logging import redact_text, register_secret
from app.core.utils import iso, utcnow
from app.liara.errors import (
    LiaraAuthError,
    LiaraConflictError,
    LiaraError,
    LiaraForbiddenError,
    LiaraNetworkError,
    LiaraNotFoundError,
    LiaraRateLimitError,
    LiaraResponseError,
    LiaraServerError,
    LiaraTimeoutError,
    LiaraValidationError,
)
from app.liara.schemas import (
    LogEntry,
    MetricSeries,
    ProjectDetails,
    ProjectDetailsEnvelope,
    ProjectList,
    ProjectSummary,
    RawReports,
    ReleaseDeployResult,
    ReleasePage,
    SourceUploadResult,
    parse_metric_reports,
)

logger = logging.getLogger(__name__)

MAX_RETRY_DELAY_SECONDS = 5.0
MAX_ERROR_BODY_CHARS = 400
RETRYABLE_STATUS = {429, 500, 502, 503, 504}


class LiaraClient:
    """Async Liara API client with bounded retries and strict auditing."""

    def __init__(
        self,
        settings: Settings,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
        audit_hook: Callable[[dict[str, Any]], Awaitable[None] | None] | None = None,
        sleep: Callable[[float], Awaitable[None]] | None = None,
    ) -> None:
        self.settings = settings
        register_secret(settings.liara_token)
        self._audit_hook = audit_hook
        self._sleep = sleep or asyncio.sleep
        self._client = httpx.AsyncClient(
            base_url=settings.liara_base_url,
            timeout=httpx.Timeout(settings.liara_request_timeout_seconds),
            transport=transport,
            headers={
                "Accept": "application/json",
                "User-Agent": "LiaraPilot/0.1 (+https://developers.liara.ir)",
            },
            follow_redirects=False,
        )

    # ------------------------------------------------------------------
    # lifecycle
    # ------------------------------------------------------------------
    async def aclose(self) -> None:
        await self._client.aclose()

    async def __aenter__(self) -> LiaraClient:
        return self

    async def __aexit__(self, *exc: object) -> None:
        await self.aclose()

    # ------------------------------------------------------------------
    # auth / request plumbing
    # ------------------------------------------------------------------
    def _auth_header(self) -> str:
        token = self.settings.liara_token
        if self.settings.liara_auth_scheme.lower() == "bearer":
            return f"Bearer {token}"
        return token

    async def _audit(self, record: dict[str, Any]) -> None:
        if not self._audit_hook:
            return
        try:
            result = self._audit_hook(record)
            if asyncio.iscoroutine(result):
                await result
        except Exception:  # pragma: no cover - auditing must never break a call
            logger.warning("audit hook failed", exc_info=True)

    def _map_status(self, response: httpx.Response) -> LiaraError:
        status = response.status_code
        body = redact_text(response.text or "", max_length=MAX_ERROR_BODY_CHARS)
        details = {"status_code": status, "body": body}
        if status in (401,):
            return LiaraAuthError(
                "Liara rejected the API token (401 Unauthorized). Check LIARA_API_TOKEN.",
                status_code=status, details=details,
            )
        if status == 403:
            return LiaraForbiddenError(
                "Liara denied access to this resource (403 Forbidden).",
                status_code=status, details=details,
            )
        if status == 404:
            return LiaraNotFoundError(
                "Project or resource not found on Liara (404).", status_code=status, details=details
            )
        if status == 409:
            return LiaraConflictError(
                "Liara reported a conflict (409).", status_code=status, details=details
            )
        if status in (400, 422):
            return LiaraValidationError(
                f"Liara rejected the request payload ({status}).", status_code=status, details=details
            )
        if status == 429:
            return LiaraRateLimitError(
                "Liara rate limit reached (429).", status_code=status, details=details
            )
        if status >= 500:
            return LiaraServerError(
                f"Liara service error ({status}).", status_code=status, details=details
            )
        return LiaraError(
            f"Unexpected Liara response ({status}).", status_code=status, details=details
        )

    def _retry_after(self, response: httpx.Response, attempt: int) -> float:
        header = response.headers.get("retry-after")
        if header:
            try:
                return min(MAX_RETRY_DELAY_SECONDS, max(0.0, float(header)))
            except ValueError:
                pass
        return min(MAX_RETRY_DELAY_SECONDS, 0.5 * (2**attempt))

    async def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json_body: dict[str, Any] | None = None,
        files: dict[str, Any] | None = None,
        idempotent: bool = True,
        expected_status: int = 200,
    ) -> Any:
        assert path.startswith("/v1/") or path.startswith("/v2/"), "Only documented API paths are allowed"
        url = self.settings.liara_base_url + path
        headers = {"Authorization": self._auth_header()}
        max_attempts = self.settings.liara_max_retries + 1 if idempotent else 1
        last_error: LiaraError | None = None

        for attempt in range(max_attempts):
            started = time.perf_counter()
            record: dict[str, Any] = {
                "at": iso(),
                "method": method,
                "path": path,
                "attempt": attempt + 1,
                "endpoint": f"{method} {path}",
            }
            try:
                response = await self._client.request(
                    method, url, params=params, json=json_body, files=files, headers=headers
                )
            except httpx.TimeoutException as exc:
                record.update({"outcome": "timeout", "duration_ms": int((time.perf_counter() - started) * 1000)})
                await self._audit(record)
                last_error = LiaraTimeoutError(
                    f"Liara request timed out after {self.settings.liara_request_timeout_seconds}s.",
                    details={"path": path},
                )
                if attempt + 1 < max_attempts:
                    await self._sleep(min(MAX_RETRY_DELAY_SECONDS, 0.5 * (2**attempt)))
                    continue
                raise last_error from exc
            except httpx.HTTPError as exc:
                record.update({"outcome": "network_error",
                               "duration_ms": int((time.perf_counter() - started) * 1000)})
                await self._audit(record)
                last_error = LiaraNetworkError(
                    f"Network error while calling Liara: {type(exc).__name__}.", details={"path": path}
                )
                if attempt + 1 < max_attempts:
                    await self._sleep(min(MAX_RETRY_DELAY_SECONDS, 0.5 * (2**attempt)))
                    continue
                raise last_error from exc

            duration_ms = int((time.perf_counter() - started) * 1000)
            record.update({"status_code": response.status_code, "duration_ms": duration_ms})

            if response.status_code == expected_status:
                record["outcome"] = "ok"
                await self._audit(record)
                if expected_status == 204 or not response.content:
                    return None
                try:
                    return response.json()
                except ValueError as exc:
                    raise LiaraResponseError(
                        "Liara returned a non-JSON response.", status_code=response.status_code
                    ) from exc

            error = self._map_status(response)
            record.update({"outcome": "error", "error_code": error.code})
            await self._audit(record)

            if response.status_code in RETRYABLE_STATUS and attempt + 1 < max_attempts:
                await self._sleep(self._retry_after(response, attempt))
                last_error = error
                continue
            raise error

        raise last_error or LiaraError("Liara request failed.")  # pragma: no cover

    # ------------------------------------------------------------------
    # read operations
    # ------------------------------------------------------------------
    async def list_projects(self) -> list[ProjectSummary]:
        payload = await self._request("GET", "/v1/projects")
        try:
            parsed = ProjectList.model_validate(payload or {})
        except PydanticValidationError as exc:
            raise LiaraResponseError(
                "Unexpected response shape for GET /v1/projects.", details={"errors": str(exc)[:400]}
            ) from exc
        return parsed.projects

    async def get_project(self, name: str) -> ProjectDetails:
        payload = await self._request("GET", f"/v1/projects/{name}")
        try:
            return ProjectDetailsEnvelope.model_validate(payload or {}).project
        except PydanticValidationError as exc:
            raise LiaraResponseError(
                f"Unexpected response shape for GET /v1/projects/{name}.",
                details={"errors": str(exc)[:400]},
            ) from exc

    async def get_logs(
        self, name: str, *, since: datetime | None = None, entry_limit: int = 200
    ) -> list[LogEntry]:
        since_dt = since or utcnow()
        # The docs require a string ``since`` but do not specify the format.
        # ISO-8601 is used first; if Liara rejects it we retry once with epoch
        # seconds (see docs/liara-api.md -> "Known documentation gaps").
        try:
            payload = await self._request(
                "GET", f"/v1/projects/{name}/logs",
                params={"since": iso(since_dt)},
            )
        except LiaraValidationError:
            payload = await self._request(
                "GET", f"/v1/projects/{name}/logs",
                params={"since": str(int(since_dt.timestamp()))},
            )
        if payload is None:
            return []
        if not isinstance(payload, list):
            raise LiaraResponseError(
                "Unexpected response shape for GET /v1/projects/{name}/logs: expected a JSON array."
            )
        entries: list[LogEntry] = []
        for raw in payload:
            if not isinstance(raw, dict):
                continue
            try:
                entries.append(LogEntry.model_validate(raw))
            except PydanticValidationError:
                continue
        return entries[-entry_limit:]

    async def _metrics(self, name: str, kind: str, since: float) -> MetricSeries:
        payload = await self._request(
            "GET", f"/v1/projects/{name}/metrics/{kind}", params={"since": since}
        )
        try:
            RawReports.model_validate(payload or {})
        except PydanticValidationError as exc:
            raise LiaraResponseError(
                f"Unexpected response shape for metrics/{kind}.", details={"errors": str(exc)[:400]}
            ) from exc
        return parse_metric_reports(payload or {}, name=kind, since=since)

    async def get_cpu_metrics(self, name: str, *, since: float | None = None) -> MetricSeries:
        since_ts = since if since is not None else (utcnow().timestamp() - 3600)
        return await self._metrics(name, "cpu", since_ts)

    async def get_memory_metrics(self, name: str, *, since: float | None = None) -> MetricSeries:
        since_ts = since if since is not None else (utcnow().timestamp() - 3600)
        return await self._metrics(name, "memory", since_ts)

    async def get_summary(self, name: str) -> dict[str, Any]:
        payload = await self._request("GET", f"/v1/projects/{name}/metrics/summary")
        return payload or {}

    async def get_releases(self, name: str, *, page: int = 1, count: int = 10) -> ReleasePage:
        payload = await self._request(
            "GET", f"/v1/projects/{name}/releases", params={"page": page, "count": count}
        )
        try:
            return ReleasePage.model_validate(payload or {})
        except PydanticValidationError as exc:
            raise LiaraResponseError(
                "Unexpected response shape for GET /v1/projects/{name}/releases.",
                details={"errors": str(exc)[:400]},
            ) from exc

    # ------------------------------------------------------------------
    # write operations (never retried: they are not idempotent)
    # ------------------------------------------------------------------
    async def upload_source(self, name: str, *, archive: bytes, filename: str) -> str:
        if not archive:
            raise LiaraValidationError("Source archive is empty; refusing to upload.")
        payload = await self._request(
            "POST", f"/v2/projects/{name}/sources",
            files={"file": (filename, archive, "application/gzip")},
            idempotent=False,
        )
        try:
            return SourceUploadResult.model_validate(payload or {}).source_id
        except PydanticValidationError as exc:
            raise LiaraResponseError(
                "Liara did not return a sourceID for the uploaded archive.",
                details={"errors": str(exc)[:400]},
            ) from exc

    async def create_release(
        self, name: str, *, source_id: str, port: int, project_type: str
    ) -> str:
        if not source_id:
            raise LiaraValidationError("sourceID is required to create a release.")
        if not (1 <= int(port) <= 65535):
            raise LiaraValidationError("port must be between 1 and 65535.")
        if not project_type:
            raise LiaraValidationError("project type is required to create a release.")
        payload = await self._request(
            "POST", f"/v2/projects/{name}/releases",
            json_body={"sourceID": source_id, "port": int(port), "type": project_type},
            idempotent=False,
        )
        try:
            return ReleaseDeployResult.model_validate(payload or {}).release_id
        except PydanticValidationError as exc:
            raise LiaraResponseError(
                "Liara did not return a releaseID for the release request.",
                details={"errors": str(exc)[:400]},
            ) from exc

    async def ping(self) -> dict[str, Any]:
        """Connectivity/auth probe used by 'test Liara connection'."""
        started = time.perf_counter()
        projects = await self.list_projects()
        return {
            "ok": True,
            "project_count": len(projects),
            "latency_ms": int((time.perf_counter() - started) * 1000),
        }
