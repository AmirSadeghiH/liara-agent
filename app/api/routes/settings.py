"""Configuration status and connectivity tests (never exposes secrets)."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Request

from app.api.deps import get_container
from app.core.errors import AppError
from app.core.security import require_app_auth

router = APIRouter(prefix="/api/settings", tags=["settings"],
                   dependencies=[Depends(require_app_auth)])


@router.get("/status", summary="Configuration and capability status")
async def status(request: Request) -> dict[str, Any]:
    container = get_container(request)
    return {
        **container.settings.public_status(),
        "adapter": container.adapter.describe(),
        "coding_agent_status": await container.coding.status_report(),
        "approval_counts": {
            "pending": await container.repo.count_pending_approvals(),
        },
        "database": {
            "url_scheme": container.settings.database_url.split("://")[0],
            "path": container.settings.database_url.split("///")[-1],
        },
    }


@router.post("/test-liara-connection", summary="Test Liara connectivity and credentials")
async def test_liara_connection(request: Request) -> dict[str, Any]:
    container = get_container(request)
    try:
        result = await container.adapter.ping()
        await container.audit.record(
            "settings.connection_tested", outcome="ok",
            detail={"mode": container.adapter.mode, "project_count": result.get("project_count")},
        )
        return {
            "ok": True,
            "mode": container.adapter.mode,
            "simulated": container.adapter.simulated,
            "project_count": result.get("project_count"),
            "latency_ms": result.get("latency_ms"),
            "message": result.get("message"),
        }
    except AppError as exc:
        await container.audit.record(
            "settings.connection_tested", outcome="failed", detail={"code": exc.code},
        )
        return {
            "ok": False,
            "mode": container.adapter.mode,
            "simulated": container.adapter.simulated,
            "error": {"code": exc.code, "message": exc.message},
        }
