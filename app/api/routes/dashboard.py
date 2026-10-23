"""Server-rendered Persian UI (Jinja2) — pages, login and logout."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.templating import Jinja2Templates

from app.api.deps import get_container
from app.api.serializers import (
    agent_run_dict,
    approval_dict,
    deployment_dict,
    evidence_dict,
    workflow_detail,
    workflow_summary,
)
from app.core.errors import AppError, NotFoundError
from app.core.security import SESSION_COOKIE, create_session_token
from app.core.utils import iso

logger = logging.getLogger(__name__)

router = APIRouter(tags=["ui"], include_in_schema=False)


def templates(request: Request) -> Jinja2Templates:
    return request.app.state.templates


def _base_context(request: Request, page: str, **extra: Any) -> dict[str, Any]:
    container = get_container(request)
    return {
        "request": request,
        "page": page,
        "app_name": container.settings.app_name,
        "demo_mode": container.settings.demo_mode,
        "simulated": container.adapter.simulated,
        "auth_enabled": container.settings.app_auth_enabled,
        "now": iso(),
        **extra,
    }


async def _pending_approvals(request: Request, limit: int = 5) -> list[dict[str, Any]]:
    container = get_container(request)
    rows = await container.approvals.list_pending()
    return [approval_dict(r) for r in rows[:limit]]


@router.get("/dashboard", response_class=HTMLResponse, summary="Overview dashboard (legacy)")
async def dashboard(request: Request) -> Response:
    container = get_container(request)
    stats = await container.repo.dashboard_stats()
    recent = await container.repo.list_workflows(limit=6)
    pending = await _pending_approvals(request, limit=5)
    deployments = await container.repo.list_deployments(limit=4)
    projects: list[dict[str, Any]] = []
    projects_error: str | None = None
    try:
        for project in await container.adapter.list_projects():
            projects.append({
                "name": project.name, "type": project.type, "status": project.status,
                "is_deployed": project.is_deployed, "plan_id": project.plan_id,
            })
    except AppError as exc:
        projects_error = exc.message
    readiness = container.settings.live_readiness()
    return templates(request).TemplateResponse(
        request,
        "dashboard.html",
        _base_context(
            request, "dashboard",
            stats=stats,
            projects=projects,
            projects_error=projects_error,
            recent=[workflow_summary(r) for r in recent],
            pending=pending,
            deployments=[deployment_dict(d) for d in deployments],
            scenarios=container.demo.scenarios(),
            readiness=readiness,
            coding_agent=await container.coding.availability(),
            adapter=container.adapter.describe(),
            health=await container.health(),
        ),
    )


@router.get("/projects", response_class=HTMLResponse, summary="Projects")
async def projects_page(request: Request) -> Response:
    container = get_container(request)
    projects: list[dict[str, Any]] = []
    error: str | None = None
    try:
        for project in await container.adapter.list_projects():
            projects.append({
                "name": project.name, "type": project.type, "status": project.status,
                "is_deployed": project.is_deployed, "plan_id": project.plan_id,
                "created_at": project.created_at,
            })
    except AppError as exc:
        error = exc.message
    return templates(request).TemplateResponse(
        request, "projects.html",
        _base_context(request, "projects", projects=projects, error=error,
                      adapter=container.adapter.describe(),
                      allowed_write_projects=container.settings.allowed_deploy_projects),
    )


@router.get("/diagnose", response_class=HTMLResponse, summary="Diagnose a project")
async def diagnose_page(request: Request, project: str | None = None) -> Response:
    container = get_container(request)
    projects: list[dict[str, Any]] = []
    try:
        projects = [{"name": p.name, "status": p.status, "type": p.type}
                    for p in await container.adapter.list_projects()]
    except AppError:
        pass
    suggested = project or (container.settings.demo_scenario and
                           getattr(container.adapter, "scenario", None) and
                           getattr(container.adapter.scenario, "project", None))
    return templates(request).TemplateResponse(
        request, "diagnose.html",
        _base_context(request, "diagnose", projects=projects, suggested=suggested,
                      coding_agent=await container.coding.availability(),
                      readiness=container.settings.live_readiness()),
    )


@router.get("/workflows", response_class=HTMLResponse, summary="Workflow history")
async def workflows_page(request: Request) -> Response:
    container = get_container(request)
    rows = await container.repo.list_workflows(limit=60)
    return templates(request).TemplateResponse(
        request, "workflows.html",
        _base_context(request, "workflows", workflows=[workflow_summary(r) for r in rows]),
    )


@router.get("/workflows/{workflow_id}", response_class=HTMLResponse, summary="Workflow detail")
async def workflow_page(workflow_id: str, request: Request) -> Response:
    container = get_container(request)
    row = await container.repo.get_workflow(workflow_id)
    if row is None:
        raise NotFoundError("Workflow not found.", details={"workflow_id": workflow_id})
    events = await container.repo.list_events(workflow_id)
    evidence = await container.repo.list_evidence(workflow_id)
    approvals = await container.repo.list_approvals(workflow_id=workflow_id, limit=50)
    agent_runs = await container.repo.list_agent_runs(workflow_id)
    deployments = await container.repo.list_deployments(workflow_id=workflow_id, limit=20)
    graph = await container.runner.graph_state(workflow_id)
    detail = workflow_detail(
        row, events=events, evidence=evidence, approvals=approvals,
        agent_runs=agent_runs, deployments=deployments, graph=graph,
    )
    pending = next((a for a in detail["approvals"] if a["status"] == "pending"), None)
    return templates(request).TemplateResponse(
        request, "workflow_detail.html",
        _base_context(request, "workflows", workflow=detail,
                      pending=pending,
                      evidence_rows=[evidence_dict(e) for e in evidence],
                      agent_runs=[agent_run_dict(r) for r in agent_runs],
                      deployments=[deployment_dict(d) for d in deployments]),
    )


@router.get("/approvals", response_class=HTMLResponse, summary="Pending approvals")
async def approvals_page(request: Request) -> Response:
    container = get_container(request)
    pending = await container.approvals.list_pending()
    history = await container.repo.list_approvals(limit=30)
    return templates(request).TemplateResponse(
        request, "approvals.html",
        _base_context(request, "approvals",
                      pending=[approval_dict(r) for r in pending],
                      history=[approval_dict(r) for r in history]),
    )


@router.get("/settings", response_class=HTMLResponse, summary="Configuration status")
async def settings_page(request: Request) -> Response:
    container = get_container(request)
    return templates(request).TemplateResponse(
        request, "settings.html",
        _base_context(
            request, "settings",
            status=container.settings.public_status(),
            readiness=await container.readiness(),
            pending_count=await container.repo.count_pending_approvals(),
            coding_agent=await container.coding.status_report(),
            adapter=container.adapter.describe(),
            scenarios=container.demo.scenarios(),
        ),
    )


@router.get("/mcp", response_class=HTMLResponse, summary="MCP integration guide")
async def mcp_page(request: Request) -> Response:
    container = get_container(request)
    python_bin = "python"
    return templates(request).TemplateResponse(
        request, "mcp.html",
        _base_context(request, "mcp", mode="demo" if container.settings.demo_mode else "live",
                      python_bin=python_bin),
    )


# ---------------------------------------------------------------------------
# authentication (only active when APP_AUTH_ENABLED=true)
# ---------------------------------------------------------------------------
@router.get("/login", response_class=HTMLResponse, summary="Sign in")
async def login_page(request: Request, next: str = "/") -> Response:
    container = get_container(request)
    if not container.settings.app_auth_enabled:
        return RedirectResponse("/", status_code=303)
    return templates(request).TemplateResponse(
        request, "login.html",
        _base_context(request, "login", next=next, error=None),
    )


@router.post("/login", response_class=HTMLResponse, summary="Sign in (form)")
async def login_submit(request: Request, token: str = Form(default=""), next: str = Form(default="/")):
    container = get_container(request)
    if not container.settings.app_auth_enabled:
        return RedirectResponse("/", status_code=303)
    import hmac

    if not hmac.compare_digest(token.strip(), container.settings.auth_token):
        return templates(request).TemplateResponse(
            request, "login.html",
            _base_context(request, "login", next=next, error="توکن دسترسی نامعتبر است."),
            status_code=401,
        )
    session = create_session_token(container.settings.app_secret_key.get_secret_value())
    response = RedirectResponse(next if next.startswith("/") else "/", status_code=303)
    response.set_cookie(
        SESSION_COOKIE, session, httponly=True, samesite="lax", max_age=12 * 3600,
        secure=container.settings.app_env == "production",
    )
    await container.audit.record("app.login", actor="ui", outcome="ok")
    return response


@router.get("/logout", summary="Sign out")
async def logout() -> Response:
    response = RedirectResponse("/login", status_code=303)
    response.delete_cookie(SESSION_COOKIE)
    return response
