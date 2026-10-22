"""Shared pytest fixtures.

Every test runs fully offline against the Demo adapter with a temporary data
directory.  No real token, LLM or network access is required.
"""

from __future__ import annotations

import time
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.main import create_app

TERMINAL = {"completed", "failed", "cancelled", "needs_human"}


@pytest.fixture(autouse=True)
def _isolated_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Never let a developer's real .env leak into tests."""
    for key in (
        "LIARA_API_TOKEN", "LLM_API_KEY", "APP_ACCESS_TOKEN", "APP_AUTH_ENABLED",
        "DEMO_MODE", "LIARA_ALLOW_WRITES", "LIARA_ENABLE_DEPLOY",
        "LIARA_DEPLOY_ALLOWED_PROJECTS", "CODING_AGENT_PROVIDER",
    ):
        monkeypatch.delenv(key, raising=False)


def make_settings(tmp_path: Path, **overrides: object) -> Settings:
    base: dict[str, object] = {
        "data_dir": tmp_path / "data",
        "database_url": f"sqlite+aiosqlite:///{tmp_path}/liarapilot.db",
        "langgraph_checkpoint_path": tmp_path / "cp.sqlite",
        "audit_log_path": tmp_path / "audit.jsonl",
        "coding_agent_workspace_root": tmp_path / "workspaces",
        "demo_mode": True,
        "llm_provider": "disabled",
        "coding_agent_provider": "none",
        "demo_step_delay_seconds": 0.0,
        "app_env": "test",
        "deploy_healthcheck_interval_seconds": 0.0,
        "log_level": "WARNING",
    }
    base.update(overrides)
    return Settings(**base)  # type: ignore[arg-type]


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return make_settings(tmp_path)


@pytest.fixture
def client(settings: Settings) -> Iterator[TestClient]:
    app = create_app(settings)
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def second_client(settings: Settings) -> Iterator[TestClient]:
    """A second app instance sharing the same database and checkpoints."""
    app = create_app(settings)
    with TestClient(app) as test_client:
        yield test_client


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------
def wait_for_workflow(
    client: TestClient, workflow_id: str, predicate, *, timeout: float = 30.0
) -> dict:
    """Poll the workflow until *predicate* is satisfied, else fail with context."""
    deadline = time.time() + timeout
    data: dict = {}
    while time.time() < deadline:
        response = client.get(f"/api/workflows/{workflow_id}")
        assert response.status_code == 200, response.text
        data = response.json()
        if predicate(data):
            return data
        time.sleep(0.05)
    raise AssertionError(
        f"workflow {workflow_id} did not reach the expected state; "
        f"status={data.get('status')} step={data.get('current_step')} "
        f"stop_reason={data.get('stop_reason')} events={[e['step'] for e in data.get('events', [])]}"
    )


def wait_for_terminal(client: TestClient, workflow_id: str, *, timeout: float = 40.0) -> dict:
    return wait_for_workflow(
        client, workflow_id, lambda data: data["status"] in TERMINAL, timeout=timeout
    )


def wait_for_new_approval(client: TestClient, workflow_id: str, *, exclude: set[str],
                          timeout: float = 30.0) -> dict:
    def _predicate(data: dict) -> bool:
        pending = data.get("pending_approval_id")
        return bool(pending) and pending not in exclude and data["status"] == "waiting_for_approval"

    return wait_for_workflow(client, workflow_id, _predicate, timeout=timeout)


def approve(client: TestClient, approval_id: str, *, actor: str = "test") -> dict:
    response = client.post(f"/api/approvals/{approval_id}/approve", json={"actor": actor})
    assert response.status_code == 200, response.text
    return response.json()


def reject(client: TestClient, approval_id: str, *, actor: str = "test") -> dict:
    response = client.post(f"/api/approvals/{approval_id}/reject", json={"actor": actor})
    assert response.status_code == 200, response.text
    return response.json()


def start_demo(client: TestClient, scenario: str = "django_500") -> dict:
    response = client.post("/api/demo/run-scenario", json={"scenario": scenario})
    assert response.status_code == 202, response.text
    return response.json()
