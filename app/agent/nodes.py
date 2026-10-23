"""LangGraph nodes: the workflow step implementations.

Each node:
* records a start/completed event in the database (idempotent via ``step_key``),
* persists the workflow status so the UI can poll it,
* returns a partial state update,
* never executes a sensitive action without a server-side approval.
"""

from __future__ import annotations

import asyncio
import functools
import logging
import time
from collections.abc import Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import Any

from langgraph.types import interrupt

from app.agent.prompts import build_repair_plan
from app.agent.state import STEP_LABELS_FA, WorkflowState
from app.core.config import Settings
from app.core.errors import AppError, NotFoundError, PolicyViolation, ValidationError
from app.core.logging import redact_text
from app.core.security import validate_project_name
from app.core.utils import iso, utcnow
from app.db.repository import Repository
from app.liara.adapter import LiaraAdapter
from app.services.approval_service import ApprovalService
from app.services.audit_service import AuditService
from app.services.coding_agent_service import CodingAgentService
from app.services.deployment_service import DeploymentService
from app.services.diagnosis_service import DiagnosisService, EvidenceBundle
from app.services.verification_service import VerificationService

logger = logging.getLogger(__name__)

MAX_REQUEST_CHARS = 4000


@dataclass
class WorkflowDeps:
    settings: Settings
    repo: Repository
    adapter: LiaraAdapter
    diagnosis: DiagnosisService
    approvals: ApprovalService
    coding: CodingAgentService
    deployment: DeploymentService
    verification: VerificationService
    audit: AuditService


@dataclass
class StepContext:
    step: str
    label_fa: str
    attempt: int
    summary: str | None = None
    data: dict[str, Any] = field(default_factory=dict)
    entries: list[dict[str, Any]] = field(default_factory=list)

    def set(self, **values: Any) -> None:
        self.data.update(values)


def _guarded(fn: Callable[..., Any]) -> Callable[..., Any]:
    """Turn expected application errors into a structured stop instead of a crash."""

    @functools.wraps(fn)
    async def wrapper(self: WorkflowNodes, state: WorkflowState) -> dict[str, Any]:
        try:
            return await fn(self, state)
        except AppError as exc:
            needs_human = isinstance(exc, PolicyViolation)
            logger.warning("workflow step failed", extra={"event_data": {
                "step": fn.__name__, "code": exc.code, "workflow_id": state.get("workflow_id"),
            }})
            return self._fail(state, exc.message, code=exc.code, needs_human=needs_human)

    return wrapper


