"""Post-deployment verification (health check + fresh log evidence).

A deployment is never reported as successful without verification.  When a
health-check URL is not configured, the result is ``unverified`` - not
``verified``.
"""

from __future__ import annotations

import asyncio
import logging
import time
from datetime import timedelta
from typing import Any

import httpx

from app.core.config import Settings
from app.core.security import validate_healthcheck_url
from app.core.utils import iso, utcnow
from app.liara.adapter import LiaraAdapter
from app.liara.mock_adapter import MockLiaraAdapter
from app.services.audit_service import AuditService

logger = logging.getLogger(__name__)


class VerificationService:
    def __init__(
        self,
        adapter: LiaraAdapter,
        settings: Settings,
        audit: AuditService,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
        sleep=asyncio.sleep,
    ) -> None:
        self.adapter = adapter
        self.settings = settings
        self.audit = audit
        self._transport = transport
        self._sleep = sleep

    async def verify(self, *, workflow_id: str, project: str,
                     deployment: dict[str, Any] | None = None) -> dict[str, Any]:
        started = time.perf_counter()
        if isinstance(self.adapter, MockLiaraAdapter) or self.adapter.simulated:
            result = self.adapter.simulated_health(project, self.settings.deploy_healthcheck_url or None)
            result.update({
                "status": "verified" if result["ok"] else "failed",
                "expected_status": self.settings.deploy_healthcheck_expect_status,
                "checked_at": iso(),
                "duration_ms": int((time.perf_counter() - started) * 1000),
                "note": "شبیه‌سازی‌شده: هیچ درخواست شبکه‌ای ارسال نشد.",
            })
            logs = await self._post_deploy_logs(project)
            result["log_evidence"] = logs
            await self._audit(workflow_id, project, result)
            return result

        url = self.settings.deploy_healthcheck_url
        if not url:
            result = {
                "status": "unverified",
                "ok": False,
                "simulated": False,
                "url": None,
                "expected_status": self.settings.deploy_healthcheck_expect_status,
                "observed_status": None,
                "attempts": 0,
                "reason": (
                    "DEPLOY_HEALTHCHECK_URL is not configured. Liara does not expose a documented "
                    "health endpoint for this project, so the result cannot be verified."
                ),
                "checked_at": iso(),
                "duration_ms": int((time.perf_counter() - started) * 1000),
            }
            result["log_evidence"] = await self._post_deploy_logs(project)
            await self._audit(workflow_id, project, result)
            return result

        try:
            validate_healthcheck_url(url)
        except Exception as exc:
            result = {
                "status": "unverified", "ok": False, "simulated": False, "url": url,
                "expected_status": self.settings.deploy_healthcheck_expect_status,
                "observed_status": None, "attempts": 0,
                "reason": getattr(exc, "message", str(exc)),
                "checked_at": iso(),
                "duration_ms": int((time.perf_counter() - started) * 1000),
            }
            await self._audit(workflow_id, project, result)
            return result

        attempts = max(1, self.settings.deploy_healthcheck_retries)
        observed: int | None = None
        error: str | None = None
        async with httpx.AsyncClient(
            transport=self._transport,
            timeout=self.settings.deploy_healthcheck_timeout_seconds,
            follow_redirects=True,
        ) as client:
            for attempt in range(1, attempts + 1):
                try:
                    response = await client.get(url)
                    observed = response.status_code
                    if observed == self.settings.deploy_healthcheck_expect_status:
                        break
                except httpx.HTTPError as exc:
                    error = type(exc).__name__
                if attempt < attempts:
                    await self._sleep(self.settings.deploy_healthcheck_interval_seconds)

        ok = observed == self.settings.deploy_healthcheck_expect_status
        logs = await self._post_deploy_logs(project)
        result = {
            "status": "verified" if ok else "failed",
            "ok": ok,
            "simulated": False,
            "url": url,
            "expected_status": self.settings.deploy_healthcheck_expect_status,
            "observed_status": observed,
            "attempts": attempts,
            "error": error,
            "reason": None if ok else (
                f"Health check returned {observed}, expected "
                f"{self.settings.deploy_healthcheck_expect_status}."
            ),
            "checked_at": iso(),
            "duration_ms": int((time.perf_counter() - started) * 1000),
            "log_evidence": logs,
        }
        await self._audit(workflow_id, project, result)
        return result

    async def _post_deploy_logs(self, project: str) -> dict[str, Any]:
        try:
            entries = await self.adapter.get_logs(
                project, since=utcnow() - timedelta(minutes=15)
            )
            error_lines = [e for e in entries if e.level in {"error", "critical"}]
            return {
                "checked": len(entries),
                "errors": len(error_lines),
                "samples": [e.message[:200] for e in error_lines[-3:]],
            }
        except Exception as exc:
            return {"checked": 0, "errors": None, "unavailable_reason": type(exc).__name__}

    async def _audit(self, workflow_id: str, project: str, result: dict[str, Any]) -> None:
        await self.audit.record(
            "deployment.verified",
            target=workflow_id,
            outcome=str(result.get("status")),
            detail={"project": project, "observed_status": result.get("observed_status"),
                    "simulated": result.get("simulated")},
            trace_id=workflow_id,
        )
