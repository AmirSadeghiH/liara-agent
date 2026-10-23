"""Conversational surface tests (offline demo, no LLM, no token)."""

from __future__ import annotations

import time

from app.services.ui_blocks import BLOCK_REGISTRY, validate_blocks
from tests.conftest import wait_for_terminal

TERMINAL = {"completed", "failed", "cancelled", "needs_human"}


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------
def new_conversation(client, title: str | None = None) -> str:
    response = client.post("/api/conversations", json={"title": title})
    assert response.status_code == 201, response.text
    return response.json()["conversation"]["id"]


def send(client, conversation_id: str, text: str, client_id: str | None = None) -> dict:
    payload: dict[str, object] = {"text": text}
    if client_id:
        payload["client_message_id"] = client_id
    response = client.post(f"/api/conversations/{conversation_id}/messages", json=payload)
    assert response.status_code == 200, response.text
    return response.json()


def live(client, conversation_id: str) -> dict:
    response = client.get(f"/api/conversations/{conversation_id}/live")
    assert response.status_code == 200, response.text
    return response.json()


def wait_for_live(client, conversation_id: str, predicate, *, timeout: float = 45.0) -> dict:
    deadline = time.time() + timeout
    data = {}
    while time.time() < deadline:
        data = live(client, conversation_id)
        if predicate(data):
            return data
        time.sleep(0.05)
    raise AssertionError(f"live state did not match; states={data.get('states')}")


def block_types(message: dict) -> list[str]:
    return [block["type"] for block in message.get("blocks") or []]


def find_block(message: dict, block_type: str) -> dict | None:
    return next(
        (block for block in message.get("blocks") or [] if block["type"] == block_type),
        None,
    )


def set_project(client, conversation_id: str, project: str = "demo-django-store") -> dict:
    response = client.post(
        f"/api/conversations/{conversation_id}/select-project",
        json={"project": project},
    )
    assert response.status_code == 200, response.text
    return response.json()


# ---------------------------------------------------------------------------
# routing and project context
# ---------------------------------------------------------------------------
def test_ambiguous_project_renders_picker_then_keeps_context(client):
    conversation_id = new_conversation(client)
    first = send(client, conversation_id, "وضعیت سایت من را بررسی کن")["assistant_message"]
    assert block_types(first) == ["project_picker"]
    picker = find_block(first, "project_picker")["props"]
    assert {item["name"] for item in picker["projects"]} >= {"demo-django-store", "demo-blog"}

    set_project(client, conversation_id)

    second = send(client, conversation_id, "وضعیت را بررسی کن")["assistant_message"]
    types = block_types(second)
    assert "project_overview" in types
    assert "metrics_panel" in types
    assert "log_viewer" in types
    assert second["data"]["intent"] == "status"
    assert find_block(second, "project_overview")["props"]["project"] == "demo-django-store"
    assert find_block(second, "metrics_panel")["props"]["simulated"] is True


def test_project_selection_continues_the_pending_request(client):
    conversation_id = new_conversation(client)
    first = send(client, conversation_id, "چرا خطای ۵۰۰ می‌دهد؟")["assistant_message"]
    assert block_types(first) == ["project_picker"]
    assert first["data"]["needs_project"] is True

    selected = set_project(client, conversation_id, "demo-django-store")
    assert selected["continued"] is True
    message = selected["assistant_message"]
    assert message["data"]["continued_after_project_selection"] is True
    assert "diagnosis_card" in block_types(message)
    assert find_block(message, "diagnosis_card")["props"]["project"] == "demo-django-store"

    # The unfinished request is answered once; choosing a project again later
    # must not replay it or start a duplicate workflow.
    again = set_project(client, conversation_id, "demo-blog")
    assert again.get("continued") is not True
    assert "project_overview" in block_types(again["assistant_message"])


def test_only_one_accessible_project_is_selected_without_asking(client, monkeypatch):
    container = client.app.state.container
    original = container.adapter.list_projects

    async def one_project():
        rows = await original()
        return rows[:1]

    monkeypatch.setattr(container.adapter, "list_projects", one_project)
    conversation_id = new_conversation(client)
    message = send(client, conversation_id, "وضعیت را بررسی کن")["assistant_message"]
    assert "project_picker" not in block_types(message)
    assert find_block(message, "project_overview")["props"]["project"] == "demo-django-store"


def test_explicit_project_name_wins_over_conversation_context(client):
    conversation_id = new_conversation(client)
    set_project(client, conversation_id, "demo-django-store")
    message = send(client, conversation_id, "وضعیت demo-blog را بررسی کن")["assistant_message"]
    assert find_block(message, "project_overview")["props"]["project"] == "demo-blog"