class WorkflowNodes:
    def __init__(self, deps: WorkflowDeps) -> None:
        self.deps = deps
        self.settings = deps.settings
        self.repo = deps.repo
        self.adapter = deps.adapter
        self.diagnosis = deps.diagnosis
        self.approvals = deps.approvals
        self.coding = deps.coding
        self.deployment = deps.deployment
        self.verification = deps.verification
        self.audit = deps.audit

    # ------------------------------------------------------------------
    # helpers
    # ------------------------------------------------------------------
    @asynccontextmanager
    async def _step(self, state: WorkflowState, step: str, *, status: str = "running"):
        workflow_id = state["workflow_id"]
        attempt = int(state.get("attempt") or 0)
        label = STEP_LABELS_FA.get(step, step)
        started = time.perf_counter()
        ctx = StepContext(step=step, label_fa=label, attempt=attempt)
        await self.repo.add_event(
            workflow_id, step=step, status="running", message=label,
            step_key=f"{workflow_id}:{attempt}:{step}:start",
            data={"label_fa": label, "attempt": attempt},
        )
        await self.repo.update_workflow(workflow_id, status=status, current_step=step)
        try:
            yield ctx
        except AppError as exc:
            duration_ms = int((time.perf_counter() - started) * 1000)
            await self.repo.add_event(
                workflow_id, step=step, status="failed", message=redact_text(exc.message),
                step_key=f"{workflow_id}:{attempt}:{step}:done",
                data={"duration_ms": duration_ms, "error_code": exc.code, "label_fa": label},
            )
            raise
        else:
            duration_ms = int((time.perf_counter() - started) * 1000)
            await self.repo.add_event(
                workflow_id, step=step, status="completed",
                message=redact_text(ctx.summary or label),
                step_key=f"{workflow_id}:{attempt}:{step}:done",
                data={"duration_ms": duration_ms, "label_fa": label, **ctx.data},
            )
            ctx.entries.append({
                "step": step, "label_fa": label, "status": "completed",
                "duration_ms": duration_ms, "attempt": attempt,
            })
        if self.settings.demo_mode and self.settings.demo_step_delay_seconds > 0:
            await asyncio.sleep(self.settings.demo_step_delay_seconds)

    @staticmethod
    def _fail(state: WorkflowState, message: str, *, code: str = "error",
              needs_human: bool = False) -> dict[str, Any]:
        return {
            "error": message,
            "error_code": code,
            "stop_reason": message,
            "outcome_status": "needs_human" if needs_human else "failed",
            "steps": [],
        }

    def _step_result(self, ctx: StepContext, **values: Any) -> dict[str, Any]:
        return {**values, "steps": ctx.entries}

    # ------------------------------------------------------------------
    # 1. intake
    # ------------------------------------------------------------------
    @_guarded
    async def intake_request(self, state: WorkflowState) -> dict[str, Any]:
        async with self._step(state, "intake_request") as ctx:
            text = (state.get("request_text") or "").strip()
            if len(text) < 3:
                raise ValidationError("درخواست خیلی کوتاه است؛ مشکل را با جزئیات بیشتری بنویسید.")
            if len(text) > MAX_REQUEST_CHARS:
                raise ValidationError(f"درخواست بیش از حد طولانی است (حداکثر {MAX_REQUEST_CHARS} کاراکتر).")
            ctx.summary = "درخواست ثبت شد."
        return self._step_result(ctx, status="running", request_text=text, attempt=0)

    # ------------------------------------------------------------------
    # 2. resolve project
    # ------------------------------------------------------------------
    @_guarded
    async def resolve_project(self, state: WorkflowState) -> dict[str, Any]:
        async with self._step(state, "resolve_project") as ctx:
            requested = (state.get("project") or "").strip()
            projects = await self.adapter.list_projects()
            names = [p.name for p in projects]
            if not requested:
                if len(names) == 1:
                    requested = names[0]
                else:
                    raise ValidationError(
                        "پروژه مشخص نشده است. یکی از پروژه‌های موجود را انتخاب کنید.",
                        details={"projects": names[:20]},
                    )
            requested = validate_project_name(requested)
            if requested not in names:
                raise NotFoundError(
                    "پروژه در حساب لیارا پیدا نشد.",
                    details={"project": requested, "visible_projects": names[:20]},
                )
            ctx.summary = f"پروژه {requested} تأیید شد."
        return self._step_result(ctx, project=requested, status="running")

    # ------------------------------------------------------------------
    # 3-4. evidence
    # ------------------------------------------------------------------
    @_guarded
    async def collect_evidence(self, state: WorkflowState) -> dict[str, Any]:
        async with self._step(state, "collect_evidence") as ctx:
            bundle = await self.diagnosis.collect(
                workflow_id=state["workflow_id"], project=state["project"],
                attempt=int(state.get("attempt") or 0),
            )
            ctx.summary = (
                f"{len(bundle.logs)} خط لاگ و {len(bundle.evidence_ids)} منبع شواهد جمع‌آوری شد."
            )
            ctx.set(evidence_ids=list(bundle.evidence_ids.values()),
                    unavailable=bundle.unavailable)
        return self._step_result(
            ctx, evidence=bundle.model_dump(), status="running",
            simulated=bundle.simulated, demo_mode=bundle.mode == "demo",
        )

    @_guarded
    async def normalize_evidence(self, state: WorkflowState) -> dict[str, Any]:
        async with self._step(state, "normalize_evidence") as ctx:
            bundle = EvidenceBundle.model_validate(state.get("evidence") or {})
            summary = bundle.to_llm_summary()
            evidence = dict(state.get("evidence") or {})
            evidence["summary"] = summary
            flagged = int(bundle.log_stats.get("flagged_instruction_lines") or 0)
            ctx.summary = "شواهد پاک‌سازی و نرمال‌سازی شد."
            if flagged:
                ctx.summary += f" {flagged} خط حاوی متن شبیه دستور خنثی شد."
            ctx.set(flagged_instructions=flagged, evidence_refs=bundle.refs)
        return self._step_result(ctx, evidence=evidence, status="running")

    # ------------------------------------------------------------------
    # 5. diagnosis
    # ------------------------------------------------------------------
    @_guarded
    async def diagnose_issue(self, state: WorkflowState) -> dict[str, Any]:
        async with self._step(state, "diagnose_issue") as ctx:
            bundle = EvidenceBundle.model_validate(state.get("evidence") or {})
            report = await self.diagnosis.analyze(bundle, request_text=state.get("request_text", ""))
            diagnosis = report.as_dict()
            await self.repo.update_workflow(
                state["workflow_id"], diagnosis=diagnosis, risk_level=None,
            )
            if not report.has_incident:
                ctx.summary = "شواهد نشان‌دهنده حادثه نیست؛ اصلاحی پیشنهاد نشد."
                await self.audit.record(
                    "workflow.no_incident", target=state["workflow_id"],
                    detail={"project": state.get("project")}, trace_id=state["workflow_id"],
                )
            else:
                ctx.summary = f"علت محتمل: {report.probable_cause_key} (اطمینان {report.confidence})"
        updates: dict[str, Any] = {"diagnosis": diagnosis, "status": "running"}
        if not report.has_incident:
            updates.update({
                "outcome_status": "completed", "stop_reason": "no_incident_detected",
            })
        return self._step_result(ctx, **updates)

    # ------------------------------------------------------------------
    # 6. risk
    # ------------------------------------------------------------------
    @_guarded
    async def classify_risk(self, state: WorkflowState) -> dict[str, Any]:
        async with self._step(state, "classify_risk") as ctx:
            diagnosis = state.get("diagnosis") or {}
            repair_risk = "low" if (diagnosis.get("confidence") == "high") else "medium"
            risk = {
                "repair": repair_risk,
                "source_upload": "medium",
                "deployment": "high",
                "git_push": "high",
                "requires_approval": ["repair", "deployment"],
                "reasons": [
                    "تغییر فایل‌های برنامه در Workspace ایزوله (بدون Production)",
                    "ارسال سورس به لیارا قبل از انتشار",
                    "ساخت Release روی پروژه Production",
                ],
            }
            await self.repo.update_workflow(state["workflow_id"], risk_level=repair_risk)
            ctx.summary = "سطح ریسک: اصلاح متوسط، انتشار پرریسک (نیازمند تأیید)."
        return self._step_result(ctx, risk=risk)

    # ------------------------------------------------------------------
    # 7. repair plan
    # ------------------------------------------------------------------
    @_guarded
    async def prepare_repair_plan(self, state: WorkflowState) -> dict[str, Any]:
        async with self._step(state, "prepare_repair_plan") as ctx:
            diagnosis = state.get("diagnosis") or {}
            attempt = int(state.get("attempt") or 0)
            plan = build_repair_plan(diagnosis, state.get("project", ""))
            plan["attempt"] = attempt
            plan["max_attempts"] = self.settings.coding_agent_max_repair_attempts
            plan["branch"] = f"ai-fix/{state['workflow_id']}"
            plan["simulated"] = bool(self.settings.demo_mode)
            # A retry must not lose what the previous attempt learned.  The
            # workspace is preserved and this payload is handed to the agent.
            if attempt > 0:
                tests = state.get("tests") or {}
                repair = state.get("repair") or {}
                plan["workspace_reused"] = True
                plan["previous_failure"] = {
                    "attempt": attempt,
                    "test_status": tests.get("status"),
                    "test_runner": tests.get("runner"),
                    "test_output_tail": str(tests.get("output_tail") or "")[-6000:],
                    "files_changed": list(repair.get("files_changed") or []),
                    "diff": str(repair.get("diff") or "")[:12000],
                }
            await self.repo.update_workflow(state["workflow_id"], repair_plan=plan)
            ctx.summary = f"برنامه اصلاح برای {plan.get('cause_key')} آماده شد."
            ctx.set(cause_key=plan.get("cause_key"))
        return self._step_result(ctx, repair_plan=plan)

    # ------------------------------------------------------------------
    # 8. repair approval (interrupt)
    # ------------------------------------------------------------------
    @_guarded
    async def request_human_approval(self, state: WorkflowState) -> dict[str, Any]:
        workflow_id = state["workflow_id"]
        attempt = int(state.get("attempt") or 0)
        plan = state.get("repair_plan") or {}
        diagnosis = state.get("diagnosis") or {}

        # A bounded retry inside the *same* approved repair plan does not need a
        # second human approval.  The original server-side approval must still be
        # approved, belong to this workflow and this stage; production deployment
        # keeps its own separate approval further down the graph.
        if attempt > 0 and state.get("approval_decision") == "approved" and state.get("approval_id"):
            original = await self.repo.get_approval(str(state["approval_id"]))
            if (
                original is not None
                and original.workflow_id == workflow_id
                and original.stage == "repair"
                and original.status == "approved"
            ):
                async with self._step(state, "request_human_approval", status="running") as ctx:
                    ctx.summary = (
                        "تلاش بعدی داخل همان برنامه تأییدشده اجرا می‌شود؛ "
                        "تأیید تکراری لازم نیست."
                    )
                    ctx.set(approval_reused=True, approval_id=original.id, attempt=attempt)
                await self.audit.record(
                    "repair.retry_authorized", target=workflow_id, outcome="approved",
                    detail={"approval_id": original.id, "attempt": attempt,
                            "max_attempts": self.settings.coding_agent_max_repair_attempts},
                    trace_id=workflow_id,
                )
                return self._step_result(
                    ctx, approval_decision="approved", approval_id=original.id,
                    pending_approval_id=None, status="running",
                )

        params = {
            "stage": "repair",
            "project": state.get("project"),
            "cause_key": plan.get("cause_key"),
            "branch": plan.get("branch"),
            "files": plan.get("files", []),
            "attempt": attempt,
            "max_attempts": self.settings.coding_agent_max_repair_attempts,
            "simulated": bool(self.settings.demo_mode),
        }
        approval = await self.approvals.create(
            workflow_id=workflow_id,
            stage="repair",
            action="apply_repair_and_upload_source",
            project=state.get("project"),
            title="اجرای اصلاح در Workspace و آماده‌سازی سورس",
            reason=diagnosis.get("probable_cause") or "اصلاح خطای شناسایی‌شده",
            params=params,
            risk_level="medium",
            attempt=attempt,
            simulated=bool(self.settings.demo_mode),
        )
        await self.repo.update_workflow(
            workflow_id, status="waiting_for_approval",
            current_step="request_human_approval", pending_approval_id=approval.id,
        )
        payload = {
            "approval_id": approval.id,
            "stage": "repair",
            "project": state.get("project"),
            "title": approval.title,
            "reason": approval.reason,
            "risk_level": approval.risk_level,
            "params": params,
            "expires_at": approval.expires_at,
            "diagnosis": {
                "probable_cause": diagnosis.get("probable_cause"),
                "confidence": diagnosis.get("confidence"),
                "recommended_action": diagnosis.get("recommended_action"),
                "evidence_refs": diagnosis.get("evidence_refs", []),
            },
            "simulated": bool(self.settings.demo_mode),
        }
        resume_value = interrupt(payload)

        async with self._step(state, "request_human_approval", status="running") as ctx:
            decision_payload = resume_value if isinstance(resume_value, dict) else {}
            approval_id = str(decision_payload.get("approval_id") or approval.id)
            row = await self.repo.get_approval(approval_id)
            if row is None or row.workflow_id != workflow_id or row.stage != "repair":
                raise PolicyViolation("درخواست تأیید معتبر برای این گردش‌کار یافت نشد.")
            if row.status == "rejected":
                ctx.summary = "کاربر درخواست اصلاح را رد کرد."
                ctx.set(decision="rejected")
                await self.audit.record(
                    "workflow.approval_rejected", target=workflow_id, outcome="rejected",
                    detail={"approval_id": approval_id, "stage": "repair"}, trace_id=workflow_id,
                )
                return self._step_result(
                    ctx, approval_decision="rejected", approval_id=approval_id,
                    outcome_status="cancelled", stop_reason="repair_rejected_by_user",
                    pending_approval_id=None, status="running",
                )
            if row.status != "approved":
                raise PolicyViolation(
                    f"وضعیت تأیید برای ادامه مناسب نیست: {row.status}",
                    details={"approval_id": approval_id},
                )
            await self.approvals.validate_and_consume(
                approval_id, workflow_id=workflow_id, params=params, required_stage="repair"
            )
            ctx.summary = "اصلاح تأیید شد؛ Workspace ایزوله ساخته می‌شود."
            ctx.set(decision="approved")
        return self._step_result(
            ctx, approval_decision="approved", approval_id=approval_id,
            pending_approval_id=None, status="running",
        )

    # ------------------------------------------------------------------
    # 9-12. repair loop
    # ------------------------------------------------------------------
    @_guarded
    async def prepare_workspace(self, state: WorkflowState) -> dict[str, Any]:
        async with self._step(state, "prepare_workspace") as ctx:
            prepared = await self.coding.prepare_workspace(
                workflow_id=state["workflow_id"], project=state["project"],
                attempt=int(state.get("attempt") or 0),
            )
            if prepared.get("needs_human"):
                ctx.summary = prepared.get("summary", "Workspace آماده نشد.")
                return self._step_result(
                    ctx, repair=prepared, outcome_status="needs_human",
                    stop_reason=prepared.get("summary"), status="running",
                )
            ctx.summary = (
                f"Workspace قبلی حفظ شد؛ شاخه {prepared.get('branch')}."
                if prepared.get("workspace_reused") else
                f"Workspace آماده شد؛ شاخه {prepared.get('branch')}."
            )
            ctx.set(branch=prepared.get("branch"),
                    workspace_reused=bool(prepared.get("workspace_reused")))
            await self.repo.update_workflow(
                state["workflow_id"],
                workspace=prepared.get("workspace"),
                branch=prepared.get("branch"),
            )
        return self._step_result(
            ctx,
            workspace=prepared.get("workspace"),
            branch=prepared.get("branch"),
            agent_run_id=prepared.get("run_id"),
            repair=prepared,
            status="running",
        )

    @_guarded
    async def run_coding_agent(self, state: WorkflowState) -> dict[str, Any]:
        async with self._step(state, "run_coding_agent") as ctx:
            repair = state.get("repair") or {}
            evidence = state.get("evidence") or {}
            result = await self.coding.execute_agent(
                run_id=state.get("agent_run_id") or repair.get("run_id") or "unknown",
                workflow_id=state["workflow_id"],
                project=state["project"],
                workspace=repair.get("workspace") or state.get("workspace") or "",
                branch=repair.get("branch") or state.get("branch") or "",
                diagnosis=state.get("diagnosis") or {},
                repair_plan=state.get("repair_plan") or {},
                evidence_summary=evidence.get("summary") or {},
                attempt=int(state.get("attempt") or 0),
                previous_failure=(state.get("repair_plan") or {}).get("previous_failure"),
            )
            ctx.summary = result.get("summary") or "ایجنت اجرا شد."
            ctx.set(
                provider=result.get("provider"), files_changed=result.get("files_changed"),
                simulated=result.get("simulated"),
            )
            merged = {**repair, **result, "workspace": result.get("workspace") or repair.get("workspace")}
            if result.get("status") != "success":
                needs_human = bool(result.get("needs_human"))
                return self._step_result(
                    ctx, repair=merged,
                    outcome_status="needs_human" if needs_human else "failed",
                    stop_reason=result.get("summary"), status="running",
                )
        return self._step_result(ctx, repair=merged, status="running")

    @_guarded
    async def run_tests(self, state: WorkflowState) -> dict[str, Any]:
        async with self._step(state, "run_tests", status="testing") as ctx:
            repair = state.get("repair") or {}
            workspace = repair.get("workspace") or state.get("workspace") or ""
            if not workspace:
                raise ValidationError("Workspace برای اجرای تست موجود نیست.")
            tests = await self.coding.run_tests_for(
                workflow_id=state["workflow_id"],
                run_id=state.get("agent_run_id"),
                workspace=workspace,
                simulated=bool(repair.get("simulated")),
            )
            await self.repo.update_workflow(state["workflow_id"], test_results=tests)
            passed = tests.get("status") == "passed"
            next_attempt = int(state.get("attempt") or 0) + 1
            max_attempts = int(state.get("max_attempts") or 3)
            if passed:
                ctx.summary = (
                    f"تست‌ها با {tests.get('runner')} اجرا شد: {tests.get('status')}"
                )
            elif next_attempt >= max_attempts:
                ctx.summary = (
                    f"تست‌ها پس از {next_attempt} تلاش شکست خوردند؛ "
                    "برای ادامه به کمک انسان نیاز است."
                )
            else:
                ctx.summary = (
                    f"تست‌ها با {tests.get('runner')} اجرا شد: {tests.get('status')}؛ "
                    "تلاش بعدی با Workspace حفظ‌شده انجام می‌شود."
                )
            ctx.set(test_status=tests.get("status"))
        updates: dict[str, Any] = {"tests": tests, "status": "running"}
        if not passed:
            updates["attempt"] = next_attempt
            await self.repo.update_workflow(state["workflow_id"], attempt=next_attempt)
            if next_attempt >= max_attempts:
                # Stop the loop explicitly and ask a human for help instead of
                # reporting a successful workflow after a failing test run.
                updates.update({
                    "outcome_status": "needs_human",
                    "stop_reason": "repair_attempts_exhausted",
                })
        return self._step_result(ctx, **updates)

    @_guarded
    async def review_diff(self, state: WorkflowState) -> dict[str, Any]:
        async with self._step(state, "review_diff") as ctx:
            repair = state.get("repair") or {}
            review = self.coding.review_changes(list(repair.get("files_changed") or []))
            review["diff"] = repair.get("diff", "")
            review["diff_truncated"] = repair.get("diff_truncated", False)
            ctx.summary = (
                "Diff تأیید شد." if review["ok"]
                else "Diff شامل تغییرات غیرمجاز است: " + "; ".join(review["violations"])
            )
            ctx.set(violations=review["violations"])
            if not review["ok"]:
                await self.audit.record(
                    "diff.rejected", target=state["workflow_id"], outcome="blocked",
                    detail={"violations": review["violations"]}, trace_id=state["workflow_id"],
                )
                return self._step_result(
                    ctx, review=review, outcome_status="failed",
                    stop_reason="Diff review failed: " + "; ".join(review["violations"]),
                    status="running",
                )
        return self._step_result(ctx, review=review, status="running")

    # ------------------------------------------------------------------
    # 13. prepare deployment (source upload)
    # ------------------------------------------------------------------
    @_guarded
    async def prepare_deployment(self, state: WorkflowState) -> dict[str, Any]:
        async with self._step(state, "prepare_deployment") as ctx:
            repair = state.get("repair") or {}
            workspace = repair.get("workspace") or state.get("workspace")
            if not workspace:
                raise ValidationError("Workspace برای بسته‌بندی سورس موجود نیست.")
            prepared = await self.deployment.prepare(
                workflow_id=state["workflow_id"], project=state["project"],
                workspace=workspace, attempt=int(state.get("attempt") or 0),
            )
            await self.repo.update_workflow(state["workflow_id"], deployment=prepared)
            ctx.summary = (
                f"سورس بسته‌بندی و ارسال شد (sourceID={prepared.get('source_id')})."
                if not prepared.get("simulated")
                else f"سورس شبیه‌سازی‌شده آماده شد (sourceID={prepared.get('source_id')})."
            )
            ctx.set(source_id=prepared.get("source_id"))
        return self._step_result(ctx, deployment=prepared, status="running")

    # ------------------------------------------------------------------
    # 14. deployment approval (interrupt)
    # ------------------------------------------------------------------
    @_guarded
    async def request_deployment_approval(self, state: WorkflowState) -> dict[str, Any]:
        workflow_id = state["workflow_id"]
        deployment = state.get("deployment") or {}
        plan = state.get("repair_plan") or {}
        params = {
            "project": state.get("project"),
            "source_id": deployment.get("source_id"),
            "port": deployment.get("port"),
            "project_type": deployment.get("project_type"),
        }
        if self.settings.hitl_require_production_deploy_approval:
            approval = await self.approvals.create(
                workflow_id=workflow_id,
                stage="deploy",
                action="create_release",
                project=state.get("project"),
                title="ساخت Release در لیارا",
                reason=(
                    f"انتشار نسخه اصلاح‌شده برای رفع «{plan.get('cause_key')}» پس از "
                    f"تأیید تست‌ها."
                ),
                params=params,
                risk_level="high",
                attempt=int(state.get("attempt") or 0),
                simulated=bool(self.settings.demo_mode),
            )
            await self.repo.update_workflow(
                workflow_id, status="waiting_for_approval",
                current_step="request_deployment_approval", pending_approval_id=approval.id,
            )
            payload = {
                "approval_id": approval.id,
                "stage": "deploy",
                "project": state.get("project"),
                "title": approval.title,
                "reason": approval.reason,
                "risk_level": "high",
                "params": params,
                "expires_at": approval.expires_at,
                "release": {
                    "source_id": deployment.get("source_id"),
                    "port": deployment.get("port"),
                    "port_source": deployment.get("port_source"),
                    "project_type": deployment.get("project_type"),
                },
                "simulated": bool(self.settings.demo_mode),
            }
            resume_value = interrupt(payload)
        else:  # pragma: no cover - configuration opt-out, still requires config policy
            resume_value = {"approval_id": None, "decision": "skipped"}

        async with self._step(state, "request_deployment_approval", status="running") as ctx:
            decision_payload = resume_value if isinstance(resume_value, dict) else {}
            approval_id = decision_payload.get("approval_id")
            if not self.settings.hitl_require_production_deploy_approval:  # pragma: no cover
                ctx.summary = "تأیید انتشار در تنظیمات غیرفعال است."
                return self._step_result(
                    ctx, deployment_approval_decision="skipped", status="running"
                )
            row = await self.repo.get_approval(str(approval_id))
            if row is None or row.workflow_id != workflow_id or row.stage != "deploy":
                raise PolicyViolation("درخواست تأیید انتشار معتبر نیست.")
            if row.status == "rejected":
                ctx.summary = "کاربر انتشار را رد کرد؛ هیچ Release ساخته نشد."
                ctx.set(decision="rejected")
                return self._step_result(
                    ctx, deployment_approval_decision="rejected",
                    deployment_approval_id=row.id, pending_approval_id=None,
                    outcome_status="cancelled", stop_reason="deployment_rejected_by_user",
                    status="running",
                )
            if row.status != "approved":
                raise PolicyViolation(f"وضعیت تأیید انتشار مناسب نیست: {row.status}")
            try:
                await self.approvals.validate(
                    row.id, workflow_id=workflow_id, params=params, required_stage="deploy"
                )
            except PolicyViolation as exc:
                ctx.summary = "تأیید انتشار با پارامترهای فعلی هم‌خوان نیست."
                ctx.set(decision="invalid")
                return self._step_result(
                    ctx, deployment_approval_id=row.id, pending_approval_id=None,
                    outcome_status="needs_human",
                    stop_reason=f"Stale deployment approval: {exc.message}", status="running",
                )
            ctx.summary = "انتشار تأیید شد."
            ctx.set(decision="approved")
        return self._step_result(
            ctx, deployment_approval_decision="approved", deployment_approval_id=row.id,
            pending_approval_id=None, status="running",
        )

    # ------------------------------------------------------------------
    # 15-17. deploy / verify / evaluate
    # ------------------------------------------------------------------
    @_guarded
    async def deploy_release(self, state: WorkflowState) -> dict[str, Any]:
        async with self._step(state, "deploy_release", status="deploying") as ctx:
            deployment = state.get("deployment") or {}
            approval_id = state.get("deployment_approval_id")
            if self.settings.hitl_require_production_deploy_approval and not approval_id:
                raise PolicyViolation("انتشار بدون approval_id مجاز نیست.")
            result = await self.deployment.deploy(
                workflow_id=state["workflow_id"],
                approval_id=approval_id,
                project=state["project"],
                source_id=deployment.get("source_id") or "",
                port=int(deployment.get("port") or 0),
                project_type=deployment.get("project_type") or "",
                attempt=int(state.get("attempt") or 0),
            )
            merged = {**deployment, **result}
            await self.repo.update_workflow(state["workflow_id"], deployment=merged)
            ctx.summary = (
                f"Release ساخته شد: {result.get('release_id')}"
                + (" (شبیه‌سازی‌شده)" if result.get("simulated") else "")
            )
            ctx.set(release_id=result.get("release_id"), simulated=result.get("simulated"))
        return self._step_result(ctx, deployment=merged, status="verifying")

    @_guarded
    async def verify_deployment(self, state: WorkflowState) -> dict[str, Any]:
        async with self._step(state, "verify_deployment", status="verifying") as ctx:
            verification = await self.verification.verify(
                workflow_id=state["workflow_id"], project=state["project"],
                deployment=state.get("deployment"),
            )
            await self.repo.update_workflow(state["workflow_id"], verification=verification)
            ctx.summary = f"وضعیت بررسی سلامت: {verification.get('status')}"
            ctx.set(status=verification.get("status"), simulated=verification.get("simulated"))
        return self._step_result(ctx, verification=verification, status="verifying")

    @_guarded
    async def evaluate_result(self, state: WorkflowState) -> dict[str, Any]:
        async with self._step(state, "evaluate_result") as ctx:
            verification = state.get("verification") or {}
            deployment = state.get("deployment") or {}
            status = verification.get("status")
            release_state = (deployment.get("release_state") or "").lower()
            if status == "verified":
                outcome, stop_reason = "completed", "deployed_and_verified"
            elif status == "failed":
                outcome, stop_reason = "failed", "health_check_failed"
            else:
                outcome, stop_reason = "completed", "deployed_unverified"
            if release_state in {"failed", "error"}:
                outcome, stop_reason = "failed", "release_failed"
            report = self._build_final_report(state, outcome=outcome, stop_reason=stop_reason)
            ctx.summary = f"نتیجه نهایی: {outcome} ({stop_reason})"
            ctx.set(outcome=outcome, stop_reason=stop_reason)
            await self.repo.update_workflow(
                state["workflow_id"], final_report=report, stop_reason=stop_reason,
            )
        return self._step_result(ctx, final_report=report, outcome_status=outcome,
                                 stop_reason=stop_reason, status="verifying")

    # ------------------------------------------------------------------
    # 18. finish
    # ------------------------------------------------------------------
    @_guarded
    async def finish_or_stop(self, state: WorkflowState) -> dict[str, Any]:
        async with self._step(state, "finish_or_stop", status="running") as ctx:
            final_status = self._final_status(state)
            report = state.get("final_report") or self._build_final_report(
                state, outcome=final_status, stop_reason=state.get("stop_reason")
            )
            report["final_status"] = final_status
            report["finished_at"] = iso()
            await self.repo.set_workflow_status(
                state["workflow_id"],
                final_status,
                final_report=report,
                stop_reason=state.get("stop_reason") or final_status,
                error=state.get("error"),
                pending_approval_id=None,
            )
            await self.audit.record(
                f"workflow.{final_status}",
                target=state["workflow_id"],
                outcome=final_status,
                detail={
                    "project": state.get("project"),
                    "stop_reason": state.get("stop_reason"),
                    "simulated": bool(state.get("simulated")),
                },
                trace_id=state["workflow_id"],
            )
            ctx.summary = f"گردش‌کار با وضعیت {final_status} پایان یافت."
        return self._step_result(
            ctx, status=final_status, current_step="finish_or_stop",
            final_report=report, updated_at=iso(),
        )

    # ------------------------------------------------------------------
    @staticmethod
    def _final_status(state: WorkflowState) -> str:
        outcome = state.get("outcome_status")
        if outcome in {"completed", "failed", "cancelled", "needs_human"}:
            return outcome
        if state.get("error"):
            return "failed"
        if state.get("approval_decision") == "rejected":
            return "cancelled"
        return "completed"

    def _build_final_report(self, state: WorkflowState, *, outcome: str,
                            stop_reason: str | None = None) -> dict[str, Any]:
        diagnosis = state.get("diagnosis") or {}
        repair = state.get("repair") or {}
        tests = state.get("tests") or {}
        deployment = state.get("deployment") or {}
        verification = state.get("verification") or {}
        simulated = bool(state.get("simulated", self.settings.demo_mode))

        remaining: list[str] = []
        if simulated:
            remaining.append("این اجرا در حالت DEMO / SIMULATED انجام شده و هیچ تغییری در لیارا ثبت نشده است.")
        if verification.get("status") == "unverified":
            remaining.append("بررسی سلامت تأیید نشد؛ DEPLOY_HEALTHCHECK_URL تنظیم نشده یا قابل استفاده نبود.")
        if verification.get("status") == "failed":
            remaining.append("Health Check ناموفق بود؛ انتشار موفق تلقی نمی‌شود.")
        if not self.settings.coding_agent_allow_git_push:
            remaining.append("Push به مخزن Git غیرفعال است؛ تغییرات فقط در Workspace محلی هستند.")
        if not tests:
            remaining.append("تست‌ها در این اجرا ثبت نشدند.")

        return {
            "workflow_id": state.get("workflow_id"),
            "project": state.get("project"),
            "mode": "demo" if simulated else "live",
            "simulated": simulated,
            "outcome": outcome,
            "stop_reason": stop_reason or state.get("stop_reason"),
            "generated_at": iso(),
            "problem": {
                "request": state.get("request_text"),
                "observation": diagnosis.get("observation"),
            },
            "evidence": {
                "refs": diagnosis.get("evidence_refs", []),
                "statements": diagnosis.get("evidence", []),
                "unavailable_sources": diagnosis.get("unavailable_sources", []),
                "resource_assessment": diagnosis.get("resource_assessment"),
            },
            "diagnosis": {
                "probable_cause": diagnosis.get("probable_cause"),
                "cause_key": diagnosis.get("probable_cause_key"),
                "alternatives": diagnosis.get("alternatives", []),
                "confidence": diagnosis.get("confidence"),
                "recommended_action": diagnosis.get("recommended_action"),
                "risk": diagnosis.get("risk"),
                "verification_method": diagnosis.get("verification_method"),
                "engine": diagnosis.get("engine"),
            },
            "change": {
                "provider": repair.get("provider"),
                "simulated_patch": repair.get("simulated"),
                "branch": repair.get("branch") or state.get("branch"),
                "workspace": repair.get("workspace") or state.get("workspace"),
                "files_changed": repair.get("files_changed", []),
                "diff": repair.get("diff", ""),
                "summary": repair.get("summary"),
                "git": repair.get("git"),
            },
            "tests": {
                "status": tests.get("status"),
                "runner": tests.get("runner"),
                "command": tests.get("command"),
                "exit_code": tests.get("exit_code"),
                "duration_ms": tests.get("duration_ms"),
                "output_tail": tests.get("output_tail"),
                "simulated_patch": tests.get("simulated_patch"),
            } if tests else None,
            "deployment": {
                "source_id": deployment.get("source_id"),
                "release_id": deployment.get("release_id"),
                "release_state": deployment.get("release_state"),
                "port": deployment.get("port"),
                "project_type": deployment.get("project_type"),
                "simulated": deployment.get("simulated"),
            } if deployment else None,
            "verification": verification or None,
            "human_actions": {
                "repair_approval": state.get("approval_decision"),
                "deployment_approval": state.get("deployment_approval_decision"),
            },
            "remaining_limitations": remaining,
            "server_time": iso(utcnow()),
        }
