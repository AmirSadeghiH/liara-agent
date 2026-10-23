"""Codex CLI adapter (``codex exec``).

Verified against developers.openai.com/codex/noninteractive:

* ``codex exec`` is non-interactive and read-only by default,
* ``--sandbox workspace-write`` allows edits inside the workspace,
* ``--skip-git-repo-check`` permits isolated (possibly non-git) workspaces,
* ``--json`` emits JSONL events; ``-o <file>`` writes the final message.

``--yolo`` / ``--dangerously-bypass-approvals-and-sandbox`` and
``danger-full-access`` are never used.  ``--full-auto`` is deprecated and is
also avoided.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

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


class CodexAdapter(BaseCodingAgent):
    name = "codex"
    simulated = False
    command_name = "codex"

    async def availability(self) -> AgentAvailability:
        installed, version = await probe_binary(self.command_name or "codex")
        return AgentAvailability(
            provider=self.name,
            installed=installed,
            version=version,
            ready=installed,
            reason=(
                "Codex CLI detected." if installed
                else "Codex CLI not found on PATH (install it or use manual handoff)."
            ),
            command=self.command_name,
        )

    def build_command(self, prompt: str, workspace: Path, output_file: Path) -> list[str]:
        return [
            self.command_name or "codex",
            "exec",
            "--sandbox",
            "workspace-write",
            "--skip-git-repo-check",
            "--json",
            "-C",
            str(workspace),
            "-o",
            str(output_file),
            prompt,
        ]

    async def run(self, task: CodingAgentTask) -> CodingAgentResult:
        availability = await self.availability()
        if not availability.installed:
            return CodingAgentResult(
                provider=self.name, status="unavailable", needs_human=True,
                summary="Codex CLI در این سیستم نصب نیست؛ کار به تحویل دستی سپرده شد.",
                error=availability.reason,
            )
        output_file = task.workspace / ".liarapilot-codex-last-message.txt"
        result = await run_command(
            self.build_command(task.prompt, task.workspace, output_file),
            cwd=task.workspace,
            max_seconds=task.timeout_seconds,
            env=sanitized_env(),
        )

        final_message = ""
        try:
            if output_file.exists():
                final_message = output_file.read_text(encoding="utf-8", errors="replace").strip()
                output_file.unlink(missing_ok=True)
        except OSError:  # pragma: no cover
            logger.warning("could not read codex output file", exc_info=True)

        metadata: dict[str, object] = {"events": 0}
        if not final_message and result.stdout:
            events = []
            for line in result.stdout.splitlines():
                line = line.strip()
                if not line.startswith("{"):
                    continue
                try:
                    events.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
            metadata["events"] = len(events)
            for event in reversed(events):
                for key in ("message", "text", "content", "last_message"):
                    value = event.get(key) if isinstance(event, dict) else None
                    if isinstance(value, str) and value.strip():
                        final_message = value
                        break
                if final_message:
                    break

        if result.timed_out:
            return CodingAgentResult(
                provider=self.name, status="timeout", duration_ms=result.duration_ms,
                summary="Codex timed out.", stderr_tail=result.stderr[-4000:],
                error="timeout", metadata=metadata,
            )
        if result.returncode != 0:
            return CodingAgentResult(
                provider=self.name, status="failed", exit_code=result.returncode,
                duration_ms=result.duration_ms,
                summary=final_message or result.stderr[-2000:] or "Codex exited with a non-zero status.",
                stdout_tail=result.stdout[-4000:], stderr_tail=result.stderr[-4000:],
                error="non_zero_exit", metadata=metadata,
            )
        return CodingAgentResult(
            provider=self.name, status="success", exit_code=0, duration_ms=result.duration_ms,
            summary=final_message or "Codex completed the task.",
            stdout_tail=result.stdout[-4000:], stderr_tail=result.stderr[-4000:],
            metadata=metadata,
        )
