"""Generative UI block registry, validation and builders.

The model / orchestrator never emits free-form HTML, CSS or React.  It can only
select a *registered block name*; every block's ``props`` payload is validated
against a strict Pydantic schema before it is stored or rendered.  Anything that
does not validate is dropped and the caller falls back to plain text, so an
unknown block name can never crash the page.

Every builder in this module reads from real backend records (workflow rows,
evidence rows, agent runs, approvals, deployments, verification results) or from
an explicitly labelled demo fixture.  No value here is invented by a language
model.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app.agent.state import STEP_LABELS_FA


class _Props(BaseModel):
    model_config = ConfigDict(extra="forbid")


# ---------------------------------------------------------------------------
# prop schemas (one per registered block)
# ---------------------------------------------------------------------------
class ProjectOption(_Props):
    name: str
    type: str | None = None
    status: str | None = None
    is_deployed: bool | None = None


class ProjectPickerProps(_Props):
    projects: list[ProjectOption]
    reason: str | None = None
    allow_search: bool = True


class ProjectOverviewProps(_Props):
    project: str
    type: str | None = None
    status: str | None = None
    is_deployed: bool | None = None
    plan_id: str | None = None
    mode: Literal["demo", "live"]
    simulated: bool
    notice: str | None = None


class DiagnosisCardProps(_Props):
    project: str
    has_incident: bool
    observation: str
    probable_cause: str
    cause_key: str
    confidence: Literal["low", "medium", "high"]
    evidence_refs: list[str] = Field(default_factory=list)
    alternatives: list[str] = Field(default_factory=list)
    recommended_action: str = ""
    risk: str = ""
    verification_method: str = ""
    engine: str = "rule_engine"
    simulated: bool = False
    unavailable_sources: list[str] = Field(default_factory=list)


class EvidenceItem(_Props):
    id: str
    kind: str
    source: str
    summary: str
    observed_at: str | None = None
    simulated: bool = False


class EvidenceListProps(_Props):
    items: list[EvidenceItem]
    total: int
    unavailable_sources: list[str] = Field(default_factory=list)


class MetricPoint(_Props):
    t: float
    v: float


class MetricSeriesProps(_Props):
    available: bool
    unit: str = "%"
    average: float | None = None
    maximum: float | None = None
    last: float | None = None
    points: list[MetricPoint] = Field(default_factory=list)
    unavailable_reason: str | None = None


class MetricsPanelProps(_Props):
    project: str
    range_minutes: int
    cpu: MetricSeriesProps
    memory: MetricSeriesProps
    simulated: bool
    source: str = "Liara Metrics API"


class LogLine(_Props):
    datetime: str | None = None
    level: str = "info"
    message: str
    flagged: bool = False


class LogViewerProps(_Props):
    project: str
    range_minutes: int
    count: int
    flagged_instruction_lines: int = 0
    lines: list[LogLine]
    simulated: bool


class RepairPlanProps(_Props):
    cause_key: str
    title: str
    summary: str
    steps: list[str]
    files: list[str] = Field(default_factory=list)
    risk_level: str | None = None
    attempt: int = 0
    max_attempts: int = 1
    branch: str | None = None
    requires_tests: bool = True
    simulated: bool = False


class CodingAgentStatusProps(_Props):
    provider: str
    status: str
    attempt: int = 0
    summary: str = ""
    duration_ms: int | None = None
    files_changed: list[str] = Field(default_factory=list)
    needs_human: bool = False
    branch: str | None = None
    simulated: bool = False


class DiffReviewProps(_Props):
    files: list[str]
    diff: str
    truncated: bool = False
    violations: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    sensitive_files: list[str] = Field(default_factory=list)
    provider: str | None = None
    simulated: bool = False


class TestResultsProps(_Props):
    status: str
    runner: str
    command: str | None = None
    exit_code: int | None = None
    duration_ms: int | None = None
    output_tail: str = ""
    timed_out: bool = False
    simulated: bool = False


class ApprovalCardProps(_Props):
    approval_id: str
    workflow_id: str
    stage: Literal["repair", "deploy"]
    action: str
    project: str | None = None
    title: str
    reason: str
    risk_level: str
    params: dict[str, Any] = Field(default_factory=dict)
    expires_at: str
    status: str
    simulated: bool = False
    decision_note: str | None = None


class TimelineStep(_Props):
    key: str
    label: str
    status: str
    summary: str | None = None
    reference: str | None = None
    error: str | None = None


class DeploymentTimelineProps(_Props):
    project: str
    steps: list[TimelineStep]
    release_id: str | None = None
    source_id: str | None = None
    port: int | None = None
    status: str
    simulated: bool = False


class ReleaseStatusProps(_Props):
    project: str
    release_id: str | None = None
    release_state: str | None = None
    source_id: str | None = None
    port: int | None = None
    simulated: bool = False


class HealthCheckProps(_Props):
    status: Literal["verified", "failed", "unverified"]
    verified: bool
    url: str | None = None
    status_code: int | None = None
    checked_at: str | None = None
    reason: str | None = None
    simulated: bool = False


class FinalReportProps(_Props):
    workflow_id: str | None = None
    project: str | None = None
    request: str | None = None
    outcome: str
    stop_reason: str | None = None
    cause_key: str | None = None
    probable_cause: str | None = None
    evidence_refs: list[str] = Field(default_factory=list)
    actions: list[str] = Field(default_factory=list)
    tests_status: str | None = None
    deployment_status: str | None = None
    verification_status: str | None = None
    human_actions: dict[str, str | None] = Field(default_factory=dict)
    limitations: list[str] = Field(default_factory=list)
    simulated: bool = False
    generated_at: str | None = None


class WorkflowTimelineProps(_Props):
    workflow_id: str
    project: str | None = None
    status: str
    current_step: str | None = None
    current_label: str | None = None
    attempt: int = 0
    max_attempts: int = 1
    stop_reason: str | None = None
    error: str | None = None
    steps: list[TimelineStep] = Field(default_factory=list)
    simulated: bool = False


BLOCK_REGISTRY: dict[str, type[_Props]] = {
    "project_picker": ProjectPickerProps,
    "project_overview": ProjectOverviewProps,
    "diagnosis_card": DiagnosisCardProps,
    "evidence_list": EvidenceListProps,
    "metrics_panel": MetricsPanelProps,
    "log_viewer": LogViewerProps,
    "repair_plan_card": RepairPlanProps,
    "coding_agent_status": CodingAgentStatusProps,
    "diff_review": DiffReviewProps,
    "test_results": TestResultsProps,
    "approval_card": ApprovalCardProps,
    "deployment_timeline": DeploymentTimelineProps,
    "release_status": ReleaseStatusProps,
    "health_check_card": HealthCheckProps,
    "final_report": FinalReportProps,
    "workflow_timeline": WorkflowTimelineProps,
}

MAX_BLOCKS = 16


def make_block(name: str, props: dict[str, Any]) -> dict[str, Any]:
    return {"type": name, "props": props}


def validate_blocks(raw: Any, *, max_blocks: int = MAX_BLOCKS) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Validate untrusted block payloads against the registry.

    Returns ``(valid_blocks, errors)``.  Invalid entries are dropped instead of
    raising: an unknown component or malformed props must degrade to the plain
    text answer, never crash the conversation.
    """
    valid: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []
    if not isinstance(raw, list):
        return [], [{"error": "blocks_not_a_list"}]
    for item in raw[:max_blocks]:
        if not isinstance(item, dict):
            errors.append({"error": "block_not_an_object"})
            continue
        name = item.get("type")
        model = BLOCK_REGISTRY.get(name) if isinstance(name, str) else None
        if model is None:
            errors.append({"type": str(name)[:64], "error": "unknown_block_type"})
            continue
        try:
            props = model.model_validate(item.get("props") or {})
        except ValidationError as exc:
            errors.append({
                "type": name,
                "error": "invalid_props",
                "fields": [str(err.get("loc")) for err in exc.errors()[:5]],
            })
            continue
        valid.append({"type": name, "props": props.model_dump(mode="json")})
    return valid, errors


