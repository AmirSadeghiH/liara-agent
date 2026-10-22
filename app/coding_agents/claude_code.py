"""Claude Code adapter (headless ``claude -p``).

Flags are limited to documented, non-destructive options:

* ``-p`` headless mode, ``--output-format json`` for machine readable results,
* ``--permission-mode acceptEdits`` (edits are accepted inside the workspace;
  arbitrary shell commands still follow Claude Code's permission policy),
* ``--allowedTools`` restricted to file-editing tools for this workspace.

``--dangerously-skip-permissions`` is never used.
"""

from __future__ import annotations

import json
import logging

from app.coding_agents.base import (
    AgentAvailability,
    BaseCodingAgent,
    CodingAgentResult,
    CodingAgentTask,
    probe_binary,
    run_command,
    sanitized_env,
)

logger = logging.getLogger(__name__)

ALLOWED_TOOLS = "Read,Edit,Write,Glob,Grep"


class ClaudeCodeAdapter(BaseCodingAgent):
    name = "claude_code"
    simulated = False
    command_name = "claude"

    async def availability(self) -> AgentAvailability:
        installed, version = await probe_binary(self.command_name or "claude")
        return AgentAvailability(
            provider=self.name,
            installed=installed,
            version=version,
            ready=installed,
            reason=(
                "Claude Code CLI detected." if installed
                else "Claude Code CLI not found on PATH (install it or use manual handoff)."
            ),
            command=self.command_name,
        )

    def build_command(self, prompt: str) -> list[str]:
        return [
            self.command_name or "claude",
            "-p",
            prompt,
            "--output-format",
            "json",
            "--permission-mode",
            "acceptEdits",
            "--allowedTools",
            ALLOWED_TOOLS,
        ]

    async def run(self, task: CodingAgentTask) -> CodingAgentResult:
        availability = await self.availability()
        if not availability.installed:
            return CodingAgentResult(
                provider=self.name, status="unavailable", needs_human=True,
                summary="Claude Code CLI در این سیستم نصب نیست؛ کار به تحویل دستی سپرده شد.",
                error=availability.reason,
            )
        result = await run_command(
            self.build_command(task.prompt),
            cwd=task.workspace,
            max_seconds=task.timeout_seconds,
            env=sanitized_env(),
        )
        summary = ""
        metadata: dict[str, str | int | float | None] = {}
        try:
            payload = json.loads(result.stdout)
            if isinstance(payload, dict):
                summary = str(payload.get("result") or "").strip()
                metadata = {
                    "session_id": payload.get("session_id"),
                    "num_turns": payload.get("num_turns"),
                    "total_cost_usd": payload.get("total_cost_usd"),
                    "is_error": payload.get("is_error"),
                }
                if payload.get("is_error"):
                    return CodingAgentResult(
                        provider=self.name, status="failed", exit_code=result.returncode,
                        duration_ms=result.duration_ms, summary=summary or "Claude Code reported an error.",
                        stdout_tail=result.stdout[-4000:], stderr_tail=result.stderr[-4000:],
                        error="agent_reported_error", metadata=metadata,
                    )
        except json.JSONDecodeError:
            summary = (result.stdout or result.stderr).strip()[-2000:]

        if result.timed_out:
            return CodingAgentResult(
                provider=self.name, status="timeout", exit_code=result.returncode,
                duration_ms=result.duration_ms, summary="Claude Code timed out.",
                stderr_tail=result.stderr[-4000:], error="timeout", metadata=metadata,
            )
        if result.returncode != 0:
            return CodingAgentResult(
                provider=self.name, status="failed", exit_code=result.returncode,
                duration_ms=result.duration_ms,
                summary=summary or "Claude Code exited with a non-zero status.",
                stdout_tail=result.stdout[-4000:], stderr_tail=result.stderr[-4000:],
                error="non_zero_exit", metadata=metadata,
            )
        return CodingAgentResult(
            provider=self.name, status="success", exit_code=0,
            duration_ms=result.duration_ms,
            summary=summary or "Claude Code completed the task.",
            stdout_tail=result.stdout[-4000:], stderr_tail=result.stderr[-4000:],
            metadata=metadata,
        )