# ---------------------------------------------------------------------------
# diagnosis
# ---------------------------------------------------------------------------
def test_diagnosis_blocks_are_real_and_persisted(client, settings):
    conversation_id = new_conversation(client)
    set_project(client, conversation_id)
    response = send(client, conversation_id, "چرا اپلیکیشن خطای ۵۰۰ می‌دهد؟")
    message = response["assistant_message"]
    types = block_types(message)
    assert "diagnosis_card" in types
    assert "evidence_list" in types
    diagnosis = find_block(message, "diagnosis_card")["props"]
    assert diagnosis["cause_key"] == "missing_dependency"
    assert diagnosis["has_incident"] is True
    assert diagnosis["simulated"] is True
    evidence_refs = diagnosis["evidence_refs"]
    assert evidence_refs
    ids = {item["id"] for item in find_block(message, "evidence_list")["props"]["items"]}
    assert set(evidence_refs) <= ids
    assert response["workflow_id"]

    # Persisted: a brand-new app instance reads the same conversation.
    from fastapi.testclient import TestClient
    from app.main import create_app

    with TestClient(create_app(settings)) as second:
        detail = second.get(f"/api/conversations/{conversation_id}").json()
        persisted = next(m for m in detail["messages"] if m["id"] == message["id"])
        assert persisted["blocks"] == message["blocks"]
        assert persisted["workflow_id"] == response["workflow_id"]


def test_read_only_status_does_not_create_approvals_or_start_repair(client):
    conversation_id = new_conversation(client)
    set_project(client, conversation_id)
    before = client.get("/api/workflows").json()["count"]
    send(client, conversation_id, "مصرف CPU و RAM را بررسی کن")
    assert client.get("/api/workflows").json()["count"] == before
    approvals = client.get("/api/approvals", params={"workflow_id": "none"}).json()
    assert approvals["approvals"] == []


# ---------------------------------------------------------------------------
# repair, approval and deployment inside the chat
# ---------------------------------------------------------------------------
def test_full_repair_and_deploy_flow_runs_inside_one_conversation(client):
    conversation_id = new_conversation(client)
    set_project(client, conversation_id)
    send(client, conversation_id, "چرا خطای ۵۰۰ می‌دهد؟")

    started = send(client, conversation_id, "حالا با Codex درستش کن")
    workflow_id = started["workflow_id"]
    assert workflow_id, "repair must start a real workflow"
    assert started["assistant_message"]["data"]["live"] is True

    repair_wait = wait_for_live(
        client, conversation_id,
        lambda data: any(
            state["workflow_id"] == workflow_id
            and any(block["type"] == "approval_card"
                    and block["props"]["stage"] == "repair"
                    and block["props"]["status"] == "pending"
                    for block in state["blocks"])
            for state in data["states"]
        ),
    )
    state = next(s for s in repair_wait["states"] if s["workflow_id"] == workflow_id)
    assert state["current_step"] == "request_human_approval"
    repair_approval = next(
        block["props"] for block in state["blocks"] if block["type"] == "approval_card"
    )
    assert repair_approval["params"]["project"] == "demo-django-store"
    assert repair_approval["simulated"] is True

    approve_response = client.post(
        f"/api/conversations/{conversation_id}/approvals/{repair_approval['approval_id']}/approve",
        json={},
    )
    assert approve_response.status_code == 200, approve_response.text
    assert approve_response.json()["approval"]["status"] == "approved"

    deploy_wait = wait_for_live(
        client, conversation_id,
        lambda data: any(
            state["workflow_id"] == workflow_id
            and any(block["type"] == "approval_card"
                    and block["props"]["stage"] == "deploy"
                    and block["props"]["status"] == "pending"
                    for block in state["blocks"])
            for state in data["states"]
        ),
        timeout=60,
    )
    state = next(s for s in deploy_wait["states"] if s["workflow_id"] == workflow_id)
    assert state["current_step"] == "request_deployment_approval"
    assert any(block["type"] == "deployment_timeline" for block in state["blocks"])
    assert any(block["type"] == "test_results"
               and block["props"]["status"] == "passed" for block in state["blocks"])
    deploy_approval = next(
        block["props"] for block in state["blocks"] if block["type"] == "approval_card"
    )

    approve_response = client.post(
        f"/api/conversations/{conversation_id}/approvals/{deploy_approval['approval_id']}/approve",
        json={},
    )
    assert approve_response.status_code == 200, approve_response.text

    final_live = wait_for_live(
        client, conversation_id,
        lambda data: any(
            state["workflow_id"] == workflow_id and state["status"] in TERMINAL
            for state in data["states"]
        ),
        timeout=60,
    )
    state = next(s for s in final_live["states"] if s["workflow_id"] == workflow_id)
    types = [block["type"] for block in state["blocks"]]
    assert "final_report" in types
    assert "health_check_card" in types
    assert types.count("approval_card") == 1  # one current approval, not one per poll

    report = next(block["props"] for block in state["blocks"] if block["type"] == "final_report")
    assert report["outcome"] == "completed"
    assert report["verification_status"] == "verified"
    assert report["tests_status"] == "passed"
    health = next(block["props"] for block in state["blocks"] if block["type"] == "health_check_card")
    assert health["status"] == "verified" and health["verified"] is True
    release = next(block["props"] for block in state["blocks"] if block["type"] == "release_status")
    assert release["release_id"].startswith("rel-demo-")
    timeline = next(
        block["props"] for block in state["blocks"] if block["type"] == "deployment_timeline"
    )
    assert timeline["status"] == "completed"
    assert next(step for step in timeline["steps"] if step["key"] == "health")["status"] == "completed"
    agent = next(
        block["props"] for block in state["blocks"] if block["type"] == "coding_agent_status"
    )
    assert agent["summary"], "the agent's activity summary must reach the chat card"

    # The workflow is linked to the conversation and survives a detail reload.
    detail = client.get(f"/api/conversations/{conversation_id}").json()
    conversation = detail["conversation"]
    assert workflow_id in conversation["workflow_ids"]

    # Exactly two approvals total: repair + deploy (no duplicate repair approval).
    workflow = client.get(f"/api/workflows/{workflow_id}").json()
    assert len(workflow["approvals"]) == 2
    assert all(item["consumed_at"] for item in workflow["approvals"])


