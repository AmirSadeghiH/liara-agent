"""Retry-loop guarantees.

A failing test used to send the graph back to ``prepare_repair_plan`` while
``prepare_workspace`` recreated the workspace from the fixture, silently throwing
away the previous attempt.  These tests pin the fixed behaviour:

* the workspace is preserved between attempts,
* the failed test output and the previous diff are given to the next attempt,
* the retry runs inside the already-approved repair plan (no duplicate approval),
* production deployment still requires its own approval,
* the loop stops with ``needs_human`` when attempts are exhausted.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from app.services import coding_agent_service
from app.services.coding_agent_service import WorkspaceManager, compute_diff, snapshot_workspace
from tests.conftest import approve, wait_for_new_approval, wait_for_terminal


class _AuditStub:
    async def record(self, *args, **kwargs) -> None:  # noqa: ANN002, ANN003
        return None


def test_workspace_preserved_only_when_requested(settings):
    manager = WorkspaceManager(settings, _AuditStub())

    first = asyncio.run(manager.create(workflow_id="wf-retry-unit", project="demo"))
    marker = first.path / "attempt-one.txt"
    marker.write_text("keep me", encoding="utf-8")

    second = asyncio.run(
        manager.create(workflow_id="wf-retry-unit", project="demo", preserve=True)
    )
    assert second.reused is True
    assert marker.is_file(), "preserve=True must not recreate the workspace"

    third = asyncio.run(
        manager.create(workflow_id="wf-retry-unit", project="demo", preserve=False)
    )
    assert third.reused is False
    assert not marker.exists(), "a fresh attempt still starts from the fixture"


def test_diff_uses_the_content_captured_before_the_agent(tmp_path):
    workspace = tmp_path / "ws"
    workspace.mkdir()
    target = workspace / "app.py"
    target.write_text("print('one')\n", encoding="utf-8")

    before = snapshot_workspace(workspace)
    target.write_text("print('two')\n", encoding="utf-8")
    (workspace / "new.txt").write_text("new file\n", encoding="utf-8")
    after = snapshot_workspace(workspace)
    diff = compute_diff(before, after, workspace)

    assert diff["files"] == ["app.py", "new.txt"]
    assert "-print('one')" in diff["diff"]
    assert "+print('two')" in diff["diff"]
    assert "+new file" in diff["diff"]


def test_repair_prompt_carries_previous_failure():
    prompt = coding_agent_service.build_repair_prompt(
        project="demo-django-store",
        workflow_id="wf-1",
        diagnosis={"confidence": "high", "probable_cause": "missing dependency"},
        evidence_summary={"error_samples": ["ModuleNotFoundError: django_filters"]},
        branch="ai-fix/wf-1",
        test_command="pytest -q",
        max_attempts=3,
        attempt=1,
        previous_failure={
            "attempt": 1,
            "test_status": "failed",
            "test_output_tail": "AssertionError: expected 2",
            "diff": "+import django_filters",
            "files_changed": ["store/settings.py"],
        },
    )
    flat = " ".join(prompt.split())
    assert "Attempt: 2 of 3" in flat
    assert "AssertionError: expected 2" in flat
    assert "+import django_filters" in flat
    assert "do not discard those changes" in flat


def test_retry_preserves_workspace_reuses_approval_and_carries_failure(
    client, monkeypatch
):
    container = client.app.state.container
    calls = {"tests": 0, "agent": 0}
    prompts: list[dict] = []

    original_tests = container.coding.run_tests_for
    original_agent_run = container.coding.agents["mock"].run
    original_build = coding_agent_service.build_repair_prompt

    def capture_prompt(**kwargs):
        prompts.append(kwargs)
        return original_build(**kwargs)

    monkeypatch.setattr(coding_agent_service, "build_repair_prompt", capture_prompt)

    async def agent_run(task):
        calls["agent"] += 1
        (task.workspace / f"attempt-{calls['agent']}.txt").write_text(
            "agent ran", encoding="utf-8"
        )
        return await original_agent_run(task)

    monkeypatch.setattr(container.coding.agents["mock"], "run", agent_run)

    async def flaky_tests(*, workflow_id, run_id, workspace, simulated):
        calls["tests"] += 1
        if calls["tests"] == 1:
            return {
                "status": "failed", "runner": "pytest", "command": "pytest -q",
                "exit_code": 1, "duration_ms": 12,
                "output_tail": "E AssertionError: expected 2", "timed_out": False,
                "simulated_patch": simulated,
            }
        assert (Path(workspace) / "attempt-1.txt").is_file(), (
            "the retry lost the first attempt's workspace changes"
        )
        return await original_tests(
            workflow_id=workflow_id, run_id=run_id, workspace=workspace,
            simulated=simulated,
        )

    monkeypatch.setattr(container.coding, "run_tests_for", flaky_tests)

    response = client.post(
        "/api/workflows",
        json={
            "project": "demo-django-store",
            "request": "خطای 500 را اصلاح کن",
            "max_attempts": 3,
        },
    )
    assert response.status_code == 202, response.text
    workflow_id = response.json()["workflow_id"]

    repair_wait = wait_for_new_approval(client, workflow_id, exclude=set())
    repair_approval = repair_wait["pending_approval_id"]
    approve(client, repair_approval)

    deploy_wait = wait_for_new_approval(client, workflow_id, exclude={repair_approval}, timeout=60)
    deploy_approval = deploy_wait["pending_approval_id"]
    assert deploy_approval != repair_approval
    approve(client, deploy_approval)

    final = wait_for_terminal(client, workflow_id, timeout=90)
    assert final["status"] == "completed"
    assert calls["tests"] >= 2
    assert calls["agent"] >= 2
    assert final["attempt"] == 1
    assert final["test_results"]["status"] == "passed"

    # No second repair approval was requested for the retry.
    repair_approvals = [a for a in final["approvals"] if a["stage"] == "repair"]
    assert len(repair_approvals) == 1
    assert repair_approvals[0]["id"] == repair_approval
    assert repair_approvals[0]["consumed_at"]

    # The workspace from attempt 1 survived and the agent added attempt 2.
    workspace = Path(final["workspace"])
    assert (workspace / "attempt-1.txt").is_file()
    assert (workspace / "attempt-2.txt").is_file()

    # The second prompt received the failing test output and the previous diff.
    retry_prompt = next(prompt for prompt in prompts if prompt.get("attempt") == 1)
    previous = retry_prompt["previous_failure"]
    assert previous is not None
    assert previous["test_output_tail"].startswith("E AssertionError")
    assert previous["test_status"] == "failed"
    assert "attempt-1.txt" in " ".join(previous["files_changed"])

    # The retry is audited as running under the original approval.
    from app.db.repository import Repository

    repo = Repository(container.db)
    events = asyncio.run(repo.list_audit(limit=200))
    assert any(event.action == "repair.retry_authorized" for event in events)


def test_exhausted_attempts_stop_and_ask_for_help(client, monkeypatch):
    container = client.app.state.container
    calls = {"tests": 0}

    async def always_fail(*, workflow_id, run_id, workspace, simulated):
        calls["tests"] += 1
        return {
            "status": "failed", "runner": "pytest", "command": "pytest -q",
            "exit_code": 1, "duration_ms": 5,
            "output_tail": "E AssertionError: still broken", "timed_out": False,
            "simulated_patch": simulated,
        }

    monkeypatch.setattr(container.coding, "run_tests_for", always_fail)
    monkeypatch.setattr(
        container.coding.agents["mock"], "run",
        _agent_that_always_changes(container.coding.agents["mock"]),
    )

    response = client.post(
        "/api/workflows",
        json={
            "project": "demo-django-store",
            "request": "خطا را اصلاح کن",
            "max_attempts": 2,
        },
    )
    workflow_id = response.json()["workflow_id"]
    waiting = wait_for_new_approval(client, workflow_id, exclude=set())
    approve(client, waiting["pending_approval_id"])

    final = wait_for_terminal(client, workflow_id, timeout=90)
    assert final["status"] == "needs_human"
    assert final["stop_reason"] == "repair_attempts_exhausted"
    assert calls["tests"] == 2  # bounded by max_attempts, never infinite
    repair_approvals = [a for a in final["approvals"] if a["stage"] == "repair"]
    assert len(repair_approvals) == 1


def _agent_that_always_changes(agent):
    original = agent.run
    counter = {"runs": 0}

    async def run(task):
        counter["runs"] += 1
        marker = task.workspace / f"attempt-marker-{counter['runs']}.txt"
        marker.write_text("changed", encoding="utf-8")
        return await original(task)

    return run
