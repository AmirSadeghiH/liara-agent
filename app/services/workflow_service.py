"""Workflow orchestration: start, resume, cancel and inspect runs.

The graph itself is pure workflow logic; this service owns execution concerns
(background tasks, serialisation of checkpoint access, error containment) so the
HTTP layer and MCP tools share exactly the same behaviour.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from langgraph.types import Command

from app.core.config import Settings
from app.core.errors import ConflictError, NotFoundError, PolicyViolation
from app.core.logging import redact_text
from app.core.utils import iso, new_id
from app.db.repository import Repository
from app.liara.adapter import LiaraAdapter
from app.services.approval_service import ApprovalService
from app.services.audit_service import AuditService

logger = logging.getLogger(__name__)

TERMINAL = {"completed", "failed", "cancelled", "needs_human"}
CANCELLABLE = {"queued", "waiting_for_approval", "needs_human", "failed"}
MAX_RECURSION = 60


class WorkflowRunner:
    def __init__(
        self,
        settings: Settings,
        repo: Repository,
        audit: AuditService,
        approvals: ApprovalService,
        adapter: LiaraAdapter,
    ) -> None:
        self.settings = settings
        self.repo = repo
        self.audit = audit
        self.approvals = approvals
        self.adapter = adapter
        self.graph: Any = None
        self._locks: dict[str, asyncio.Lock] = {}
        self._tasks: dict[str, asyncio.Task[Any]] = {}
        self._checkpoint_lock = asyncio.Lock()

    def attach(self, graph: Any) -> None:
        self.graph = graph

    # ------------------------------------------------------------------
    # helpers
    # ------------------------------------------------------------------
    def _config(self, thread_id: str) -> dict[str, Any]:
        return {"configurable": {"thread_id": thread_id}, "recursion_limit": MAX_RECURSION}

    def _lock(self, workflow_id: str) -> asyncio.Lock:
        return self._locks.setdefault(workflow_id, asyncio.Lock())

    async def _spawn(self, workflow_id: str, coro) -> None:  # type: ignore[no-untyped-def]
        task = asyncio.create_task(coro)
        self._tasks[workflow_id] = task

        def _done(_t: asyncio.Task[Any]) -> None:
            self._tasks.pop(workflow_id, None)

        task.add_done_callback(_done)

    # ------------------------------------------------------------------
    # start
    # ------------------------------------------------------------------
    async def start(
        self,
        *,
        request_text: str,
        project: str | None,
        actor: str = "ui",
        max_attempts: int | None = None,
    ) -> dict[str, Any]:
        if self.graph is None:
            raise RuntimeError("Workflow graph is not initialised.")
        workflow_id = new_id("wf")
        thread_id = f"thread-{workflow_id}"
        attempts = max_attempts or self.settings.coding_agent_max_repair_attempts
        row = await self.repo.create_workflow({
            "id": workflow_id,
            "thread_id": thread_id,
            "project": project,
            "request_text": request_text,
            "status": "queued",
            "current_step": "queued",
            "demo_mode": self.settings.demo_mode,
            "simulated": self.adapter.simulated,
            "attempt": 0,
            "max_attempts": attempts,
            "created_by": actor,
        })
        await self.repo.add_event(
            workflow_id, step=None, status="queued", message="گردش‌کار در صف اجرا قرار گرفت.",
            step_key=f"{workflow_id}:queued",
            data={"project": project, "simulated": self.adapter.simulated},
        )
        await self.audit.record(
            "workflow.created", actor=actor, target=workflow_id, outcome="queued",
            detail={"project": project, "demo_mode": self.settings.demo_mode},
            trace_id=workflow_id,
        )
        input_state = {
            "workflow_id": workflow_id,
            "thread_id": thread_id,
            "project": project or "",
            "request_text": request_text,
            "attempt": 0,
            "max_attempts": attempts,
            "simulated": self.adapter.simulated,
            "demo_mode": self.settings.demo_mode,
            "started_at": iso(),
            "updated_at": iso(),
            "steps": [],
        }
        await self._spawn(workflow_id, self._run(workflow_id, thread_id, input_state))
        return self._summary(row)

    async def _run(self, workflow_id: str, thread_id: str, input_state: dict[str, Any]) -> None:
        async with self._lock(workflow_id), self._checkpoint_lock:
            try:
                result = await self.graph.ainvoke(input_state, self._config(thread_id))
                await self._after_invoke(workflow_id, result)
            except asyncio.CancelledError:  # pragma: no cover - shutdown
                raise
            except Exception as exc:
                await self._fail(workflow_id, exc)

    async def _after_invoke(self, workflow_id: str, result: dict[str, Any] | None) -> None:
        interrupts = (result or {}).get("__interrupt__")
        row = await self.repo.get_workflow(workflow_id)
        if interrupts:
            pending = await self.approvals.get_pending_for_workflow(workflow_id)
            # ``current_step`` is the graph node name, not the approval stage:
            # the chat timeline renders it directly and would show a bare
            # "repair" instead of the waiting step.
            waiting_step = (
                "request_deployment_approval"
                if pending is not None and pending.stage == "deploy"
                else "request_human_approval"
            )
            await self.repo.update_workflow(
                workflow_id,
                status="waiting_for_approval",
                pending_approval_id=pending.id if pending else None,
                current_step=waiting_step,
            )
            await self.audit.record(
                "workflow.waiting_for_approval", target=workflow_id, outcome="waiting",
                detail={"approval_id": pending.id if pending else None,
                        "stage": pending.stage if pending else None},
                trace_id=workflow_id,
            )
            return
        if row is not None and row.status not in TERMINAL:
            # Defensive: a graph that ends without finish_or_stop must not look "running".
            await self.repo.set_workflow_status(
                workflow_id, "completed", stop_reason=row.stop_reason or "graph_finished"
            )
            await self.audit.record(
                "workflow.completed", target=workflow_id, outcome="completed",
                detail={"stop_reason": row.stop_reason or "graph_finished"}, trace_id=workflow_id,
            )

    async def _fail(self, workflow_id: str, exc: Exception) -> None:
        message = redact_text(f"{type(exc).__name__}: {exc}")[:2000]
        logger.exception("workflow execution failed", extra={"event_data": {"workflow_id": workflow_id}})
        await self.repo.set_workflow_status(
            workflow_id, "failed", error=message, stop_reason="internal_error",
            pending_approval_id=None,
        )
        await self.repo.add_event(
            workflow_id, step=None, status="failed", message="خطای داخلی در اجرای گردش‌کار.",
            step_key=f"{workflow_id}:internal_error:{iso()}",
            data={"error": message},
        )
        await self.audit.record(
            "workflow.failed", target=workflow_id, outcome="failed",
            detail={"error": message}, trace_id=workflow_id,
        )

    # ------------------------------------------------------------------
    # resume
    # ------------------------------------------------------------------
    async def resume(
        self, workflow_id: str, *, approval_id: str, actor: str = "ui", wait: bool = False
    ) -> dict[str, Any]:
        row = await self.repo.get_workflow(workflow_id)
        if row is None:
            raise NotFoundError("Workflow not found.", details={"workflow_id": workflow_id})
        if row.status == "cancelled":
            raise ConflictError("Workflow was cancelled and cannot be resumed.")
        if row.status in {"completed", "failed"}:
            raise ConflictError(
                f"Workflow is already finished ({row.status}) and cannot be resumed.",
                details={"status": row.status},
            )
        approval = await self.approvals.get(approval_id)
        if approval.workflow_id != workflow_id:
            raise PolicyViolation("Approval does not belong to this workflow.")
        if approval.status == "pending":
            raise ConflictError(
                "Approval decision is still pending; approve or reject it first.",
                details={"approval_id": approval_id},
            )
        if approval.status == "expired":
            raise PolicyViolation("Approval has expired; a new approval is required.")
        if row.status not in {"waiting_for_approval", "needs_human"}:
            raise ConflictError(
                f"Workflow is not waiting for approval (status: {row.status}).",
                details={"status": row.status},
            )
        if self.graph is None:
            raise RuntimeError("Workflow graph is not initialised.")

        resume_payload = {"approval_id": approval.id, "decision": approval.status}
        task = asyncio.create_task(
            self._resume_run(
                workflow_id, row.thread_id, resume_payload, approval, actor, wait_handle=True
            )
        )
        self._tasks[workflow_id] = task
        task.add_done_callback(lambda _t: self._tasks.pop(workflow_id, None))
        if wait:
            await task
            refreshed = await self.repo.get_workflow(workflow_id)
            return self._summary(refreshed)
        return self._summary(row)

    async def _resume_run(
        self, workflow_id: str, thread_id: str, payload: dict[str, Any], approval: Any,
        actor: str, *, wait_handle: bool = False,
    ) -> None:
        async with self._lock(workflow_id), self._checkpoint_lock:
            await self.audit.record(
                "workflow.resumed", actor=actor, target=workflow_id, outcome="running",
                detail={"approval_id": approval.id, "stage": approval.stage,
                        "decision": approval.status},
                trace_id=workflow_id,
            )
            await self.repo.add_event(
                workflow_id, step=None, status="running",
                message=(
                    "ادامه گردش‌کار پس از تأیید کاربر."
                    if approval.status == "approved" else "ادامه گردش‌کار پس از رد کاربر."
                ),
                step_key=f"{workflow_id}:resume:{approval.id}",
                data={"approval_id": approval.id, "decision": approval.status},
            )
            try:
                result = await self.graph.ainvoke(Command(resume=payload), self._config(thread_id))
                await self._after_invoke(workflow_id, result)
            except Exception as exc:
                await self._fail(workflow_id, exc)

    # ------------------------------------------------------------------
    # cancel
    # ------------------------------------------------------------------
    async def cancel(self, workflow_id: str, *, actor: str = "ui") -> dict[str, Any]:
        row = await self.repo.get_workflow(workflow_id)
        if row is None:
            raise NotFoundError("Workflow not found.", details={"workflow_id": workflow_id})
        if row.status in TERMINAL:
            return self._summary(row)
        if row.status not in CANCELLABLE:
            raise ConflictError(
                "لغو در این مرحله امکان‌پذیر نیست: درخواست در حال اجراست و فراخوانی HTTP "
                "لیارا قابل بازگشت نیست. تا پایان مرحله فعلی صبر کنید.",
                details={"status": row.status, "cancellable": sorted(CANCELLABLE)},
            )
        pending = await self.repo.list_approvals(status="pending", workflow_id=workflow_id, limit=10)
        for approval in pending:
            await self.repo.update_approval(
                approval.id, status="expired", decision_note="cancelled by user",
            )
        await self.repo.set_workflow_status(
            workflow_id, "cancelled", stop_reason="cancelled_by_user", pending_approval_id=None,
        )
        await self.repo.add_event(
            workflow_id, step=None, status="cancelled", message="گردش‌کار توسط کاربر لغو شد.",
            step_key=f"{workflow_id}:cancelled",
        )
        await self.audit.record(
            "workflow.cancelled", actor=actor, target=workflow_id, outcome="cancelled",
            detail={"expired_approvals": [p.id for p in pending]}, trace_id=workflow_id,
        )
        refreshed = await self.repo.get_workflow(workflow_id)
        assert refreshed is not None
        return self._summary(refreshed)

    # ------------------------------------------------------------------
    # reads
    # ------------------------------------------------------------------
    async def wait(self, workflow_id: str, max_seconds: float = 120.0) -> dict[str, Any]:
        task = self._tasks.get(workflow_id)
        if task is not None:
            try:
                await asyncio.wait_for(asyncio.shield(task), timeout=max_seconds)
            except TimeoutError:
                logger.warning("workflow wait timed out", extra={"event_data": {"workflow_id": workflow_id}})
        row = await self.repo.get_workflow(workflow_id)
        if row is None:
            raise NotFoundError("Workflow not found.")
        return self._summary(row)

    async def graph_state(self, workflow_id: str) -> dict[str, Any] | None:
        row = await self.repo.get_workflow(workflow_id)
        if row is None or self.graph is None:
            return None
        try:
            snapshot = await self.graph.aget_state(self._config(row.thread_id))
            return {
                "values": snapshot.values if snapshot else {},
                "next": list(getattr(snapshot, "next", ()) or ()),
                "interrupts": [
                    {"id": getattr(i, "id", None), "value": getattr(i, "value", None)}
                    for i in (getattr(snapshot, "interrupts", ()) or ())
                ] if snapshot else [],
                "checkpoint_id": (snapshot.config or {}).get("configurable", {}).get("checkpoint_id")
                if snapshot else None,
            }
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning("could not read graph state", exc_info=True)
            return {"error": type(exc).__name__}

    @staticmethod
    def _summary(row: Any) -> dict[str, Any]:
        if row is None:
            return {}
        return {
            "workflow_id": row.id,
            "thread_id": row.thread_id,
            "project": row.project,
            "status": row.status,
            "current_step": row.current_step,
            "demo_mode": row.demo_mode,
            "simulated": row.simulated,
            "attempt": row.attempt,
            "max_attempts": row.max_attempts,
            "pending_approval_id": row.pending_approval_id,
            "stop_reason": row.stop_reason,
            "error": row.error,
            "created_at": row.created_at,
            "updated_at": row.updated_at,
            "completed_at": row.completed_at,
        }
