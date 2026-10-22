"""Workflow lifecycle endpoints."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query, Request, status

from app.api.deps import get_container
from app.api.schemas import ResumeRequest, WorkflowCreateRequest
from app.api.serializers import workflow_detail, workflow_summary
from app.core.errors import NotFoundError, ValidationError
from app.core.security import require_app_auth, validate_project_name
from app.db.repository import TERMINAL_STATUSES

router = APIRouter(prefix="/api/workflows", tags=["workflows"],
                   dependencies=[Depends(require_app_auth)])


@router.post("", status_code=status.HTTP_202_ACCEPTED, summary="Start a diagnostic/repair workflow")
async def create_workflow(payload: WorkflowCreateRequest, request: Request) -> dict[str, Any]:
    container = get_container(request)
    project = validate_project_name(payload.project) if payload.project else None
    started = await container.runner.start(
        request_text=payload.request, project=project, actor="api",
        max_attempts=payload.max_attempts,
    )
    return started


@router.get("", summary="List workflows")
async def list_workflows(
    request: Request,
    limit: int = Query(default=30, ge=1, le=100),
    status_filter: str | None = Query(default=None, alias="status"),
    project: str | None = Query(default=None),
) -> dict[str, Any]:
    container = get_container(request)
    rows = await container.repo.list_workflows(
        limit=limit, status=status_filter,
        project=validate_project_name(project) if project else None,
    )
    return {"count": len(rows), "workflows": [workflow_summary(r) for r in rows]}


@router.get("/{workflow_id}", summary="Workflow detail with events, evidence and approvals")
async def get_workflow(workflow_id: str, request: Request) -> dict[str, Any]:
    container = get_container(request)
    row = await container.repo.get_workflow(workflow_id)
    if row is None:
        raise NotFoundError("Workflow not found.", details={"workflow_id": workflow_id})
    events = await container.repo.list_events(workflow_id)
    evidence = await container.repo.list_evidence(workflow_id)
    approvals = await container.repo.list_approvals(workflow_id=workflow_id, limit=50)
    agent_runs = await container.repo.list_agent_runs(workflow_id)
    deployments = await container.repo.list_deployments(workflow_id=workflow_id, limit=20)
    graph = await container.runner.graph_state(workflow_id)
    return workflow_detail(
        row, events=events, evidence=evidence, approvals=approvals,
        agent_runs=agent_runs, deployments=deployments, graph=graph,
    )


@router.get("/{workflow_id}/events", summary="Workflow event timeline")
async def get_events(workflow_id: str, request: Request) -> dict[str, Any]:
    container = get_container(request)
    row = await container.repo.get_workflow(workflow_id)
    if row is None:
        raise NotFoundError("Workflow not found.")
    events = await container.repo.list_events(workflow_id)
    from app.api.serializers import event_dict

    return {"workflow_id": workflow_id, "status": row.status,
            "events": [event_dict(e) for e in events]}


@router.post("/{workflow_id}/resume", summary="Resume a workflow after a decided approval")
async def resume_workflow(
    workflow_id: str, payload: ResumeRequest, request: Request
) -> dict[str, Any]:
    container = get_container(request)
    row = await container.repo.get_workflow(workflow_id)
    if row is None:
        raise NotFoundError("Workflow not found.")
    approval_id = payload.approval_id or row.pending_approval_id
    if not approval_id:
        raise ValidationError("No approval_id supplied and the workflow has no pending approval.")
    if row.status in TERMINAL_STATUSES and row.status != "needs_human":
        raise ValidationError(
            f"Workflow is already finished ({row.status}).", details={"status": row.status}
        )
    result = await container.runner.resume(
        workflow_id, approval_id=approval_id, actor="api", wait=payload.wait
    )
    return result


@router.post("/{workflow_id}/cancel", summary="Cancel a workflow when it is safe to do so")
async def cancel_workflow(workflow_id: str, request: Request) -> dict[str, Any]:
    container = get_container(request)
    return await container.runner.cancel(workflow_id, actor="api")
