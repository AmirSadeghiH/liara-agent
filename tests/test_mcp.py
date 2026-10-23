"""MCP server tests: registration, schemas, read tools, gated writes, stdio hygiene."""

from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
from pathlib import Path

from app.mcp.server import build_server
from app.mcp.tool_registry import TOOL_INDEX, TOOL_SPECS

EXPECTED_TOOLS = {
    "liara_list_projects",
    "liara_get_project_status",
    "liara_get_logs",
    "liara_get_cpu_metrics",
    "liara_get_memory_metrics",
    "liara_get_release_history",
    "liara_diagnose_project",
    "liara_prepare_repair",
    "liara_prepare_deployment",
    "liara_get_workflow_status",
    "liara_request_approval",
    "liara_deploy_approved_source",
    "liara_verify_deployment",
}


def test_all_tools_are_registered(client):
    server = build_server(client.app.state.container)
    tools = asyncio.run(server.list_tools())
    names = {tool.name for tool in tools}
    assert names == EXPECTED_TOOLS
    assert set(TOOL_INDEX) == EXPECTED_TOOLS


def test_tools_have_descriptions_and_input_schemas(client):
    server = build_server(client.app.state.container)
    tools = asyncio.run(server.list_tools())
    for tool in tools:
        assert tool.description and "LiaraPilot tool" in tool.description
        schema = getattr(tool, "inputSchema", None) or getattr(tool, "input_schema", None)
        assert schema is not None, f"{tool.name} has no input schema"
        assert "properties" in schema


def test_risk_metadata_is_declared():
    for spec in TOOL_SPECS:
        assert spec.risk_level in {"low", "medium", "high"}
        assert spec.kind in {"read", "prepare", "sensitive"}
    sensitive = {s.name for s in TOOL_SPECS if s.kind == "sensitive"}
    assert "liara_deploy_approved_source" in sensitive
    assert "liara_deploy_approved_source" in TOOL_INDEX["liara_deploy_approved_source"].name


async def call_tool(client, name: str, arguments: dict) -> dict:
    server = build_server(client.app.state.container)
    result = await server.call_tool(name, arguments)
    structured = getattr(result, "structuredContent", None) or getattr(
        result, "structured_content", None
    )
    if structured is None:
        content = getattr(result, "content", []) or []
        text = getattr(content[0], "text", "{}") if content else "{}"
        structured = json.loads(text)
    return structured


def test_read_tools_work_in_demo_mode(client):
    async def scenario():
        listed = await call_tool(client, "liara_list_projects", {"limit": 10})
        assert listed["ok"] is True
        assert listed["result"]["simulated"] is True
        assert listed["result"]["count"] >= 1

        status = await call_tool(client, "liara_get_project_status",
                                 {"project": "demo-django-store"})
        assert status["ok"] is True
        assert status["result"]["env_keys"]
        assert "supersecret" not in json.dumps(status)

        logs = await call_tool(client, "liara_get_logs",
                               {"project": "demo-django-store", "minutes": 120})
        assert logs["ok"] is True
        assert logs["result"]["count"] > 0
        assert logs["result"]["flagged_instruction_lines"] >= 1

        cpu = await call_tool(client, "liara_get_cpu_metrics", {"project": "demo-django-store"})
        assert cpu["result"]["cpu"]["maximum"] is not None

        mem = await call_tool(client, "liara_get_memory_metrics",
                              {"project": "demo-django-store"})
        assert mem["result"]["memory"]["count"] > 0

        releases = await call_tool(client, "liara_get_release_history",
                                   {"project": "demo-django-store", "count": 3})
        assert releases["result"]["releases"]

        diagnosis = await call_tool(client, "liara_diagnose_project",
                                    {"project": "demo-django-store"})
        assert diagnosis["result"]["diagnosis"]["probable_cause_key"] == "missing_dependency"
        assert diagnosis["result"]["evidence_ids"]

    asyncio.run(scenario())


