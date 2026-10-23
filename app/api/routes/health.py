"""Health and readiness endpoints (secret-free)."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Request

from app.api.deps import get_container
from app.core.security import require_app_auth

router = APIRouter(tags=["health"])


@router.get("/api/health", summary="Liveness probe")
async def health(request: Request) -> dict[str, Any]:
    container = get_container(request)
    return await container.health()


@router.get("/api/readiness", summary="Readiness and live-mode prerequisites",
            dependencies=[Depends(require_app_auth)])
async def readiness(request: Request) -> dict[str, Any]:
    container = get_container(request)
    return await container.readiness()