# ---------------------------------------------------------------------------
# builders
# ---------------------------------------------------------------------------
def _clean(value: Any, limit: int = 4000) -> str:
    text = str(value or "")
    return text if len(text) <= limit else text[: limit - 1] + "…"


def project_overview_block(
    project: dict[str, Any], *, simulated: bool, mode: str, notice: str | None
) -> dict[str, Any]:
    return make_block("project_overview", {
        "project": project.get("name") or "",
        "type": project.get("type"),
        "status": project.get("status"),
        "is_deployed": project.get("is_deployed"),
        "plan_id": project.get("plan_id"),
        "mode": mode,
        "simulated": simulated,
        "notice": notice,
    })


def project_picker_block(
    projects: list[dict[str, Any]], *, reason: str
) -> dict[str, Any]:
    return make_block("project_picker", {
        "projects": [
            {
                "name": p.get("name") or "",
                "type": p.get("type"),
                "status": p.get("status"),
                "is_deployed": p.get("is_deployed"),
            }
            for p in projects[:20]
        ],
        "reason": reason,
        "allow_search": True,
    })


def diagnosis_block(
    diagnosis: dict[str, Any], *, project: str, simulated: bool
) -> dict[str, Any]:
    return make_block("diagnosis_card", {
        "project": project,
        "has_incident": bool(diagnosis.get("has_incident")),
        "observation": _clean(diagnosis.get("observation")),
        "probable_cause": _clean(diagnosis.get("probable_cause")),
        "cause_key": _clean(diagnosis.get("probable_cause_key") or "unknown", 120),
        "confidence": diagnosis.get("confidence") if diagnosis.get("confidence") in
        {"low", "medium", "high"} else "low",
        "evidence_refs": [str(ref) for ref in (diagnosis.get("evidence_refs") or [])[:40]],
        "alternatives": [_clean(item, 600) for item in (diagnosis.get("alternatives") or [])[:5]],
        "recommended_action": _clean(diagnosis.get("recommended_action")),
        "risk": _clean(diagnosis.get("risk"), 1200),
        "verification_method": _clean(diagnosis.get("verification_method"), 1200),
        "engine": _clean(diagnosis.get("engine") or "rule_engine", 80),
        "simulated": simulated,
        "unavailable_sources": [_clean(item, 200) for item in
                                (diagnosis.get("unavailable_sources") or [])[:10]],
    })


