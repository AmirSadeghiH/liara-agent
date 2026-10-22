"""Demo scenario endpoints (available only while DEMO_MODE=true)."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Request, status

from app.api.deps import get_container
from app.api.schemas import DemoRunRequest
from app.core.security import require_app_auth

router = APIRouter(prefix="/api/demo", tags=["demo"],
                   dependencies=[Depends(require_app_auth)])


@router.get("/scenarios", summary="List built-in demo scenarios")
async def scenarios(request: Request) -> dict[str, Any]:
    container = get_container(request)
    return {
        "demo_mode": container.settings.demo_mode,
        "simulated": container.adapter.simulated,
        "scenarios": container.demo.scenarios(),
    }


@router.post("/run-scenario", status_code=status.HTTP_202_ACCEPTED,
             summary="Run the full demo scenario (diagnosis → repair → deploy → health)")
async def run_scenario(payload: DemoRunRequest, request: Request) -> dict[str, Any]:
    container = get_container(request)
    result = await container.demo.run(
        scenario=payload.scenario, project=payload.project,
        request_text=payload.request, actor="demo",
    )
    return {
        **result,
        "notice": (
            "این سناریو شبیه‌سازی‌شده است: هیچ تغییری در api.liara.ir ثبت نمی‌شود."
            if container.adapter.simulated else None
        ),
    }
