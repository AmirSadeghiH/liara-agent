"""ORM -> API dictionary serialisers (no secrets, no ORM leakage)."""

from __future__ import annotations

import json
from typing import Any

from app.core.logging import redact_value
from app.db.models import (
    ApprovalRequest,
    AuditEvent,
    CodingAgentRun,
    DeploymentRecord,
    EvidenceRecord,
    WorkflowEvent,
    WorkflowRun,
)


def workflow_summary(row: WorkflowRun) -> dict[str, Any]:
    return {
        "workflow_id": row.id,
        "thread_id": row.thread_id,
        "project": row.project,
        "request": row.request_text,
        "status": row.status,
        "current_step": row.current_step,
        "risk_level": row.risk_level,
        "demo_mode": row.demo_mode,
        "simulated": row.simulated,
        "attempt": row.attempt,
        "max_attempts": row.max_attempts,
        "pending_approval_id": row.pending_approval_id,
        "stop_reason": row.stop_reason,
        "error": redact_value(row.error),
        "created_at": row.created_at,
        "updated_at": row.updated_at,
        "completed_at": row.completed_at,
        "created_by": row.created_by,
    }


def workflow_detail(
    row: WorkflowRun,
    *,
    events: list[WorkflowEvent] | None = None,
    evidence: list[EvidenceRecord] | None = None,
    approvals: list[ApprovalRequest] | None = None,
    agent_runs: list[CodingAgentRun] | None = None,
    deployments: list[DeploymentRecord] | None = None,
    graph: dict[str, Any] | None = None,
) -> dict[str, Any]:
    data = workflow_summary(row)
    data.update({
        "diagnosis": redact_value(row.diagnosis),
        "repair_plan": redact_value(row.repair_plan),
        "test_results": redact_value(row.test_results),
        "deployment": redact_value(row.deployment),
        "verification": redact_value(row.verification),
        "final_report": redact_value(row.final_report),
        "workspace": row.workspace,
        "branch": row.branch,
        "events": [event_dict(e) for e in (events or [])],
        "evidence": [evidence_dict(e) for e in (evidence or [])],
        "approvals": [approval_dict(a) for a in (approvals or [])],
        "coding_agent_runs": [agent_run_dict(r) for r in (agent_runs or [])],
        "deployments": [deployment_dict(d) for d in (deployments or [])],
        "graph": _graph_public(graph),
    })
    return data


def event_dict(row: WorkflowEvent) -> dict[str, Any]:
    return {
        "id": row.id,
        "workflow_id": row.workflow_id,
        "step": row.step,
        "status": row.status,
        "message": redact_value(row.message),
        "data": redact_value(row.data),
        "created_at": row.created_at,
    }


def evidence_dict(row: EvidenceRecord) -> dict[str, Any]:
    return {
        "id": row.id,
        "workflow_id": row.workflow_id,
        "project": row.project,
        "kind": row.kind,
        "source": row.source,
        "summary": redact_value(row.summary),
        "payload": redact_value(row.payload),
        "redacted": row.redacted,
        "simulated": row.simulated,
        "observed_at": row.observed_at,
    }


def approval_dict(row: ApprovalRequest) -> dict[str, Any]:
    return {
        "id": row.id,
        "workflow_id": row.workflow_id,
        "project": row.project,
        "action": row.action,
        "stage": row.stage,
        "risk_level": row.risk_level,
        "title": row.title,
        "reason": redact_value(row.reason),
        "params": redact_value(row.params),
        "fingerprint": row.fingerprint,
        "status": row.status,
        "requested_at": row.requested_at,
        "expires_at": row.expires_at,
        "decided_at": row.decided_at,
        "decided_by": row.decided_by,
        "decision_note": redact_value(row.decision_note),
        "consumed_at": row.consumed_at,
        "simulated": row.simulated,
    }


def deployment_dict(row: DeploymentRecord) -> dict[str, Any]:
    return {
        "id": row.id,
        "workflow_id": row.workflow_id,
        "project": row.project,
        "stage": row.stage,
        "status": row.status,
        "source_id": row.source_id,
        "release_id": row.release_id,
        "port": row.port,
        "project_type": row.project_type,
        "simulated": row.simulated,
        "approval_id": row.approval_id,
        "detail": redact_value(row.detail),
        "package": row.package,
        "created_at": row.created_at,
        "updated_at": row.updated_at,
    }


def agent_run_dict(row: CodingAgentRun) -> dict[str, Any]:
    return {
        "id": row.id,
        "workflow_id": row.workflow_id,
        "provider": row.provider,
        "status": row.status,
        "summary": row.prompt_summary,
        "simulated": row.simulated,
        "workspace": row.workspace,
        "branch": row.branch,
        "exit_code": row.exit_code,
        "duration_ms": row.duration_ms,
        "files_changed": row.files_changed,
        "diff": redact_value(row.diff),
        "test_results": redact_value(row.test_results),
        "error": redact_value(row.error),
        "created_at": row.created_at,
    }


def audit_dict(row: AuditEvent) -> dict[str, Any]:
    return {
        "id": row.id,
        "at": row.at,
        "actor": row.actor,
        "action": row.action,
        "target": row.target,
        "outcome": row.outcome,
        "trace_id": row.trace_id,
        "detail": redact_value(row.detail),
    }


def _graph_public(graph: dict[str, Any] | None) -> dict[str, Any] | None:
    if not graph:
        return None
    values = graph.get("values") or {}
    # Only expose a compact, already-public subset of the graph state.
    keys = ("current_step", "status", "attempt", "stop_reason", "approval_decision",
            "deployment_approval_decision", "branch", "workspace")
    return {
        "next": graph.get("next"),
        "interrupts": graph.get("interrupts"),
        "checkpoint_id": graph.get("checkpoint_id"),
        "values": {k: values.get(k) for k in keys if k in values},
        "error": graph.get("error"),
    }


def json_safe(value: Any) -> Any:
    """Best-effort conversion for JSON columns that may contain datetimes."""
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return json.loads(json.dumps(value, default=str))