def evidence_block(evidence_rows: list[dict[str, Any]], *, unavailable: list[str] | None = None) -> dict[str, Any]:
    return make_block("evidence_list", {
        "items": [
            {
                "id": str(row.get("id") or ""),
                "kind": str(row.get("kind") or "unknown"),
                "source": _clean(row.get("source"), 160),
                "summary": _clean(row.get("summary"), 900),
                "observed_at": row.get("observed_at"),
                "simulated": bool(row.get("simulated")),
            }
            for row in evidence_rows[:24]
        ],
        "total": len(evidence_rows),
        "unavailable_sources": [_clean(item, 200) for item in (unavailable or [])[:10]],
    })


def metrics_block(
    *,
    project: str,
    range_minutes: int,
    cpu: dict[str, Any],
    memory: dict[str, Any],
    simulated: bool,
) -> dict[str, Any]:
    def _series(payload: dict[str, Any]) -> dict[str, Any]:
        points = [
            {"t": float(p.get("t")), "v": float(p.get("v"))}
            for p in (payload.get("points") or [])
            if isinstance(p, dict) and p.get("t") is not None and p.get("v") is not None
        ][-120:]
        return {
            "available": bool(points),
            "unit": str(payload.get("unit") or "%"),
            "average": payload.get("average"),
            "maximum": payload.get("maximum"),
            "last": payload.get("last"),
            "points": points,
            "unavailable_reason": payload.get("unavailable_reason"),
        }

    return make_block("metrics_panel", {
        "project": project,
        "range_minutes": range_minutes,
        "cpu": _series(cpu),
        "memory": _series(memory),
        "simulated": simulated,
        "source": "Liara Metrics API",
    })


def logs_block(
    *,
    project: str,
    range_minutes: int,
    lines: list[dict[str, Any]],
    flagged: int,
    simulated: bool,
) -> dict[str, Any]:
    return make_block("log_viewer", {
        "project": project,
        "range_minutes": range_minutes,
        "count": len(lines),
        "flagged_instruction_lines": int(flagged),
        "lines": [
            {
                "datetime": line.get("datetime"),
                "level": str(line.get("level") or "info"),
                "message": _clean(line.get("message"), 2000),
                "flagged": bool(line.get("flagged")),
            }
            for line in lines[-120:]
        ],
        "simulated": simulated,
    })


