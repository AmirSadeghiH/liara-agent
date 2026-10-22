"""MCP tool contract: read-only, preparation and sensitive tools.

The tools are LiaraPilot's own contract - they are **not** Liara API endpoints.
Every handler delegates to the same services used by the web UI, so authorisation
(allowlist, writes enabled, approval fingerprint/expiry/single-use) is enforced
identically for agents and humans.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable
from dataclasses import dataclass
from typing import Any, Literal

from pydantic import BaseModel, Field

from app.agent.prompts import build_repair_plan
from app.core.errors import AppError, NotFoundError, PolicyViolation, ValidationError
from app.core.security import ensure_deploy_allowed, validate_project_name
from app.core.utils import iso, new_id
from app.liara.schemas import LogEntry, MetricSeries
from app.services.container import AppContainer
from app.services.diagnosis_service import sanitize_log_message

logger = logging.getLogger(__name__)

RiskLevel = Literal["low", "medium", "high"]
ToolKind = Literal["read", "prepare", "sensitive"]


@dataclass(frozen=True)
class ToolSpec:
    name: str
    kind: ToolKind
    risk_level: RiskLevel
    summary: str


TOOL_SPECS: list[ToolSpec] = [
    ToolSpec("liara_list_projects", "read", "low", "فهرست پروژه‌های لیارا"),
    ToolSpec("liara_get_project_status", "read", "low", "وضعیت یک پروژه (بدون مقادیر env)"),
    ToolSpec("liara_get_logs", "read", "low", "لاگ‌های پاک‌سازی‌شده پروژه"),
    ToolSpec("liara_get_cpu_metrics", "read", "low", "گزارش CPU پروژه"),
    ToolSpec("liara_get_memory_metrics", "read", "low", "گزارش حافظه پروژه"),
    ToolSpec("liara_get_release_history", "read", "low", "تاریخچه انتشارها"),
    ToolSpec("liara_diagnose_project", "read", "low", "تشخیص ساختاریافته با شواهد"),
    ToolSpec("liara_prepare_repair", "prepare", "medium", "برنامه اصلاح بدون تغییر Production"),
    ToolSpec("liara_prepare_deployment", "prepare", "medium", "بررسی پیش‌نیازهای انتشار"),
    ToolSpec("liara_get_workflow_status", "read", "low", "وضعیت گردش‌کار"),
    ToolSpec("liara_request_approval", "sensitive", "high", "ایجاد درخواست تأیید سروری"),
    ToolSpec("liara_deploy_approved_source", "sensitive", "high", "انتشار با تأیید معتبر"),
    ToolSpec("liara_verify_deployment", "sensitive", "medium", "بررسی سلامت پس از انتشار"),
]

TOOL_INDEX = {spec.name: spec for spec in TOOL_SPECS}


def tool_description(spec: ToolSpec) -> str:
    return (
        f"{spec.summary}. "
        f"[LiaraPilot tool · kind={spec.kind} · risk={spec.risk_level}] "
        + (
            "این ابزار داده را تغییر نمی‌دهد."
            if spec.kind == "read"
            else "این ابزار فقط آماده‌سازی می‌کند و تغییر Production نمی‌دهد."
            if spec.kind == "prepare"
            else "این ابزار حساس است و بدون approval_id معتبر سرور اجرا نمی‌شود."
        )
    )


class Tool:
    """Small helper that turns handlers into uniform JSON results."""

    def __init__(self, container: AppContainer) -> None:
        self.container = container

    async def run(self, spec_name: str, coro: Awaitable[dict[str, Any]]) -> dict[str, Any]:
        spec = TOOL_INDEX[spec_name]
        try:
            result = await coro
            await self.container.audit.record(
                f"mcp.{spec_name}", actor="mcp", outcome="ok",
                detail={"kind": spec.kind, "risk": spec.risk_level},
            )
            return {"ok": True, "tool": spec_name, "kind": spec.kind,
                    "risk_level": spec.risk_level, "result": result}
        except AppError as exc:
            await self.container.audit.record(
                f"mcp.{spec_name}", actor="mcp", outcome="error",
                detail={"code": exc.code, "message": exc.message},
            )
            return {
                "ok": False, "tool": spec_name, "kind": spec.kind,
                "risk_level": spec.risk_level,
                "error": {"code": exc.code, "message": exc.message, "details": exc.details},
            }


# ---------------------------------------------------------------------------
# input models (documented contract for each tool)
# ---------------------------------------------------------------------------
class ProjectInput(BaseModel):
    project: str = Field(description="نام پروژه در لیارا", max_length=80)


class LogsInput(ProjectInput):
    minutes: int = Field(default=60, ge=1, le=1440, description="بازه زمانی به دقیقه")
    limit: int = Field(default=50, ge=1, le=200, description="حداکثر تعداد خط")


class MetricsInput(ProjectInput):
    minutes: int = Field(default=60, ge=5, le=1440, description="بازه زمانی به دقیقه")


class ReleasesInput(ProjectInput):
    count: int = Field(default=10, ge=1, le=50)


class DiagnoseInput(ProjectInput):
    request_text: str = Field(default="علت خطا را با شواهد بررسی کن.", max_length=2000)


class WorkflowInput(BaseModel):
    workflow_id: str = Field(min_length=3, max_length=64)


class ApprovalInput(BaseModel):
    workflow_id: str = Field(min_length=3, max_length=64)
    stage: Literal["repair", "deploy"] = Field(description="مرحله‌ای که تأیید برای آن درخواست می‌شود")


class DeployInput(BaseModel):
    workflow_id: str = Field(min_length=3, max_length=64)
    approval_id: str = Field(min_length=8, max_length=120,
                             description="شناسه تأیید مصرف‌نشده و معتبر برای همین پارامترها")


# ---------------------------------------------------------------------------
# handlers
# ---------------------------------------------------------------------------
def _series_payload(series: MetricSeries) -> dict[str, Any]:
    return {
        **series.as_summary(),
        "points": [{"t": p.timestamp, "v": p.value} for p in series.points[-60:]],
    }


def _logs_payload(entries: list[LogEntry], limit: int) -> dict[str, Any]:
    logs = []
    flagged = 0
    for entry in entries[-limit:]:
        text, was_flagged = sanitize_log_message(entry.message)
        flagged += int(was_flagged)
        logs.append({"datetime": entry.datetime, "level": entry.level,
                     "type": entry.type, "message": text, "flagged": was_flagged})
    return {"count": len(logs), "flagged_instruction_lines": flagged, "logs": logs}


def policy_blockers(settings: Any, project: str, *, simulated: bool) -> tuple[list[str], list[str]]:
    """Return (blockers, warnings) for a live deployment, without any network call."""
    blockers: list[str] = []
    warnings: list[str] = []
    if simulated:
        warnings.append("حالت DEMO: انتشار فقط شبیه‌سازی می‌شود.")
    else:
        try:
            ensure_deploy_allowed(settings, project)
        except PolicyViolation as exc:
            blockers.append(exc.message)
        if not settings.liara_allow_writes:
            blockers.append("LIARA_ALLOW_WRITES=false — ارسال سورس مجاز نیست.")
        if not settings.liara_enable_deploy:
            blockers.append("LIARA_ENABLE_DEPLOY=false — ساخت Release مجاز نیست.")
    if not settings.deploy_healthcheck_url:
        warnings.append("DEPLOY_HEALTHCHECK_URL تنظیم نشده؛ نتیجه انتشار «تأییدنشده» ثبت می‌شود.")
    return blockers, warnings


class ToolHandlers:
    def __init__(self, container: AppContainer) -> None:
        self.c = container

    # ---------------- read-only ----------------
    async def liara_list_projects(self, limit: int = 50) -> dict[str, Any]:
        projects = await self.c.adapter.list_projects()
        return {
            "mode": self.c.adapter.mode,
            "simulated": self.c.adapter.simulated,
            "notice": "داده‌های شبیه‌سازی‌شده (DEMO)." if self.c.adapter.simulated else None,
            "count": len(projects),
            "projects": [
                {"name": p.name, "type": p.type, "status": p.status,
                 "is_deployed": p.is_deployed, "plan_id": p.plan_id}
                for p in projects[:limit]
            ],
        }

    async def liara_get_project_status(self, project: str) -> dict[str, Any]:
        project = validate_project_name(project)
        details = await self.c.adapter.get_project(project)
        return {
            "project": project,
            "mode": self.c.adapter.mode,
            "simulated": self.c.adapter.simulated,
            "status": details.status,
            "type": details.type,
            "is_deployed": details.is_deployed,
            "scale": details.scale,
            "plan_id": details.plan_id,
            "env_keys": details.env_keys,
            "note": "مقادیر متغیرهای محیطی هرگز برگردانده نمی‌شوند.",
        }

    async def liara_get_logs(self, project: str, minutes: int = 60, limit: int = 50) -> dict[str, Any]:
        from datetime import timedelta

        from app.core.utils import utcnow

        project = validate_project_name(project)
        entries = await self.c.adapter.get_logs(project, since=utcnow() - timedelta(minutes=minutes))
        return {
            "project": project,
            "mode": self.c.adapter.mode,
            "simulated": self.c.adapter.simulated,
            "since_minutes": minutes,
            **_logs_payload(entries, limit),
        }

    async def liara_get_cpu_metrics(self, project: str, minutes: int = 60) -> dict[str, Any]:
        from app.core.utils import utcnow

        project = validate_project_name(project)
        series = await self.c.adapter.get_cpu_metrics(
            project, since=utcnow().timestamp() - minutes * 60
        )
        return {"project": project, "simulated": self.c.adapter.simulated,
                "cpu": _series_payload(series)}

    async def liara_get_memory_metrics(self, project: str, minutes: int = 60) -> dict[str, Any]:
        from app.core.utils import utcnow

        project = validate_project_name(project)
        series = await self.c.adapter.get_memory_metrics(
            project, since=utcnow().timestamp() - minutes * 60
        )
        return {"project": project, "simulated": self.c.adapter.simulated,
                "memory": _series_payload(series)}

    async def liara_get_release_history(self, project: str, count: int = 10) -> dict[str, Any]:
        project = validate_project_name(project)
        page = await self.c.adapter.get_releases(project, count=count)
        return {
            "project": project,
            "simulated": self.c.adapter.simulated,
            "total": page.total,
            "current_release": page.current_release,
            "ready_releases_count": page.ready_releases_count,
            "platform": page.platform,
            "releases": [
                {"id": r.id, "state": r.state, "tag": r.tag, "port": r.port,
                 "created_at": r.created_at, "type": r.type,
                 "git_message": (r.git_info or {}).get("message") if r.git_info else None}
                for r in page.releases
            ],
        }

    async def liara_diagnose_project(self, project: str, request_text: str = "") -> dict[str, Any]:
        project = validate_project_name(project)
        workflow_id = new_id("mcp")
        bundle, report = await self.c.diagnosis.diagnose(
            workflow_id=workflow_id, project=project, attempt=0, request_text=request_text
        )
        return {
            "diagnosis_ref": workflow_id,
            "project": project,
            "mode": bundle.mode,
            "simulated": bundle.simulated,
            "has_incident": report.has_incident,
            "diagnosis": report.as_dict(),
            "evidence_ids": bundle.refs,
            "evidence": [
                {"id": evidence_id, "kind": kind}
                for kind, evidence_id in bundle.evidence_ids.items()
            ],
            "unavailable_sources": report.unavailable_sources,
        }

    # ---------------- preparation ----------------
    async def liara_prepare_repair(self, project: str, request_text: str = "") -> dict[str, Any]:
        project = validate_project_name(project)
        workflow_id = new_id("mcp")
        bundle, report = await self.c.diagnosis.diagnose(
            workflow_id=workflow_id, project=project, attempt=0, request_text=request_text
        )
        plan = build_repair_plan(report.as_dict(), project)
        return {
            "diagnosis_ref": workflow_id,
            "project": project,
            "simulated": bundle.simulated,
            "has_incident": report.has_incident,
            "probable_cause": report.probable_cause,
            "repair_plan": plan,
            "next_step": (
                "برای اعمال تغییرات، یک گردش‌کار در LiaraPilot بسازید؛ اصلاح فقط پس از "
                "تأیید انسانی در Workspace ایزوله اجرا می‌شود."
            ),
            "note": "هیچ فایلی تغییر نکرد و هیچ درخواستی به Production ارسال نشد.",
        }

    async def liara_prepare_deployment(self, project: str) -> dict[str, Any]:
        project = validate_project_name(project)
        settings = self.c.settings
        blockers, warnings = policy_blockers(
            settings, project, simulated=self.c.adapter.simulated
        )

        details = await self.c.adapter.get_project(project)
        port = None
        port_source = "previous_release"
        try:
            page = await self.c.adapter.get_releases(project, count=5)
            for release in page.releases:
                if release.port:
                    port = int(release.port)
                    break
        except AppError:
            pass
        if port is None:
            port = settings.liara_default_port
            port_source = "LIARA_DEFAULT_PORT"
        project_type = details.type
        if not project_type:
            blockers.append("نوع پلتفرم پروژه از API قابل تشخیص نیست؛ انتشار بدون type مجاز نیست.")

        return {
            "project": project,
            "simulated": self.c.adapter.simulated,
            "ready": not blockers,
            "blockers": blockers,
            "warnings": warnings,
            "release_params": {"port": port, "port_source": port_source,
                               "project_type": project_type},
            "approval_required": ["deploy"],
            "note": (
                "این ابزار فقط پیش‌نیازها را بررسی می‌کند. ارسال سورس در مرحله "
                "prepare_deployment گردش‌کار و ساخت Release فقط با approval_id معتبر انجام می‌شود."
            ),
        }

    # ---------------- workflow / approvals ----------------
    async def liara_get_workflow_status(self, workflow_id: str) -> dict[str, Any]:
        row = await self.c.repo.get_workflow(workflow_id)
        if row is None:
            raise NotFoundError("گردش‌کار یافت نشد.", details={"workflow_id": workflow_id})
        events = await self.c.repo.list_events(workflow_id)
        approvals = await self.c.repo.list_approvals(workflow_id=workflow_id, limit=10)
        pending = next((a for a in approvals if a.status == "pending"), None)
        return {
            "workflow_id": row.id,
            "project": row.project,
            "status": row.status,
            "current_step": row.current_step,
            "attempt": row.attempt,
            "max_attempts": row.max_attempts,
            "simulated": row.simulated,
            "stop_reason": row.stop_reason,
            "pending_approval": (
                {"id": pending.id, "stage": pending.stage, "risk_level": pending.risk_level,
                 "expires_at": pending.expires_at} if pending else None
            ),
            "steps": [
                {"step": e.step, "status": e.status,
                 "label": (e.data or {}).get("label_fa"), "at": e.created_at}
                for e in events if e.step and e.status in {"running", "completed", "failed"}
            ][-40:],
            "final_report": row.final_report,
        }

    async def liara_request_approval(self, workflow_id: str, stage: str = "repair") -> dict[str, Any]:
        if stage not in {"repair", "deploy"}:
            raise ValidationError("stage must be 'repair' or 'deploy'.")
        row = await self.c.repo.get_workflow(workflow_id)
        if row is None:
            raise NotFoundError("گردش‌کار یافت نشد.", details={"workflow_id": workflow_id})
        existing = await self.c.approvals.get_pending_for_workflow(workflow_id)
        if existing is not None:
            return {"approval_id": existing.id, "stage": existing.stage,
                    "status": existing.status, "expires_at": existing.expires_at,
                    "reused": True}
        if stage == "repair":
            plan = row.repair_plan or {}
            params = {
                "stage": "repair", "project": row.project,
                "cause_key": plan.get("cause_key"), "branch": plan.get("branch"),
                "files": plan.get("files", []), "attempt": row.attempt,
                "max_attempts": row.max_attempts, "simulated": row.simulated,
            }
            title = "اجرای اصلاح در Workspace و آماده‌سازی سورس"
            reason = (row.diagnosis or {}).get("probable_cause") or "اصلاح خطای شناسایی‌شده"
        else:
            deployment = row.deployment or {}
            if not deployment.get("source_id"):
                raise ValidationError(
                    "سورس این گردش‌کار هنوز آماده نشده است؛ تأیید انتشار معنا ندارد."
                )
            params = {
                "project": row.project, "source_id": deployment.get("source_id"),
                "port": deployment.get("port"), "project_type": deployment.get("project_type"),
            }
            title = "ساخت Release در لیارا"
            reason = "انتشار نسخه اصلاح‌شده پس از تأیید تست‌ها"
        approval = await self.c.approvals.create(
            workflow_id=workflow_id, stage=stage, action="create_release" if stage == "deploy"
            else "apply_repair_and_upload_source",
            project=row.project, title=title, reason=reason, params=params,
            risk_level="high" if stage == "deploy" else "medium",
            attempt=row.attempt, simulated=row.simulated,
        )
        return {
            "approval_id": approval.id, "stage": approval.stage, "status": approval.status,
            "risk_level": approval.risk_level, "expires_at": approval.expires_at,
            "params": approval.params, "reused": False,
            "next_step": "تصمیم انسان باید در رابط وب ثبت شود؛ ابزارهای MCP نمی‌توانند تأیید کنند.",
        }

    async def liara_deploy_approved_source(
        self, workflow_id: str, approval_id: str
    ) -> dict[str, Any]:
        row = await self.c.repo.get_workflow(workflow_id)
        if row is None:
            raise NotFoundError("گردش‌کار یافت نشد.", details={"workflow_id": workflow_id})
        deployment = row.deployment or {}
        if not deployment.get("source_id") or not deployment.get("port"):
            raise ValidationError(
                "سورس آماده‌شده برای این گردش‌کار وجود ندارد؛ ابتدا مرحله آماده‌سازی انتشار را اجرا کنید."
            )
        result = await self.c.deployment.deploy(
            workflow_id=workflow_id, approval_id=approval_id, project=row.project or "",
            source_id=deployment.get("source_id"), port=int(deployment.get("port")),
            project_type=deployment.get("project_type") or "", attempt=row.attempt,
        )
        merged = {**deployment, **result}
        await self.c.repo.update_workflow(workflow_id, deployment=merged)
        return {
            **result,
            "next_step": "برای بررسی نتیجه از liara_verify_deployment استفاده کنید.",
            "note": (
                "انتشار شبیه‌سازی‌شده است." if result.get("simulated")
                else "درخواست Release واقعی به لیارا ارسال شد."
            ),
        }

    async def liara_verify_deployment(self, workflow_id: str) -> dict[str, Any]:
        row = await self.c.repo.get_workflow(workflow_id)
        if row is None:
            raise NotFoundError("گردش‌کار یافت نشد.", details={"workflow_id": workflow_id})
        deployment = row.deployment or {}
        if not deployment.get("release_id") and not deployment.get("source_id"):
            raise ValidationError("برای این گردش‌کار انتشار/آماده‌سازی سورس ثبت نشده است.")
        verification = await self.c.verification.verify(
            workflow_id=workflow_id, project=row.project or "", deployment=deployment
        )
        await self.c.repo.update_workflow(
            workflow_id, verification=verification,
            current_step="verify_deployment",
        )
        return {
            "workflow_id": workflow_id,
            "project": row.project,
            "verification": verification,
            "verified": verification.get("status") == "verified",
            "checked_at": iso(),
            "note": (
                "نتیجه «unverified» به معنی موفقیت نیست؛ آدرس سلامت را تنظیم کنید."
                if verification.get("status") == "unverified" else None
            ),
        }
