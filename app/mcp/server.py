"""LiaraPilot MCP server (stdio transport).

Run locally for Claude Code / Codex:

    python -m app.mcp.server

Important: stdout is reserved for the MCP protocol.  All diagnostics go to
stderr (see :func:`app.core.logging.configure_logging`).
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
from typing import Any

from mcp.server.mcpserver import MCPServer

from app.core.config import Settings, get_settings
from app.core.logging import configure_logging
from app.mcp.tool_registry import TOOL_INDEX, Tool, ToolHandlers, tool_description
from app.services.container import AppContainer

logger = logging.getLogger(__name__)

INSTRUCTIONS = """LiaraPilot is an AI infrastructure engineer for apps hosted on Liara.

Workflow for an incident:
1. liara_list_projects → pick the project.
2. liara_diagnose_project → evidence-based diagnosis (logs, CPU, memory, releases).
3. liara_prepare_repair → proposed repair plan (no changes to Production).
4. Ask the human to approve in the LiaraPilot web UI; MCP tools cannot approve.
5. liara_get_workflow_status to follow the repair, tests and approvals.
6. For deployment: inspect liara_prepare_deployment, then call
   liara_deploy_approved_source with a valid, unconsumed approval_id.
7. liara_verify_deployment → health evidence. "unverified" is not success.