def repair_plan_block(plan: dict[str, Any], *, risk_level: str | None, max_attempts: int) -> dict[str, Any]:
    return make_block("repair_plan_card", {
        "cause_key": _clean(plan.get("cause_key") or "unknown", 120),
        "title": _clean(plan.get("title_fa") or plan.get("title") or "برنامه اصلاح", 200),
        "summary": _clean(plan.get("summary_fa") or plan.get("summary")),
        "steps": [_clean(step, 400) for step in (plan.get("steps") or [])[:12]],
        "files": [str(item) for item in (plan.get("files") or [])[:20]],
        "risk_level": risk_level,
        "attempt": int(plan.get("attempt") or 0),
        "max_attempts": max_attempts,
        "branch": plan.get("branch"),
        "requires_tests": bool(plan.get("requires_tests", True)),
        "simulated": bool(plan.get("simulated")),
    })


def coding_agent_block(
    run: dict[str, Any], *, attempt: int, max_attempts: int, needs_human: bool, simulated: bool
) -> dict[str, Any]:
    status = str(run.get("status") or "unknown")
    return make_block("coding_agent_status", {
        "provider": str(run.get("provider") or "unknown"),
        "status": status,
        "attempt": attempt,
        "summary": _clean(run.get("error") or run.get("summary") or ""),
        "duration_ms": run.get("duration_ms"),
        "files_changed": [str(item) for item in (run.get("files_changed") or [])[:25]],
        "needs_human": needs_human,
        "branch": run.get("branch"),
        "simulated": simulated,
    })


def diff_block(
    run: dict[str, Any], *, review: dict[str, Any], simulated: bool
) -> dict[str, Any]:
    files = [str(item) for item in (run.get("files_changed") or [])]
    sensitive = [
        rel for rel in files
        if rel.split("/")[-1].startswith(".env")
        or rel.split("/")[-1] in {".netrc", ".npmrc", "id_rsa", "id_ed25519", ".pgpass"}
    ]
    return make_block("diff_review", {
        "files": files[:40],
        "diff": _clean(run.get("diff"), 24_000),
        "truncated": bool(run.get("diff_truncated")),
        "violations": [_clean(item, 300) for item in (review.get("violations") or [])],
        "warnings": [_clean(item, 300) for item in (review.get("warnings") or [])],
        "sensitive_files": sensitive,
        "provider": run.get("provider"),
        "simulated": simulated,
    })


def tests_block(tests: dict[str, Any]) -> dict[str, Any]:
    return make_block("test_results", {
        "status": str(tests.get("status") or "unknown"),
        "runner": str(tests.get("runner") or "unknown"),
        "command": tests.get("command"),
        "exit_code": tests.get("exit_code"),
        "duration_ms": tests.get("duration_ms"),
        "output_tail": _clean(tests.get("output_tail"), 6000),
        "timed_out": bool(tests.get("timed_out")),
        "simulated": bool(tests.get("simulated_patch")),
    })


def approval_block(approval: dict[str, Any]) -> dict[str, Any]:
    stage = approval.get("stage")
    return make_block("approval_card", {
        "approval_id": str(approval.get("id") or ""),
        "workflow_id": str(approval.get("workflow_id") or ""),
        "stage": stage if stage in {"repair", "deploy"} else "repair",
        "action": str(approval.get("action") or ""),
        "project": approval.get("project"),
        "title": _clean(approval.get("title") or "درخواست تأیید", 200),
        "reason": _clean(approval.get("reason"), 1200),
        "risk_level": str(approval.get("risk_level") or "medium"),
        "params": approval.get("params") or {},
        "expires_at": str(approval.get("expires_at") or ""),
        "status": str(approval.get("status") or "pending"),
        "simulated": bool(approval.get("simulated")),
        "decision_note": approval.get("decision_note"),
    })


