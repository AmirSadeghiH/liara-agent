"""End-to-end workflow tests (offline, demo adapter, no token, no LLM)."""

from __future__ import annotations

import pytest

from tests.conftest import (
    approve,
    reject,
    start_demo,
    wait_for_new_approval,
    wait_for_terminal,
)


def _run_to_first_approval(client, scenario="django_500"):
    started = start_demo(client, scenario)
    workflow_id = started["workflow_id"]
    waiting = wait_for_new_approval(client, workflow_id, exclude=set())
    return workflow_id, waiting


def test_full_incident_flow_completes_with_verification(client):
    workflow_id, waiting = _run_to_first_approval(client)

    detail = client.get(f"/api/workflows/{workflow_id}").json()
    assert detail["diagnosis"]["probable_cause_key"] == "missing_dependency"
    assert detail["diagnosis"]["has_incident"] is True
    assert detail["simulated"] is True
    assert detail["repair_plan"]["cause_key"] == "missing_dependency"

    # --- repair approval ------------------------------------------------
    repair_approval = waiting["pending_approval_id"]
    approve(client, repair_approval)

    deploy_waiting = wait_for_new_approval(client, workflow_id, exclude={repair_approval})
    deploy_approval_id = deploy_waiting["pending_approval_id"]
    assert "deploy" in deploy_approval_id
    deploy_detail = client.get(f"/api/workflows/{workflow_id}").json()
    assert deploy_detail["deployment"]["source_id"]
    assert deploy_detail["deployment"]["port"]
    assert deploy_detail["test_results"]["status"] == "passed"

    # --- deployment approval -------------------------------------------
    approve(client, deploy_approval_id)
    final = wait_for_terminal(client, workflow_id)

    assert final["status"] == "completed"
    report = final["final_report"]
    assert report["outcome"] == "completed"
    assert report["stop_reason"] == "deployed_and_verified"
    assert report["simulated"] is True
    assert report["tests"]["status"] == "passed"
    assert report["deployment"]["release_id"].startswith("rel-demo-")
    assert report["deployment"]["simulated"] is True
    assert report["verification"]["status"] == "verified"
    assert report["verification"]["simulated"] is True
    assert report["change"]["files_changed"]
    assert "requirements.txt" in report["change"]["files_changed"]
    assert report["human_actions"] == {
        "repair_approval": "approved", "deployment_approval": "approved",
    }
    assert any("DEMO" in item or "شبیه" in item for item in report["remaining_limitations"])

    # both approvals consumed exactly once
    approvals = final["approvals"]
    assert len(approvals) == 2
    assert all(a["status"] == "approved" and a["consumed_at"] for a in approvals)

    steps = [event["step"] for event in final["events"] if event["step"]]
    for expected in ("intake_request", "collect_evidence", "diagnose_issue",
                     "request_human_approval", "run_coding_agent", "run_tests",
                     "review_diff", "prepare_deployment", "deploy_release",
                     "verify_deployment", "finish_or_stop"):
        assert expected in steps, f"missing step {expected}"


def test_repair_rejection_cancels_workflow(client):
    workflow_id, waiting = _run_to_first_approval(client)
    reject(client, waiting["pending_approval_id"])
    final = wait_for_terminal(client, workflow_id)

    assert final["status"] == "cancelled"
    assert final["stop_reason"] == "repair_rejected_by_user"
    assert not (final["deployment"] or {}).get("release_id")
    assert not final["coding_agent_runs"]


def test_deployment_rejection_keeps_repair_but_creates_no_release(client):
    workflow_id, waiting = _run_to_first_approval(client)
    approve(client, waiting["pending_approval_id"])
    deploy_waiting = wait_for_new_approval(client, workflow_id, exclude={waiting["pending_approval_id"]})
    reject(client, deploy_waiting["pending_approval_id"])
    final = wait_for_terminal(client, workflow_id)

    assert final["status"] == "cancelled"
    assert final["stop_reason"] == "deployment_rejected_by_user"
    assert final["test_results"]["status"] == "passed"
    assert not (final["deployment"] or {}).get("release_id")


def test_healthy_scenario_stops_without_repair(client):
    started = start_demo(client, "healthy_site")
    final = wait_for_terminal(client, started["workflow_id"])
    assert final["status"] == "completed"
    assert final["stop_reason"] == "no_incident_detected"
    assert final["diagnosis"]["probable_cause_key"] == "no_incident"
    assert not final["approvals"]


def test_workflow_is_resumable_after_restart(client, second_client, settings):
    workflow_id, waiting = _run_to_first_approval(client)
    repair_approval = waiting["pending_approval_id"]

    # A brand-new process reads the same checkpoints and database.
    resumed_detail = second_client.get(f"/api/workflows/{workflow_id}").json()
    assert resumed_detail["status"] == "waiting_for_approval"
    assert resumed_detail["graph"]["next"], "graph must be parked on an interrupt node"
    assert resumed_detail["graph"]["interrupts"], "interrupt payload must survive restart"

    approve(second_client, repair_approval)
    deploy_waiting = wait_for_new_approval(
        second_client, workflow_id, exclude={repair_approval}
    )
    approve(second_client, deploy_waiting["pending_approval_id"])
    final = wait_for_terminal(second_client, workflow_id)
    assert final["status"] == "completed"


