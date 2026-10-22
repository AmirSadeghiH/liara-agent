"""Repository layer: the only place that talks to SQLAlchemy directly."""

from __future__ import annotations

from typing import Any

from sqlalchemy import delete, func, select

from app.core.utils import iso
from app.db.database import Database
from app.db.models import (
    ApprovalRequest,
    AuditEvent,
    CodingAgentRun,
    DeploymentRecord,
    EvidenceRecord,
    WorkflowEvent,
    WorkflowRun,
)

TERMINAL_STATUSES = {"completed", "failed", "cancelled", "needs_human"}


class Repository:
    def __init__(self, db: Database) -> None:
        self.db = db

    # ------------------------------------------------------------------
    # workflows
    # ------------------------------------------------------------------
    async def create_workflow(self, payload: dict[str, Any]) -> WorkflowRun:
        now = iso()
        row = WorkflowRun(
            created_at=now, updated_at=now,
            **{k: v for k, v in payload.items() if k not in {"created_at", "updated_at"}},
        )
        async with self.db.session() as session:
            session.add(row)
        return row

    async def get_workflow(self, workflow_id: str) -> WorkflowRun | None:
        async with self.db.session() as session:
            return await session.get(WorkflowRun, workflow_id)

    async def list_workflows(
        self, *, limit: int = 50, status: str | None = None, project: str | None = None
    ) -> list[WorkflowRun]:
        stmt = select(WorkflowRun).order_by(WorkflowRun.created_at.desc()).limit(limit)
        if status:
            stmt = stmt.where(WorkflowRun.status == status)
        if project:
            stmt = stmt.where(WorkflowRun.project == project)
        async with self.db.session() as session:
            return list((await session.execute(stmt)).scalars().all())

    async def update_workflow(self, workflow_id: str, **fields: Any) -> WorkflowRun | None:
        allowed = {
            "project", "request_text", "status", "current_step", "risk_level", "attempt",
            "max_attempts", "diagnosis", "repair_plan", "test_results", "deployment",
            "verification", "final_report", "workspace", "branch", "pending_approval_id",
            "stop_reason", "error", "completed_at", "simulated", "demo_mode",
        }
        unknown = set(fields) - allowed
        if unknown:
            raise ValueError(f"Unknown workflow fields: {sorted(unknown)}")
        async with self.db.session() as session:
            row = await session.get(WorkflowRun, workflow_id)
            if row is None:
                return None
            for key, value in fields.items():
                setattr(row, key, value)
            row.updated_at = iso()
            return row

    async def set_workflow_status(self, workflow_id: str, status: str, **fields: Any) -> None:
        if status in TERMINAL_STATUSES and "completed_at" not in fields:
            fields["completed_at"] = iso()
        await self.update_workflow(workflow_id, status=status, **fields)

    async def count_active_workflows(self) -> int:
        stmt = select(func.count()).select_from(WorkflowRun).where(
            WorkflowRun.status.in_(
                ["queued", "running", "testing", "deploying", "verifying", "waiting_for_approval"]
            )
        )
        async with self.db.session() as session:
            return int((await session.execute(stmt)).scalar_one())

    # ------------------------------------------------------------------
    # events
    # ------------------------------------------------------------------
    async def add_event(
        self, workflow_id: str, *, step: str | None, status: str, message: str | None = None,
        data: dict[str, Any] | None = None, step_key: str | None = None,
    ) -> bool:
        """Append an event. Returns False when *step_key* already exists.

        LangGraph re-executes a node after an ``interrupt`` resume, so node
        bookkeeping must be idempotent; ``step_key`` provides that guarantee.
        """
        async with self.db.session() as session:
            if step_key:
                existing = await session.execute(
                    select(WorkflowEvent.id).where(
                        WorkflowEvent.workflow_id == workflow_id,
                        WorkflowEvent.step_key == step_key,
                    ).limit(1)
                )
                if existing.scalar_one_or_none() is not None:
                    return False
            session.add(
                WorkflowEvent(
                    workflow_id=workflow_id, step=step, step_key=step_key, status=status,
                    message=message, data=data, created_at=iso(),
                )
            )
        return True

    async def list_events(self, workflow_id: str, *, limit: int = 300) -> list[WorkflowEvent]:
        stmt = (
            select(WorkflowEvent).where(WorkflowEvent.workflow_id == workflow_id)
            .order_by(WorkflowEvent.id.asc()).limit(limit)
        )
        async with self.db.session() as session:
            return list((await session.execute(stmt)).scalars().all())

    # ------------------------------------------------------------------
    # evidence
    # ------------------------------------------------------------------
    async def add_evidence(self, payload: dict[str, Any]) -> EvidenceRecord:
        now = iso()
        row = EvidenceRecord(created_at=now, **payload)
        async with self.db.session() as session:
            session.add(row)
        return row

    async def get_evidence(self, evidence_id: str) -> EvidenceRecord | None:
        async with self.db.session() as session:
            return await session.get(EvidenceRecord, evidence_id)

    async def list_evidence(self, workflow_id: str) -> list[EvidenceRecord]:
        stmt = (
            select(EvidenceRecord).where(EvidenceRecord.workflow_id == workflow_id)
            .order_by(EvidenceRecord.created_at.asc())
        )
        async with self.db.session() as session:
            return list((await session.execute(stmt)).scalars().all())

    # ------------------------------------------------------------------
    # approvals
    # ------------------------------------------------------------------
    async def create_approval(self, payload: dict[str, Any]) -> ApprovalRequest:
        row = ApprovalRequest(**payload)
        async with self.db.session() as session:
            session.add(row)
        return row

    async def get_approval(self, approval_id: str) -> ApprovalRequest | None:
        async with self.db.session() as session:
            return await session.get(ApprovalRequest, approval_id)

    async def list_approvals(
        self, *, status: str | None = None, workflow_id: str | None = None, limit: int = 100
    ) -> list[ApprovalRequest]:
        stmt = select(ApprovalRequest).order_by(ApprovalRequest.requested_at.desc()).limit(limit)
        if status:
            stmt = stmt.where(ApprovalRequest.status == status)
        if workflow_id:
            stmt = stmt.where(ApprovalRequest.workflow_id == workflow_id)
        async with self.db.session() as session:
            return list((await session.execute(stmt)).scalars().all())

    async def update_approval(self, approval_id: str, **fields: Any) -> ApprovalRequest | None:
        allowed = {
            "status", "decided_at", "decided_by", "decision_note", "consumed_at",
            "fingerprint", "params", "expires_at",
        }
        unknown = set(fields) - allowed
        if unknown:
            raise ValueError(f"Unknown approval fields: {sorted(unknown)}")
        async with self.db.session() as session:
            row = await session.get(ApprovalRequest, approval_id)
            if row is None:
                return None
            for key, value in fields.items():
                setattr(row, key, value)
            return row

    async def expire_pending_approvals(self, now_iso: str) -> list[str]:
        """Mark expired pending approvals; returns the affected IDs."""
        async with self.db.session() as session:
            stmt = select(ApprovalRequest).where(
                ApprovalRequest.status == "pending", ApprovalRequest.expires_at < now_iso
            )
            rows = list((await session.execute(stmt)).scalars().all())
            for row in rows:
                row.status = "expired"
            return [row.id for row in rows]

    async def count_pending_approvals(self) -> int:
        stmt = select(func.count()).select_from(ApprovalRequest).where(
            ApprovalRequest.status == "pending"
        )
        async with self.db.session() as session:
            return int((await session.execute(stmt)).scalar_one())

    # ------------------------------------------------------------------
    # deployments
    # ------------------------------------------------------------------
    async def create_deployment(self, payload: dict[str, Any]) -> DeploymentRecord:
        now = iso()
        row = DeploymentRecord(created_at=now, updated_at=now, **payload)
        async with self.db.session() as session:
            session.add(row)
        return row

    async def get_deployment(self, deployment_id: str) -> DeploymentRecord | None:
        async with self.db.session() as session:
            return await session.get(DeploymentRecord, deployment_id)

    async def update_deployment(self, deployment_id: str, **fields: Any) -> DeploymentRecord | None:
        allowed = {
            "stage", "status", "source_id", "release_id", "port", "project_type",
            "approval_id", "params", "detail", "package", "simulated",
        }
        unknown = set(fields) - allowed
        if unknown:
            raise ValueError(f"Unknown deployment fields: {sorted(unknown)}")
        async with self.db.session() as session:
            row = await session.get(DeploymentRecord, deployment_id)
            if row is None:
                return None
            for key, value in fields.items():
                setattr(row, key, value)
            row.updated_at = iso()
            return row

    async def list_deployments(self, *, limit: int = 20, workflow_id: str | None = None
                               ) -> list[DeploymentRecord]:
        stmt = select(DeploymentRecord).order_by(DeploymentRecord.created_at.desc()).limit(limit)
        if workflow_id:
            stmt = stmt.where(DeploymentRecord.workflow_id == workflow_id)
        async with self.db.session() as session:
            return list((await session.execute(stmt)).scalars().all())

    # ------------------------------------------------------------------
    # coding agent runs
    # ------------------------------------------------------------------
    async def create_agent_run(self, payload: dict[str, Any]) -> CodingAgentRun:
        now = iso()
        row = CodingAgentRun(created_at=now, updated_at=now, **payload)
        async with self.db.session() as session:
            session.add(row)
        return row

    async def update_agent_run(self, run_id: str, **fields: Any) -> CodingAgentRun | None:
        allowed = {
            "status", "exit_code", "duration_ms", "files_changed", "diff", "test_results",
            "error", "workspace", "branch", "prompt_summary", "simulated", "provider",
        }
        unknown = set(fields) - allowed
        if unknown:
            raise ValueError(f"Unknown agent run fields: {sorted(unknown)}")
        async with self.db.session() as session:
            row = await session.get(CodingAgentRun, run_id)
            if row is None:
                return None
            for key, value in fields.items():
                setattr(row, key, value)
            row.updated_at = iso()
            return row

    async def list_agent_runs(self, workflow_id: str) -> list[CodingAgentRun]:
        stmt = (
            select(CodingAgentRun).where(CodingAgentRun.workflow_id == workflow_id)
            .order_by(CodingAgentRun.created_at.asc())
        )
        async with self.db.session() as session:
            return list((await session.execute(stmt)).scalars().all())

    # ------------------------------------------------------------------
    # audit
    # ------------------------------------------------------------------
    async def add_audit(self, payload: dict[str, Any]) -> None:
        async with self.db.session() as session:
            session.add(AuditEvent(**payload))

    async def list_audit(self, *, limit: int = 100) -> list[AuditEvent]:
        stmt = select(AuditEvent).order_by(AuditEvent.at.desc()).limit(limit)
        async with self.db.session() as session:
            return list((await session.execute(stmt)).scalars().all())

    # ------------------------------------------------------------------
    # dashboard
    # ------------------------------------------------------------------
    async def dashboard_stats(self) -> dict[str, Any]:
        async with self.db.session() as session:
            total = int((await session.execute(
                select(func.count()).select_from(WorkflowRun)
            )).scalar_one())
            by_status = {
                status: int(count)
                for status, count in (await session.execute(
                    select(WorkflowRun.status, func.count()).group_by(WorkflowRun.status)
                )).all()
            }
            pending = int((await session.execute(
                select(func.count()).select_from(ApprovalRequest).where(
                    ApprovalRequest.status == "pending"
                )
            )).scalar_one())
            deployments = int((await session.execute(
                select(func.count()).select_from(DeploymentRecord)
            )).scalar_one())
            last_verification = (await session.execute(
                select(WorkflowRun.verification).where(WorkflowRun.verification.is_not(None))
                .order_by(WorkflowRun.updated_at.desc()).limit(1)
            )).scalar_one_or_none()
        return {
            "workflows_total": total,
            "workflows_by_status": by_status,
            "pending_approvals": pending,
            "deployments_total": deployments,
            "last_verification": last_verification,
            "now": iso(),
        }

    async def reset_runtime_state(self) -> None:
        """Test/demo helper: clear workflow-scoped tables (keeps audit history)."""
        async with self.db.session() as session:
            for model in (WorkflowEvent, EvidenceRecord, ApprovalRequest, DeploymentRecord,
                          CodingAgentRun, WorkflowRun):
                await session.execute(delete(model))