def deployment_blocks(
    deployment: dict[str, Any], *, verification: dict[str, Any] | None = None
) -> list[dict[str, Any]]:
    project = str(deployment.get("project") or "")
    release_id = deployment.get("release_id")
    source_id = deployment.get("source_id")
    simulated = bool(deployment.get("simulated"))
    status = str(deployment.get("status") or "pending")
    health_status = str((verification or {}).get("status") or "")
    if status not in {"failed", "error"}:
        if health_status == "verified":
            status = "completed"
        elif release_id:
            status = "ready"
        elif source_id:
            status = "prepared"
    steps = [
        {
            "key": "prepare",
            "label": "بسته‌بندی و ارسال سورس",
            "status": "completed" if source_id else "pending",
            "summary": f"sourceID: {source_id}" if source_id else "در انتظار ارسال سورس",
            "reference": source_id,
            "error": None,
        },
        {
            "key": "release",
            "label": "ساخت Release",
            "status": "completed" if release_id else ("failed" if status in {"failed", "error"} else "pending"),
            "summary": f"release: {release_id}" if release_id else "در انتظار ساخت Release",
            "reference": release_id,
            "error": deployment.get("detail") if status in {"failed", "error"} else None,
        },
        {
            "key": "health",
            "label": "بررسی سلامت",
            "status": (
                "completed" if health_status == "verified"
                else "failed" if health_status == "failed"
                else "pending"
            ),
            "summary": (
                "Health Check با پاسخ مورد انتظار تأیید شد." if health_status == "verified"
                else "Health Check ناموفق بود." if health_status == "failed"
                else "نتیجه Health Check جداگانه و در کارت خودش گزارش می‌شود."
            ),
            "reference": (verification or {}).get("url"),
            "error": (verification or {}).get("reason") if health_status == "failed" else None,
        },
    ]
    blocks = [make_block("deployment_timeline", {
        "project": project,
        "steps": steps,
        "release_id": release_id,
        "source_id": source_id,
        "port": deployment.get("port"),
        "status": status,
        "simulated": simulated,
    })]
    if release_id:
        blocks.append(make_block("release_status", {
            "project": project,
            "release_id": release_id,
            "release_state": deployment.get("release_state"),
            "source_id": source_id,
            "port": deployment.get("port"),
            "simulated": simulated,
        }))
    return blocks


def health_block(verification: dict[str, Any]) -> dict[str, Any]:
    status = str(verification.get("status") or "unverified")
    if status not in {"verified", "failed", "unverified"}:
        status = "unverified"
    return make_block("health_check_card", {
        "status": status,
        "verified": status == "verified",
        "url": verification.get("url"),
        "status_code": verification.get("status_code"),
        "checked_at": verification.get("checked_at"),
        "reason": _clean(verification.get("reason"), 600),
        "simulated": bool(verification.get("simulated")),
    })


def final_report_block(report: dict[str, Any]) -> dict[str, Any]:
    diagnosis = report.get("diagnosis") or {}
    change = report.get("change") or {}
    tests = report.get("tests") or {}
    deployment = report.get("deployment") or {}
    verification = report.get("verification") or {}
    actions: list[str] = []
    if change.get("summary"):
        actions.append(_clean(change.get("summary"), 600))
    for rel in (change.get("files_changed") or [])[:8]:
        actions.append(f"تغییر فایل: {rel}")
    return make_block("final_report", {
        "workflow_id": report.get("workflow_id"),
        "project": report.get("project"),
        "request": _clean((report.get("problem") or {}).get("request"), 800),
        "outcome": str(report.get("outcome") or "unknown"),
        "stop_reason": report.get("stop_reason"),
        "cause_key": diagnosis.get("cause_key"),
        "probable_cause": _clean(diagnosis.get("probable_cause")),
        "evidence_refs": [str(ref) for ref in ((report.get("evidence") or {}).get("refs") or [])[:40]],
        "actions": actions,
        "tests_status": tests.get("status"),
        "deployment_status": deployment.get("release_state") or (
            "released" if deployment.get("release_id") else None),
        "verification_status": verification.get("status"),
        "human_actions": {
            str(k): (str(v) if v is not None else None)
            for k, v in (report.get("human_actions") or {}).items()
        },
        "limitations": [_clean(item, 500) for item in (report.get("remaining_limitations") or [])[:10]],
        "simulated": bool(report.get("simulated")),
        "generated_at": report.get("generated_at"),
    })


_STEP_ORDER = {name: index for index, name in enumerate(STEP_LABELS_FA)}