def test_rejection_is_reflected_in_the_same_conversation(client):
    conversation_id = new_conversation(client)
    set_project(client, conversation_id)
    started = send(client, conversation_id, "خطای سایت را اصلاح کن")
    workflow_id = started["workflow_id"]

    waiting = wait_for_live(
        client, conversation_id,
        lambda data: any(
            state["workflow_id"] == workflow_id
            and any(block["type"] == "approval_card"
                    and block["props"]["status"] == "pending"
                    for block in state["blocks"])
            for state in data["states"]
        ),
    )
    state = next(s for s in waiting["states"] if s["workflow_id"] == workflow_id)
    approval_id = next(
        block["props"]["approval_id"] for block in state["blocks"] if block["type"] == "approval_card"
    )
    rejected = client.post(
        f"/api/conversations/{conversation_id}/approvals/{approval_id}/reject",
        json={},
    )
    assert rejected.status_code == 200, rejected.text

    final_live = wait_for_live(
        client, conversation_id,
        lambda data: any(
            state["workflow_id"] == workflow_id and state["status"] in TERMINAL
            for state in data["states"]
        ),
    )
    state = next(s for s in final_live["states"] if s["workflow_id"] == workflow_id)
    report = next(block["props"] for block in state["blocks"] if block["type"] == "final_report")
    assert report["outcome"] == "cancelled"
    assert report["stop_reason"] == "repair_rejected_by_user"
    assert "release_status" not in [block["type"] for block in state["blocks"]]


def test_approval_cannot_be_used_from_another_conversation(client):
    first = new_conversation(client)
    set_project(client, first)
    started = send(client, first, "خطا را اصلاح کن")
    workflow_id = started["workflow_id"]
    waiting = wait_for_live(
        client, first,
        lambda data: any(
            state["workflow_id"] == workflow_id
            and any(block["type"] == "approval_card" for block in state["blocks"])
            for state in data["states"]
        ),
    )
    state = next(s for s in waiting["states"] if s["workflow_id"] == workflow_id)
    approval_id = next(
        block["props"]["approval_id"] for block in state["blocks"] if block["type"] == "approval_card"
    )

    second = new_conversation(client)
    response = client.post(
        f"/api/conversations/{second}/approvals/{approval_id}/approve", json={}
    )
    assert response.status_code == 404

    # Clean up: reject through the owning conversation.
    client.post(f"/api/conversations/{first}/approvals/{approval_id}/reject", json={})
    wait_for_terminal(client, workflow_id)


# ---------------------------------------------------------------------------
# idempotency, validation and error handling
# ---------------------------------------------------------------------------
def test_same_client_message_id_does_not_duplicate_messages_or_workflows(client):
    conversation_id = new_conversation(client)
    set_project(client, conversation_id)
    first = send(client, conversation_id, "وضعیت را بررسی کن", "client-abc")
    second = send(client, conversation_id, "وضعیت را بررسی کن", "client-abc")
    assert second["deduplicated"] is True
    assert second["user_message"]["id"] == first["user_message"]["id"]
    assert second["assistant_message"]["id"] == first["assistant_message"]["id"]
    messages = client.get(f"/api/conversations/{conversation_id}").json()["messages"]
    # The project-selection reply comes first; the duplicated send must add no
    # further messages at all.
    assert [m["role"] for m in messages] == ["assistant", "user", "assistant"]