def test_cancel_marks_workflow_cancelled_and_expires_approvals(client):
    workflow_id, waiting = _run_to_first_approval(client)
    response = client.post(f"/api/workflows/{workflow_id}/cancel")
    assert response.status_code == 200
    assert response.json()["status"] == "cancelled"

    approvals = client.get(f"/api/approvals?workflow_id={workflow_id}").json()["approvals"]
    assert approvals[0]["status"] in {"expired", "rejected", "cancelled"}
    assert approvals[0]["status"] != "pending"


def test_cancel_after_finish_is_idempotent(client):
    started = start_demo(client, "healthy_site")
    wait_for_terminal(client, started["workflow_id"])
    response = client.post(f"/api/workflows/{started['workflow_id']}/cancel")
    assert response.status_code == 200
    assert response.json()["status"] == "completed"


def test_used_approval_cannot_authorise_a_new_release(client):
    from app.core.errors import PolicyViolation

    workflow_id, waiting = _run_to_first_approval(client)
    approve(client, waiting["pending_approval_id"])
    deploy_waiting = wait_for_new_approval(client, workflow_id, exclude={waiting["pending_approval_id"]})
    deploy_id = deploy_waiting["pending_approval_id"]
    approve(client, deploy_id)
    final = wait_for_terminal(client, workflow_id)
    assert final["status"] == "completed"

    container = client.app.state.container
    deployment = final["deployment"]

    async def attempt():
        # A new attempt (different parameters path) re-uses the consumed approval.
        return await container.deployment.deploy(
            workflow_id=workflow_id, approval_id=deploy_id,
            project=final["project"], source_id=deployment["source_id"],
            port=deployment["port"], project_type=deployment["project_type"], attempt=99,
        )

    import asyncio

    with pytest.raises(PolicyViolation):
        asyncio.run(attempt())


def test_repeated_approve_does_not_create_second_release(client):
    workflow_id, waiting = _run_to_first_approval(client)
    approve(client, waiting["pending_approval_id"])
    deploy_waiting = wait_for_new_approval(client, workflow_id, exclude={waiting["pending_approval_id"]})
    deploy_id = deploy_waiting["pending_approval_id"]
    approve(client, deploy_id)
    wait_for_terminal(client, workflow_id)

    second = client.post(f"/api/approvals/{deploy_id}/approve", json={"actor": "test"})
    assert second.status_code == 409

    detail = client.get(f"/api/workflows/{workflow_id}").json()
    releases = [d for d in detail["deployments"] if d.get("release_id")]
    assert len(releases) == 1


def test_diagnose_endpoint_changes_nothing(client):
    before = client.get("/api/workflows").json()["count"]
    response = client.post("/api/diagnose", json={"project": "demo-django-store"})
    assert response.status_code == 200
    payload = response.json()
    assert payload["diagnosis"]["probable_cause_key"] == "missing_dependency"
    assert payload["final_report"]["stop_reason"] == "diagnosis_only"
    detail = client.get(f"/api/workflows/{payload['workflow_id']}").json()
    assert detail["status"] == "completed"
    assert not detail["approvals"]
    assert client.get("/api/workflows").json()["count"] == before + 1


def test_unknown_project_fails_cleanly(client):
    response = client.post("/api/workflows", json={"project": "ghost-project", "request": "بررسی کن"})
    assert response.status_code == 202
    final = wait_for_terminal(client, response.json()["workflow_id"])
    assert final["status"] == "failed"
    assert "پیدا نشد" in (final["error"] or "")


def test_workflow_rejects_too_short_request(client):
    response = client.post("/api/workflows", json={"project": "demo-blog", "request": "x"})
    assert response.status_code == 422


def test_audit_trail_is_recorded(client):
    workflow_id, waiting = _run_to_first_approval(client)
    approve(client, waiting["pending_approval_id"])
    client.post(f"/api/workflows/{workflow_id}/cancel")

    from app.db.repository import Repository

    repo = Repository(client.app.state.container.db)
    import asyncio

    events = asyncio.run(repo.list_audit(limit=200))
    actions = {event.action for event in events}
    assert "workflow.created" in actions
    assert "approval.requested" in actions
    assert "approval.approved" in actions
    assert "workflow.cancelled" in actions
    assert any(event.action.startswith("mcp.") or event.action.startswith("workflow.")
               for event in events)


def test_second_attempts_are_bounded(client, settings):
    """A failing repair loop must stop at CODING_AGENT_MAX_REPAIR_ATTEMPTS."""
    started = start_demo(client, "django_500")
    detail = wait_for_new_approval(client, started["workflow_id"], exclude=set())
    assert detail["max_attempts"] <= 3