def workflow_timeline_block(detail: dict[str, Any]) -> dict[str, Any]:
    events = detail.get("events") or []
    approvals = detail.get("approvals") or []
    deployment = detail.get("deployment") or {}
    steps: dict[str, dict[str, Any]] = {}
    for event in events:
        step = event.get("step")
        if not step:
            continue
        label = (event.get("data") or {}).get("label_fa") or STEP_LABELS_FA.get(step, step)
        reference = None
        if step in {"request_human_approval", "request_deployment_approval"}:
            matching = [a for a in approvals if a.get("stage") == (
                "repair" if step == "request_human_approval" else "deploy")]
            reference = matching[-1]["id"] if matching else None
        if step == "deploy_release" and deployment.get("release_id"):
            reference = deployment["release_id"]
        steps[step] = {
            "key": step,
            "label": str(label),
            "status": str(event.get("status") or "running"),
            "summary": _clean(event.get("message"), 600),
            "reference": reference,
            "error": event.get("data", {}).get("error_code") if event.get("status") == "failed" else None,
        }
    current_step = detail.get("current_step")
    if current_step and current_step not in steps:
        steps[current_step] = {
            "key": current_step,
            "label": STEP_LABELS_FA.get(current_step, current_step),
            "status": "running",
            "summary": None,
            "reference": None,
            "error": None,
        }
    ordered = sorted(steps.values(), key=lambda item: _STEP_ORDER.get(item["key"], 99))
    current = detail.get("current_step")
    return make_block("workflow_timeline", {
        "workflow_id": detail.get("workflow_id") or "",
        "project": detail.get("project"),
        "status": str(detail.get("status") or "unknown"),
        "current_step": current,
        "current_label": STEP_LABELS_FA.get(current or "", current),
        "attempt": int(detail.get("attempt") or 0),
        "max_attempts": int(detail.get("max_attempts") or 1),
        "stop_reason": detail.get("stop_reason"),
        "error": _clean(detail.get("error"), 800),
        "steps": ordered,
        "simulated": bool(detail.get("simulated")),
    })


def workflow_blocks(detail: dict[str, Any], *, review: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    """Build the full Generative-UI set for one workflow snapshot.

    Blocks are deterministic and derived from the persisted workflow record.
    The frontend replaces the previous block list of the same workflow message,
    so polling never produces duplicate cards.
    """
    blocks: list[dict[str, Any]] = [workflow_timeline_block(detail)]
    diagnosis = detail.get("diagnosis") or {}
    if diagnosis:
        blocks.append(diagnosis_block(
            diagnosis, project=str(detail.get("project") or ""),
            simulated=bool(detail.get("simulated")),
        ))
        evidence = detail.get("evidence") or []
        if evidence:
            blocks.append(evidence_block(
                evidence, unavailable=diagnosis.get("unavailable_sources") or []
            ))
    plan = detail.get("repair_plan") or {}
    if plan:
        blocks.append(repair_plan_block(
            plan, risk_level=detail.get("risk_level"),
            max_attempts=int(detail.get("max_attempts") or 1),
        ))
    runs = detail.get("coding_agent_runs") or []
    if runs:
        latest = runs[-1]
        blocks.append(coding_agent_block(
            latest,
            attempt=int(detail.get("attempt") or 0),
            max_attempts=int(detail.get("max_attempts") or 1),
            needs_human=str(detail.get("status")) in {"needs_human", "failed"},
            simulated=bool(latest.get("simulated")),
        ))
        blocks.append(diff_block(
            latest,
            review=review or {"violations": [], "warnings": []},
            simulated=bool(latest.get("simulated")),
        ))
    tests = detail.get("test_results")
    if tests:
        blocks.append(tests_block(tests))
    # Exactly one approval card is rendered: the pending request when there is
    # one, otherwise the most recent decision.  The detail query returns rows
    # newest-first, so the pending approval must be looked up by id rather than
    # assumed to be the last element (that bug hid the deployment approval).
    approvals = detail.get("approvals") or []
    if approvals:
        pending_id = detail.get("pending_approval_id")
        selected = next((a for a in approvals if a.get("id") == pending_id), approvals[0])
        blocks.append(approval_block(selected))
    deployment = detail.get("deployment") or {}
    verification = detail.get("verification") or {}
    if deployment:
        blocks.extend(deployment_blocks(deployment, verification=verification))
    if verification:
        blocks.append(health_block(verification))
    report = detail.get("final_report")
    if report:
        blocks.append(final_report_block(report))
    return blocks