def test_empty_message_is_rejected(client):
    conversation_id = new_conversation(client)
    response = client.post(
        f"/api/conversations/{conversation_id}/messages", json={"text": "   "}
    )
    assert response.status_code == 422


def test_unknown_ui_block_and_invalid_props_are_dropped():
    valid, errors = validate_blocks([
        {"type": "not_a_real_block", "props": {}},
        {"type": "<script>alert(1)</script>", "props": {}},
        {"type": "approval_card", "props": {"approval_id": "x"}},
    ])
    assert valid == []
    assert {error["error"] for error in errors} == {"unknown_block_type", "invalid_props"}


def test_every_registered_block_validates_its_own_schema():
    samples = {
        "project_picker": {"projects": [], "reason": None, "allow_search": True},
        "project_overview": {
            "project": "demo", "type": "django", "status": "running", "is_deployed": True,
            "plan_id": "p1", "mode": "demo", "simulated": True, "notice": None,
        },
        "diagnosis_card": {
            "project": "demo", "has_incident": True, "observation": "o",
            "probable_cause": "c", "cause_key": "missing_dependency", "confidence": "high",
            "evidence_refs": ["ev-1"], "alternatives": [], "recommended_action": "a",
            "risk": "r", "verification_method": "v", "engine": "rule_engine",
            "simulated": True, "unavailable_sources": [],
        },
        "evidence_list": {"items": [], "total": 0, "unavailable_sources": []},
        "metrics_panel": {
            "project": "demo", "range_minutes": 60,
            "cpu": {"available": False, "unit": "%", "points": [],
                    "average": None, "maximum": None, "last": None,
                    "unavailable_reason": "x"},
            "memory": {"available": False, "unit": "%", "points": [],
                       "average": None, "maximum": None, "last": None,
                       "unavailable_reason": "x"},
            "simulated": True, "source": "Liara Metrics API",
        },
        "log_viewer": {"project": "demo", "range_minutes": 60, "count": 0,
                       "flagged_instruction_lines": 0, "lines": [], "simulated": True},
        "repair_plan_card": {
            "cause_key": "missing_dependency", "title": "t", "summary": "s", "steps": [],
            "files": [], "risk_level": "medium", "attempt": 0, "max_attempts": 3,
            "branch": "b", "requires_tests": True, "simulated": True,
        },
        "coding_agent_status": {
            "provider": "mock", "status": "success", "attempt": 0, "summary": "s",
            "duration_ms": 1, "files_changed": [], "needs_human": False,
            "branch": "b", "simulated": True,
        },
        "diff_review": {"files": [], "diff": "", "truncated": False, "violations": [],
                        "warnings": [], "sensitive_files": [], "provider": "mock",
                        "simulated": True},
        "test_results": {"status": "passed", "runner": "pytest", "command": None,
                         "exit_code": 0, "duration_ms": 1, "output_tail": "",
                         "timed_out": False, "simulated": True},
        "approval_card": {
            "approval_id": "apr-1", "workflow_id": "wf-1", "stage": "repair",
            "action": "apply_repair_and_upload_source", "project": "demo", "title": "t",
            "reason": "r", "risk_level": "medium", "params": {}, "expires_at": "2030-01-01",
            "status": "pending", "simulated": True, "decision_note": None,
        },
        "deployment_timeline": {"project": "demo", "steps": [], "release_id": None,
                                "source_id": None, "port": None, "status": "pending",
                                "simulated": True},
        "release_status": {"project": "demo", "release_id": None, "release_state": None,
                           "source_id": None, "port": None, "simulated": True},
        "health_check_card": {"status": "unverified", "verified": False, "url": None,
                              "status_code": None, "checked_at": None, "reason": "x",
                              "simulated": True},
        "final_report": {"workflow_id": "wf-1", "project": "demo", "request": "r",
                         "outcome": "completed", "stop_reason": "s", "cause_key": None,
                         "probable_cause": None, "evidence_refs": [], "actions": [],
                         "tests_status": None, "deployment_status": None,
                         "verification_status": None, "human_actions": {},
                         "limitations": [], "simulated": True, "generated_at": None},
        "workflow_timeline": {"workflow_id": "wf-1", "project": "demo", "status": "running",
                              "current_step": None, "current_label": None, "attempt": 0,
                              "max_attempts": 3, "stop_reason": None, "error": None,
                              "steps": [], "simulated": True},
    }
    assert set(samples) == set(BLOCK_REGISTRY)
    for name, props in samples.items():
        valid, errors = validate_blocks([{"type": name, "props": props}])
        assert errors == [], (name, errors)
        assert valid[0]["type"] == name