def test_prepare_tools_do_not_mutate(client):
    async def scenario():
        prepared = await call_tool(client, "liara_prepare_repair",
                                   {"project": "demo-django-store"})
        assert prepared["ok"] is True
        assert prepared["result"]["repair_plan"]["cause_key"] == "missing_dependency"
        assert "هیچ فایلی تغییر نکرد" in prepared["result"]["note"]

        deploy = await call_tool(client, "liara_prepare_deployment",
                                 {"project": "demo-django-store"})
        assert deploy["ok"] is True
        assert deploy["result"]["release_params"]["port"]
        assert deploy["result"]["approval_required"] == ["deploy"]

    asyncio.run(scenario())


def test_deploy_tool_requires_valid_approval(client):
    async def scenario():
        blocked = await call_tool(client, "liara_deploy_approved_source",
                                  {"workflow_id": "wf-does-not-exist", "approval_id": "apv-fake-123"})
        assert blocked["ok"] is False
        assert blocked["error"]["code"] == "not_found"

    asyncio.run(scenario())


def test_live_deployment_policy_blockers_are_computed(tmp_path):
    """Live mode without policy flags reports blockers (no network call)."""
    from app.mcp.tool_registry import policy_blockers
    from tests.conftest import make_settings

    settings = make_settings(
        tmp_path, demo_mode=False, liara_api_token="a-real-looking-token",
        liara_allow_writes=False, liara_enable_deploy=False,
        liara_deploy_allowed_projects="",
    )
    blockers, warnings = policy_blockers(settings, "demo-django-store", simulated=False)
    joined = " ".join(blockers)
    assert "LIARA_ALLOW_WRITES" in joined
    assert "LIARA_ENABLE_DEPLOY" in joined
    assert "allowlist" in joined.lower() or "ALLOWED_PROJECTS" in joined
    assert any("HEALTHCHECK" in warning for warning in warnings)

    allowed, _ = policy_blockers(
        make_settings(tmp_path, demo_mode=False, liara_api_token="t",
                      liara_allow_writes=True, liara_enable_deploy=True,
                      liara_deploy_allowed_projects="demo-django-store",
                      deploy_healthcheck_url="https://example.com/health"),
        "demo-django-store", simulated=False,
    )
    assert allowed == []


def test_tool_wrapper_turns_policy_errors_into_structured_failures(client):
    from app.core.errors import PolicyViolation
    from app.mcp.tool_registry import Tool

    async def scenario():
        tool = Tool(client.app.state.container)

        async def denied():
            raise PolicyViolation("blocked by allowlist", details={"reason": "test"})

        result = await tool.run("liara_deploy_approved_source", denied())
        assert result["ok"] is False
        assert result["error"]["code"] == "policy_violation"
        assert "blocked" in result["error"]["message"]

    asyncio.run(scenario())


def test_stdio_selftest_writes_only_json_to_stdout():
    """`--selftest` must produce parseable JSON on stdout (no log noise)."""
    repo_root = Path(__file__).resolve().parents[1]
    env = dict(os.environ)
    env.update({
        "PYTHONPATH": str(repo_root),
        "DEMO_MODE": "true",
        "LLM_PROVIDER": "disabled",
        "CODING_AGENT_PROVIDER": "none",
        "DATA_DIR": "./data",
        "APP_ENV": "test",
        "DEMO_STEP_DELAY_SECONDS": "0",
    })
    proc = subprocess.run(
        [sys.executable, "-m", "app.mcp.server", "--selftest"],
        cwd=repo_root, env=env, capture_output=True, text=True, timeout=120,
    )
    assert proc.returncode == 0, proc.stderr[-3000:]
    payload = json.loads(proc.stdout)
    assert payload["ok"] is True
    assert payload["tool_count"] == len(EXPECTED_TOOLS)
    assert set(payload["tools"]) == EXPECTED_TOOLS
    assert payload["sample_call_ok"] is True
