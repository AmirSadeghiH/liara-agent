"""Read-only project, log and metric endpoints."""

from __future__ import annotations

import asyncio
from datetime import timedelta
from typing import Any

from fastapi import APIRouter, Depends, Query, Request

from app.api.deps import get_container
from app.api.schemas import ProjectListResponse
from app.core.security import require_app_auth, validate_project_name
from app.core.utils import utcnow
from app.services.diagnosis_service import sanitize_log_message

router = APIRouter(prefix="/api/projects", tags=["projects"],
                   dependencies=[Depends(require_app_auth)])

DEMO_NOTICE = "اطلاعات این صفحه در حالت DEMO شبیه‌سازی شده است و از api.liara.ir دریافت نشده است."


@router.get("", response_model=ProjectListResponse, summary="List Liara projects")
async def list_projects(request: Request) -> dict[str, Any]:
    container = get_container(request)
    projects = await container.adapter.list_projects()
    return {
        "mode": container.adapter.mode,
        "simulated": container.adapter.simulated,
        "notice": DEMO_NOTICE if container.adapter.simulated else None,
        "projects": [
            {
                "id": p.id, "name": p.name, "type": p.type, "status": p.status,
                "scale": p.scale, "plan_id": p.plan_id, "is_deployed": p.is_deployed,
                "created_at": p.created_at,
            }
            for p in projects
        ],
    }


@router.get("/{project_name}", summary="Project details (env values never returned)")
async def get_project(project_name: str, request: Request) -> dict[str, Any]:
    container = get_container(request)
    project = validate_project_name(project_name)
    details = await container.adapter.get_project(project)
    return {
        "mode": container.adapter.mode,
        "simulated": container.adapter.simulated,
        "project": {
            "id": details.id,
            "name": details.name,
            "type": details.type,
            "status": details.status,
            "scale": details.scale,
            "plan_id": details.plan_id,
            "is_deployed": details.is_deployed,
            "created_at": details.created_at,
            "env_keys": details.env_keys,
            "zero_downtime": details.zero_downtime,
        },
        "notice": DEMO_NOTICE if container.adapter.simulated else None,
    }


@router.get("/{project_name}/logs", summary="Recent logs (sanitised)")
async def get_logs(
    project_name: str,
    request: Request,
    minutes: int = Query(default=60, ge=1, le=1440),
    limit: int = Query(default=100, ge=1, le=300),
) -> dict[str, Any]:
    container = get_container(request)
    project = validate_project_name(project_name)
    since = utcnow() - timedelta(minutes=minutes)
    entries = await container.adapter.get_logs(project, since=since)
    sanitized = []
    flagged = 0
    for entry in entries[-limit:]:
        message, was_flagged = sanitize_log_message(entry.message)
        flagged += int(was_flagged)
        sanitized.append({
            "datetime": entry.datetime,
            "level": entry.level,
            "type": entry.type,
            "message": message,
            "flagged": was_flagged,
        })
    return {
        "mode": container.adapter.mode,
        "simulated": container.adapter.simulated,
        "project": project,
        "since_minutes": minutes,
        "count": len(sanitized),
        "flagged_instruction_lines": flagged,
        "logs": sanitized,
        "notice": DEMO_NOTICE if container.adapter.simulated else None,
    }


@router.get("/{project_name}/metrics", summary="CPU and memory metrics")
async def get_metrics(
    project_name: str,
    request: Request,
    minutes: int = Query(default=60, ge=5, le=1440),
) -> dict[str, Any]:
    container = get_container(request)
    project = validate_project_name(project_name)
    since = utcnow().timestamp() - minutes * 60
    cpu, memory = await asyncio.gather(
        container.adapter.get_cpu_metrics(project, since=since),
        container.adapter.get_memory_metrics(project, since=since),
        return_exceptions=True,
    )
    def _payload(series: Any) -> dict[str, Any]:
        if isinstance(series, BaseException):
            return {"unavailable_reason": str(series)[:200], "points": []}
        return {
            **series.as_summary(),
            "points": [
                {"t": p.timestamp, "v": p.value} for p in series.points[-120:]
            ],
        }
    return {
        "mode": container.adapter.mode,
        "simulated": container.adapter.simulated,
        "project": project,
        "cpu": _payload(cpu),
        "memory": _payload(memory),
        "notice": DEMO_NOTICE if container.adapter.simulated else None,
    }
