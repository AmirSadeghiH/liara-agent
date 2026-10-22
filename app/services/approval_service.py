"""Human-in-the-loop approval service.

An approval is a server-side object, never a client-supplied boolean:

* deterministic ID per (workflow, stage, attempt) so graph re-execution after an
  ``interrupt`` cannot create duplicates,
* parameters are fingerprinted (SHA-256) and must match at execution time,
* TTL enforced on read and on consumption,
* single use: ``consumed_at`` is set atomically before the sensitive action.
"""

from __future__ import annotations

import logging
from datetime import timedelta
from typing import Any, Literal

from app.core.config import Settings
from app.core.errors import ConflictError, NotFoundError, PolicyViolation
from app.core.utils import fingerprint as make_fingerprint
from app.core.utils import iso, parse_iso, utcnow
from app.db.models import ApprovalRequest
from app.db.repository import Repository
from app.services.audit_service import AuditService

logger = logging.getLogger(__name__)

Decision = Literal["approved", "rejected"]


class ApprovalService:
    def __init__(self, repo: Repository, settings: Settings, audit: AuditService) -> None:
        self.repo = repo
        self.settings = settings
        self.audit = audit

    # ------------------------------------------------------------------
    # creation
    # ------------------------------------------------------------------
    @staticmethod
    def build_id(workflow_id: str, stage: str, attempt: int) -> str:
        return f"apv-{workflow_id}-{stage}-{attempt}"

    async def create(
        self,
        *,
        workflow_id: str,
        stage: str,
        action: str,
        project: str | None,
        title: str,
        reason: str,
        params: dict[str, Any],
        risk_level: str = "medium",
        attempt: int = 0,
        simulated: bool = False,
    ) -> ApprovalRequest:
        approval_id = self.build_id(workflow_id, stage, attempt)
        existing = await self.repo.get_approval(approval_id)
        if existing is not None:
            # Idempotent: reuse a pending/decided approval, but never revive an
            # expired or consumed one with the same id.
            return existing
        now = utcnow()
        row = await self.repo.create_approval(
            {
                "id": approval_id,
                "workflow_id": workflow_id,
                "project": project,
                "action": action,
                "stage": stage,
                "risk_level": risk_level,
                "title": title,
                "reason": reason,
                "params": params,
                "fingerprint": make_fingerprint(params),
                "status": "pending",
                "requested_at": iso(now),
                "expires_at": iso(now + timedelta(minutes=self.settings.hitl_approval_ttl_minutes)),
                "simulated": simulated,
            }
        )
        await self.audit.record(
            "approval.requested",
            target=approval_id,
            detail={"workflow_id": workflow_id, "stage": stage, "action": action,
                    "project": project, "risk_level": risk_level},
            trace_id=workflow_id,
        )
        logger.info("approval requested", extra={"event_data": {
            "approval_id": approval_id, "workflow_id": workflow_id, "stage": stage}})
        return row

    # ------------------------------------------------------------------
    # reads
    # ------------------------------------------------------------------
    async def get(self, approval_id: str) -> ApprovalRequest:
        row = await self.repo.get_approval(approval_id)
        if row is None:
            raise NotFoundError("Approval request not found.", details={"approval_id": approval_id})
        return row

    async def get_pending_for_workflow(self, workflow_id: str) -> ApprovalRequest | None:
        rows = await self.repo.list_approvals(status="pending", workflow_id=workflow_id, limit=5)
        return rows[0] if rows else None

    async def list_pending(self) -> list[ApprovalRequest]:
        await self.expire_stale()
        return await self.repo.list_approvals(status="pending", limit=50)

    async def list_all(self, *, limit: int = 50) -> list[ApprovalRequest]:
        await self.expire_stale()
        return await self.repo.list_approvals(limit=limit)

    def is_expired(self, row: ApprovalRequest, *, now=None) -> bool:
        expires = parse_iso(row.expires_at)
        return bool(expires and (now or utcnow()) >= expires)

    async def expire_stale(self) -> list[str]:
        ids = await self.repo.expire_pending_approvals(iso())
        for approval_id in ids:
            await self.audit.record("approval.expired", target=approval_id, outcome="expired")
        return ids

    # ------------------------------------------------------------------
    # decisions
    # ------------------------------------------------------------------
    async def decide(
        self, approval_id: str, *, decision: Decision, actor: str = "ui", note: str | None = None
    ) -> ApprovalRequest:
        row = await self.get(approval_id)
        if row.status != "pending":
            raise ConflictError(
                f"Approval is not pending (current status: {row.status}).",
                details={"approval_id": approval_id, "status": row.status},
            )
        if self.is_expired(row):
            await self.repo.update_approval(approval_id, status="expired")
            raise PolicyViolation(
                "Approval request has expired. A new request is required.",
                details={"approval_id": approval_id},
            )
        updated = await self.repo.update_approval(
            approval_id,
            status=decision,
            decided_at=iso(),
            decided_by=actor,
            decision_note=(note or "")[:500] or None,
        )
        await self.audit.record(
            f"approval.{decision}",
            actor=actor,
            target=approval_id,
            detail={"workflow_id": row.workflow_id, "stage": row.stage, "action": row.action,
                    "fingerprint": row.fingerprint, "note": note},
            trace_id=row.workflow_id,
        )
        assert updated is not None
        return updated

    # ------------------------------------------------------------------
    # consumption (the security gate used by sensitive actions)
    # ------------------------------------------------------------------
    async def validate(
        self,
        approval_id: str | None,
        *,
        workflow_id: str,
        params: dict[str, Any],
        required_stage: str | None = None,
        allow_consumed: bool = False,
    ) -> ApprovalRequest:
        """Read-only validation of an approval against current parameters."""
        if not approval_id:
            raise PolicyViolation(
                "A valid approval_id is required for this operation.",
                details={"reason": "missing_approval"},
            )
        row = await self.get(approval_id)
        if row.workflow_id != workflow_id:
            raise PolicyViolation("Approval does not belong to this workflow.")
        if required_stage and row.stage != required_stage:
            raise PolicyViolation(
                "Approval stage does not match the requested operation.",
                details={"expected": required_stage, "actual": row.stage},
            )
        if row.status != "approved":
            raise PolicyViolation(
                f"Approval is not approved (current status: {row.status}).",
                details={"approval_id": approval_id, "status": row.status},
            )
        if row.consumed_at and not allow_consumed:
            raise PolicyViolation(
                "Approval has already been used. Sensitive actions require a fresh approval.",
                details={"approval_id": approval_id},
            )
        if self.is_expired(row):
            await self.repo.update_approval(approval_id, status="expired")
            raise PolicyViolation("Approval has expired; request a new one.")

        expected = make_fingerprint(params)
        if expected != row.fingerprint:
            raise PolicyViolation(
                "Approval does not match the current action parameters. Request a new approval.",
                details={"reason": "fingerprint_mismatch", "approval_id": approval_id},
            )
        return row

    async def validate_and_consume(
        self,
        approval_id: str | None,
        *,
        workflow_id: str,
        params: dict[str, Any],
        required_stage: str | None = None,
    ) -> ApprovalRequest:
        row = await self.validate(
            approval_id, workflow_id=workflow_id, params=params, required_stage=required_stage
        )
        consumed = await self.repo.update_approval(row.id, consumed_at=iso())
        await self.audit.record(
            "approval.consumed",
            target=row.id,
            detail={"workflow_id": workflow_id, "stage": row.stage, "action": row.action},
            trace_id=workflow_id,
        )
        assert consumed is not None
        return consumed
