"""Quick, read-only diagnosis endpoint.

This runs the evidence + rule engine synchronously (fast, no writes to Liara) and
records the result as a completed diagnosis-only run.  It never starts a repair.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Request, status

from app.api.deps import get_container
from app.api.schemas import DiagnosisRequest
from app.api.serializers import evidence_dict
from app.core.security import require_app_auth, validate_project_name
from app.core.utils import iso, new_id

router = APIRouter(prefix="/api", tags=["diagnosis"], dependencies=[Depends(require_app_auth)])


@router.post("/diagnose", status_code=status.HTTP_200_OK,
             summary="Collect evidence and diagnose without changing anything")
async def diagnose(payload: DiagnosisRequest, request: Request) -> dict[str, Any]:
    container = get_container(request)
    project = validate_project_name(payload.project)
    workflow_id = new_id("diag")
    thread_id = f"thread-{workflow_id}"
    await container.repo.create_workflow({
        "id": workflow_id,
        "thread_id": thread_id,
        "project": project,
        "request_text": payload.request,
        "status": "running",
        "current_step": "diagnose_issue",
        "demo_mode": container.settings.demo_mode,
        "simulated": container.adapter.simulated,
        "attempt": 0,
        "max_attempts": 0,
        "created_by": "api-diagnose",
    })
    await container.repo.add_event(
        workflow_id, step="diagnose_issue", status="running",
        message="تشخیص سریع (بدون تغییر در لیارا) آغاز شد.",
        step_key=f"{workflow_id}:diagnose:start",
    )
    bundle, report = await container.diagnosis.diagnose(
        workflow_id=workflow_id, project=project, attempt=0, request_text=payload.request
    )
    final_report = {
        "workflow_id": workflow_id,
        "project": project,
        "mode": bundle.mode,
        "simulated": bundle.simulated,
        "outcome": "diagnosed",
        "stop_reason": "diagnosis_only",
        "generated_at": iso(),
        "problem": {"request": payload.request, "observation": report.observation},
        "evidence": {
            "refs": report.evidence_refs,
            "statements": report.evidence,
            "unavailable_sources": report.unavailable_sources,
            "resource_assessment": report.resource_assessment,
        },
        "diagnosis": {
            "probable_cause": report.probable_cause,
            "cause_key": report.probable_cause_key,
            "alternatives": report.alternatives,
            "confidence": report.confidence,
            "recommended_action": report.recommended_action,
            "risk": report.risk,
            "verification_method": report.verification_method,
            "engine": report.engine,
        },
        "change": None,
        "tests": None,
        "deployment": None,
        "verification": None,
        "human_actions": {"repair_approval": None, "deployment_approval": None},
        "remaining_limitations": [
            "این endpoint فقط تشخیص انجام می‌دهد و هیچ اصلاح یا انتشاری را شروع نمی‌کند."
        ],
    }
    await container.repo.set_workflow_status(
        workflow_id,
        "completed",
        current_step="diagnose_issue",
        diagnosis=report.as_dict(),
        final_report=final_report,
        stop_reason="no_incident_detected" if not report.has_incident else "diagnosis_only",
    )
    await container.repo.add_event(
        workflow_id, step="diagnose_issue", status="completed",
        message=f"تشخیص کامل شد: {report.probable_cause_key}",
        step_key=f"{workflow_id}:diagnose:done",
        data={"cause_key": report.probable_cause_key, "confidence": report.confidence},
    )
    evidence = await container.repo.list_evidence(workflow_id)
    return {
        "workflow_id": workflow_id,
        "project": project,
        "mode": bundle.mode,
        "simulated": bundle.simulated,
        "diagnosis": report.as_dict(),
        "evidence": [evidence_dict(e) for e in evidence],
        "unavailable_sources": report.unavailable_sources,
        "final_report": final_report,
        "notice": (
            "نتیجه شبیه‌سازی‌شده است (DEMO)."
            if bundle.simulated else "داده‌ها از API واقعی لیارا خوانده شدند."
        ),
    }