Security: never ask for or pass the Liara API token; it is held by the server.
Write tools require server-side approvals and configuration allowlists. Tools
marked risk=high must not be retried automatically.
"""


def build_server(container: AppContainer) -> MCPServer:
    handlers = ToolHandlers(container)
    runner = Tool(container)

    server = MCPServer(
        name="liarapilot",
        version="0.1.0",
        instructions=INSTRUCTIONS,
        log_level="ERROR",  # keep stdout/stderr clean; our logs go to stderr
    )

    # ---------------- read-only ----------------
    @server.tool(name="liara_list_projects",
                 description=tool_description(TOOL_INDEX["liara_list_projects"]))
    async def liara_list_projects(limit: int = 50) -> dict[str, Any]:
        """List Liara projects visible to the configured token (or demo data)."""
        return await runner.run("liara_list_projects", handlers.liara_list_projects(limit))

    @server.tool(name="liara_get_project_status",
                 description=tool_description(TOOL_INDEX["liara_get_project_status"]))
    async def liara_get_project_status(project: str) -> dict[str, Any]:
        """Get status, platform, plan and environment variable *names* for a project."""
        return await runner.run(
            "liara_get_project_status", handlers.liara_get_project_status(project)
        )

    @server.tool(name="liara_get_logs",
                 description=tool_description(TOOL_INDEX["liara_get_logs"]))
    async def liara_get_logs(project: str, minutes: int = 60, limit: int = 50) -> dict[str, Any]:
        """Fetch recent logs. Returned lines are sanitised (secrets masked, instruction-like text defused)."""
        return await runner.run(
            "liara_get_logs", handlers.liara_get_logs(project, minutes, limit)
        )

    @server.tool(name="liara_get_cpu_metrics",
                 description=tool_description(TOOL_INDEX["liara_get_cpu_metrics"]))
    async def liara_get_cpu_metrics(project: str, minutes: int = 60) -> dict[str, Any]:
        """CPU report from the documented metrics endpoint."""
        return await runner.run(
            "liara_get_cpu_metrics", handlers.liara_get_cpu_metrics(project, minutes)
        )

    @server.tool(name="liara_get_memory_metrics",
                 description=tool_description(TOOL_INDEX["liara_get_memory_metrics"]))
    async def liara_get_memory_metrics(project: str, minutes: int = 60) -> dict[str, Any]:
        """Memory report from the documented metrics endpoint."""
        return await runner.run(
            "liara_get_memory_metrics", handlers.liara_get_memory_metrics(project, minutes)
        )

    @server.tool(name="liara_get_release_history",
                 description=tool_description(TOOL_INDEX["liara_get_release_history"]))
    async def liara_get_release_history(project: str, count: int = 10) -> dict[str, Any]:
        """Release history from GET /v1/projects/{name}/releases."""
        return await runner.run(
            "liara_get_release_history", handlers.liara_get_release_history(project, count)
        )

    @server.tool(name="liara_diagnose_project",
                 description=tool_description(TOOL_INDEX["liara_diagnose_project"]))
    async def liara_diagnose_project(project: str,
                                     request_text: str = "علت خطا را با شواهد بررسی کن.") -> dict[str, Any]:
        """Collect evidence and return a structured diagnosis (no changes are made)."""
        return await runner.run(
            "liara_diagnose_project", handlers.liara_diagnose_project(project, request_text)
        )

    # ---------------- preparation ----------------
    @server.tool(name="liara_prepare_repair",
                 description=tool_description(TOOL_INDEX["liara_prepare_repair"]))
    async def liara_prepare_repair(project: str,
                                   request_text: str = "علت خطا را با شواهد بررسی کن.") -> dict[str, Any]:
        """Produce a repair plan without touching Production. Execution needs a human approval."""
        return await runner.run(
            "liara_prepare_repair", handlers.liara_prepare_repair(project, request_text)
        )

    @server.tool(name="liara_prepare_deployment",
                 description=tool_description(TOOL_INDEX["liara_prepare_deployment"]))
    async def liara_prepare_deployment(project: str) -> dict[str, Any]:
        """Check release prerequisites and the exact release parameters (no upload)."""
        return await runner.run(
            "liara_prepare_deployment", handlers.liara_prepare_deployment(project)
        )

    @server.tool(name="liara_get_workflow_status",
                 description=tool_description(TOOL_INDEX["liara_get_workflow_status"]))
    async def liara_get_workflow_status(workflow_id: str) -> dict[str, Any]:
        """Status, steps, pending approval and final report of a LiaraPilot workflow."""
        return await runner.run(
            "liara_get_workflow_status", handlers.liara_get_workflow_status(workflow_id)
        )

    # ---------------- sensitive ----------------
    @server.tool(name="liara_request_approval",
                 description=tool_description(TOOL_INDEX["liara_request_approval"]))
    async def liara_request_approval(workflow_id: str, stage: str = "repair") -> dict[str, Any]:
        """Create a server-side approval request (stage: repair|deploy) for a human to decide."""
        return await runner.run(
            "liara_request_approval", handlers.liara_request_approval(workflow_id, stage)
        )

    @server.tool(name="liara_deploy_approved_source",
                 description=tool_description(TOOL_INDEX["liara_deploy_approved_source"]))
    async def liara_deploy_approved_source(workflow_id: str, approval_id: str) -> dict[str, Any]:
        """Create the release for an already-prepared source, only with a valid approval_id."""
        return await runner.run(
            "liara_deploy_approved_source",
            handlers.liara_deploy_approved_source(workflow_id, approval_id),
        )

    @server.tool(name="liara_verify_deployment",
                 description=tool_description(TOOL_INDEX["liara_verify_deployment"]))
    async def liara_verify_deployment(workflow_id: str) -> dict[str, Any]:
        """Run the post-deployment health check and collect fresh log evidence."""
        return await runner.run(
            "liara_verify_deployment", handlers.liara_verify_deployment(workflow_id)
        )

    return server


async def _run(settings: Settings | None = None) -> None:
    settings = settings or get_settings()
    configure_logging(settings.log_level, stream=sys.stderr)
    container = AppContainer(settings)
    await container.start()
    server = build_server(container)
    logger.info("LiaraPilot MCP server ready", extra={"event_data": {
        "transport": "stdio", "mode": "demo" if settings.demo_mode else "live"}})
    try:
        await server.run_stdio_async()
    finally:
        await container.stop()


async def _selftest() -> int:
    """In-process smoke test: list tools and call a read-only tool."""
    settings = get_settings()
    configure_logging("WARNING", stream=sys.stderr)
    container = AppContainer(settings)
    await container.start()
    try:
        server = build_server(container)
        tools = await server.list_tools()
        result = await server.call_tool("liara_list_projects", {"limit": 5})
        structured = getattr(result, "structuredContent", None) or getattr(result, "structured_content", None)
        print(json.dumps({
            "ok": True,
            "tool_count": len(tools),
            "tools": [getattr(t, "name", None) for t in tools],
            "sample_call_ok": bool(structured),
            "mode": "demo" if settings.demo_mode else "live",
        }, ensure_ascii=False, indent=2))
        return 0
    finally:
        await container.stop()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="LiaraPilot MCP server (stdio)")
    parser.add_argument("--selftest", action="store_true", help="run an in-process smoke test")
    args = parser.parse_args(argv)
    try:
        if args.selftest:
            return asyncio.run(_selftest())
        asyncio.run(_run())
        return 0
    except KeyboardInterrupt:  # pragma: no cover
        return 130


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
