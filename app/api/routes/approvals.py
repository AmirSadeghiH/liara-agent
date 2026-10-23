"""Human-in-the-loop approval endpoints.

Approvals are server-side objects.  Approving here records the decision, then
resumes the workflow; the sensitive operation itself re-validates and consumes
the approval in the service layer.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query, Request

from app.api.deps import get_container
from app.api.schemas import ApprovalDecisionRequest
from app.api.serializers import approval_dict, workflow_summary
from app.core.errors import ConflictError, NotFoundError
from app.core.security import require_app_auth
from app.db.repository import TERMINAL_STATUSES

router = APIRouter(prefix="/api/approvals", tags=["approvals"],
                   dependencies=[Depends(require_app_auth)])


@router.get("", summary="List approvals")
async def list_approvals(
    request: Request,
    status_filter: str | None = Query(default=None, alias="status"),
    workflow_id: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=100),
) -> dict[str, Any]:
    container = get_container(request)
    if status_filter == "pending":
        rows = await container.approvals.list_pending()
    else:
        rows = await container.repo.list_approvals(
            status=status_filter, workflow_id=workflow_id, limit=limit
        )
    pending = await container.repo.count_pending_approvals()
    return {"count": len(rows), "pending_count": pending,
            "approvals": [approval_dict(r) for r in rows]}


@router.get("/{approval_id}", summary="Approval detail")
async def get_approval(approval_id: str, request: Request) -> dict[str, Any]:
    container = get_container(request)
    row = await container.approvals.get(approval_id)
    workflow = await container.repo.get_workflow(row.workflow_id)
    return {
        "approval": approval_dict(row),
        "workflow": workflow_summary(workflow) if workflow else None,
        "expired": container.approvals.is_expired(row),
    }


async def _decide_and_resume(
    request: Request, approval_id: str, decision: str, payload: ApprovalDecisionRequest
) -> dict[str, Any]:
    container = get_container(request)
    row = await container.approvals.get(approval_id)
    workflow = await container.repo.get_workflow(row.workflow_id)
    if workflow is None:
        raise NotFoundError("Workflow for this approval no longer exists.")
    if workflow.status in TERMINAL_STATUSES:
        raise ConflictError(
            f"Workflow is already finished ({workflow.status}); the approval cannot be applied.",
            details={"workflow_id": workflow.id, "status": workflow.status},
        )
    updated = await container.approvals.decide(
        approval_id, decision=decision, actor=payload.actor, note=payload.note  # type: ignore[arg-type]
    )
    resumed = await container.runner.resume(
        workflow.id, approval_id=updated.id, actor=payload.actor, wait=False
    )
    return {
        "approval": approval_dict(updated),
        "workflow": resumed,
        "note": (
            "تصمیم در سرور ثبت شد و گردش‌کار ادامه یافت. نتیجه نهایی از وضعیت گردش‌کار خوانده می‌شود."
        ),
    }


@router.post("/{approval_id}/approve", summary="Approve and resume the workflow")
async def approve(
    approval_id: str, payload: ApprovalDecisionRequest, request: Request
) -> dict[str, Any]:
    return await _decide_and_resume(request, approval_id, "approved", payload)


@router.post("/{approval_id}/reject", summary="Reject and stop the workflow")
async def reject(
    approval_id: str, payload: ApprovalDecisionRequest, request: Request
) -> dict[str, Any]:
    return await _decide_and_resume(request, approval_id, "rejected", payload)
