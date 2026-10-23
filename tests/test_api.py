"""Internal API and UI smoke tests."""

from __future__ import annotations

import pytest

from tests.conftest import start_demo, wait_for_new_approval, wait_for_terminal


def test_health_is_public_and_secret_free(client):
    response = client.get("/api/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["mode"] == "demo"
    assert body["simulated"] is True
    assert "token" not in response.text.lower()


def test_readiness_reports_capabilities(client):
    body = client.get("/api/readiness").json()
    assert body["ready"] is True
    assert body["mode"] == "demo"
    assert body["capabilities"]["deploy_enabled"] is False
    assert body["live"]["live_ready"] is False


def test_projects_endpoint_marks_demo(client):
    body = client.get("/api/projects").json()
    assert body["mode"] == "demo"
    assert body["simulated"] is True
    assert "شبیه‌سازی" in body["notice"]
    assert {p["name"] for p in body["projects"]} >= {"demo-django-store", "demo-blog"}


def test_project_detail_never_returns_env_values(client):
    body = client.get("/api/projects/demo-django-store").json()
    assert body["project"]["env_keys"]
    assert "envs" not in body["project"]


def test_logs_endpoint_returns_sanitised_lines(client):
    body = client.get("/api/projects/demo-django-store/logs").json()
    assert body["count"] > 0
    assert body["flagged_instruction_lines"] >= 1
    assert all("message" in line for line in body["logs"])


def test_metrics_endpoint(client):
    body = client.get("/api/projects/demo-django-store/metrics").json()
    assert body["cpu"]["maximum"] is not None
    assert body["memory"]["maximum"] is not None


def test_unknown_project_returns_404(client):
    assert client.get("/api/projects/nope-nope").status_code == 404


def test_demo_scenarios_endpoint(client):
    body = client.get("/api/demo/scenarios").json()
    assert body["demo_mode"] is True
    keys = {s["key"] for s in body["scenarios"]}
    assert {"django_500", "memory_pressure", "healthy_site"} <= keys


def test_settings_status_hides_secrets(client):
    body = client.get("/api/settings/status").json()
    assert body["demo_mode"] is True
    assert body["liara"]["token_configured"] is False
    assert "liara_api_token" not in body


def test_connection_test_in_demo_makes_no_network_call(client):
    body = client.post("/api/settings/test-liara-connection").json()
    assert body["ok"] is True
    assert body["simulated"] is True
    assert body["project_count"] >= 1


def test_openapi_schema_is_available(client):
    schema = client.get("/openapi.json").json()
    assert "/api/workflows" in schema["paths"]
    assert "/api/approvals/{approval_id}/approve" in schema["paths"]


@pytest.mark.parametrize(
    "page",
    ["/", "/projects", "/diagnose", "/workflows", "/approvals", "/settings", "/mcp"],
)
def test_ui_pages_render_in_persian_rtl(client, page):
    response = client.get(page)
    assert response.status_code == 200, response.text
    html = response.text
    assert 'dir="rtl"' in html
    assert 'lang="fa"' in html
    assert "LiaraPilot" in html


def test_dashboard_contains_demo_button(client):
    html = client.get("/").text
    assert "اجرای سناریوی دمو" in html
    assert "DEMO / SIMULATED" in html


def test_workflow_page_renders_with_approval_controls(client):
    started = start_demo(client, "django_500")
    waiting = wait_for_new_approval(client, started["workflow_id"], exclude=set())
    html = client.get(f"/workflows/{started['workflow_id']}").text
    assert "درخواست تأیید" in html
    assert waiting["pending_approval_id"] in html
    assert "data-decision=\"approved\"" in html or "data-decision='approved'" in html


def test_workflow_page_after_completion_has_report(client):
    started = start_demo(client, "healthy_site")
    wait_for_terminal(client, started["workflow_id"])
    html = client.get(f"/workflows/{started['workflow_id']}").text
    assert "گزارش نهایی" in html
    assert "no_incident_detected" in html


def test_workflow_404_for_missing_id(client):
    assert client.get("/api/workflows/wf-missing").status_code == 404
    assert client.get("/workflows/wf-missing").status_code == 404


def test_static_assets_are_served(client):
    assert client.get("/static/styles.css").status_code == 200
    assert client.get("/static/app.js").status_code == 200


def test_resume_without_pending_approval_is_400(client):
    started = start_demo(client, "healthy_site")
    wait_for_terminal(client, started["workflow_id"])
    response = client.post(f"/api/workflows/{started['workflow_id']}/resume", json={})
    assert response.status_code == 422
