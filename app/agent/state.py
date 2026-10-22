"""LangGraph workflow state.

The state is persisted by the LangGraph checkpointer (SQLite), so a process
restart can resume a workflow that is waiting for human approval.
"""

from __future__ import annotations

import operator
from typing import Annotated, Any, Literal, TypedDict

WorkflowStatus = Literal[
    "queued", "running", "waiting_for_approval", "testing", "deploying",
    "verifying", "completed", "failed", "cancelled", "needs_human",
]

STEP_LABELS_FA: dict[str, str] = {
    "intake_request": "دریافت درخواست",
    "resolve_project": "تشخیص پروژه",
    "collect_evidence": "جمع‌آوری شواهد",
    "normalize_evidence": "نرمال‌سازی و پاک‌سازی شواهد",
    "diagnose_issue": "تحلیل علت",
    "classify_risk": "تعیین سطح ریسک",
    "prepare_repair_plan": "ساخت برنامه اصلاح",
    "request_human_approval": "انتظار تأیید کاربر",
    "prepare_workspace": "آماده‌سازی Workspace",
    "run_coding_agent": "اجرای ایجنت کدنویسی",
    "run_tests": "اجرای تست‌ها",
    "review_diff": "بررسی Diff و فایل‌های حساس",
    "prepare_deployment": "آماده‌سازی و ارسال سورس",
    "request_deployment_approval": "انتظار تأیید انتشار",
    "deploy_release": "ساخت Release",
    "verify_deployment": "بررسی سلامت",
    "evaluate_result": "ارزیابی نتیجه",
    "finish_or_stop": "پایان",
}


class WorkflowState(TypedDict, total=False):
    # identity
    workflow_id: str
    thread_id: str
    project: str
    request_text: str
    demo_mode: bool
    simulated: bool
    started_at: str
    updated_at: str

    # control
    status: str
    current_step: str
    attempt: int
    max_attempts: int
    outcome_status: str | None
    stop_reason: str | None
    error: str | None

    # evidence / reasoning
    evidence: dict[str, Any]
    diagnosis: dict[str, Any]
    risk: dict[str, Any]
    repair_plan: dict[str, Any]

    # approvals
    approval_id: str | None
    approval_decision: str | None
    deployment_approval_id: str | None
    deployment_approval_decision: str | None

    # execution
    workspace: str | None
    branch: str | None
    agent_run_id: str | None
    repair: dict[str, Any]
    tests: dict[str, Any]
    review: dict[str, Any]
    deployment: dict[str, Any]
    verification: dict[str, Any]
    final_report: dict[str, Any]

    # progress trail (merged across nodes)
    steps: Annotated[list[dict[str, Any]], operator.add]
