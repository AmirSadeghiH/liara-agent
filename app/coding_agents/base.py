"""Coding-agent contract and safe subprocess execution.

Verified CLI behaviour (2026-10-22):

* Claude Code: ``claude -p "<prompt>" --output-format json`` runs headless
  (code.claude.com/docs/en/headless).  Permission prompts are *not* bypassed;
  we use ``--permission-mode acceptEdits`` and a narrow ``--allowedTools`` list.
* Codex: ``codex exec --sandbox workspace-write --skip-git-repo-check --json``
  runs non-interactively (developers.openai.com/codex/noninteractive).
  ``--full-auto`` is deprecated and ``danger-full-access`` / ``--yolo`` are
  never used.

The Liara token is never passed to these processes: the environment is filtered
before each run.
"""

from __future__ import annotations

import asyncio
import logging
import os
import re
import shutil
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

logger = logging.getLogger(__name__)

MAX_OUTPUT_CHARS = 20_000
ENV_DENY_PREFIXES = ("LIARA_", "APP_", "LLM_", "DATABASE_URL", "LANGGRAPH_", "AUDIT_", "CODEX_API_KEY")
ENV_DENY_EXACT = {
    "LIARA_API_TOKEN", "APP_ACCESS_TOKEN", "APP_SECRET_KEY", "LLM_API_KEY",
    "OPENAI_API_KEY",
}
ENV_DENY_PATTERN = re.compile(r"(TOKEN|SECRET|PASSWORD|API_KEY|ACCESS_KEY|PRIVATE_KEY)$", re.IGNORECASE)

AgentStatus = Literal["success", "failed", "needs_human", "unavailable", "timeout"]


@dataclass
class CommandResult:
    returncode: int | None
    stdout: str
    stderr: str
    duration_ms: int
    timed_out: bool = False

    @property
    def ok(self) -> bool:
        return self.returncode == 0 and not self.timed_out


@dataclass
class AgentAvailability:
    provider: str
    installed: bool
    version: str | None = None
    ready: bool = False
    reason: str = ""
    command: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "provider": self.provider, "installed": self.installed, "version": self.version,
            "ready": self.ready, "reason": self.reason, "command": self.command,
        }


@dataclass
class CodingAgentTask:
    workspace: Path
    branch: str
    prompt: str
    evidence_summary: str
    max_turns: int = 8
    timeout_seconds: int = 900
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class CodingAgentResult:
    provider: str
    status: AgentStatus
    summary: str
    simulated: bool = False
    exit_code: int | None = None
    duration_ms: int = 0
    stdout_tail: str = ""
    stderr_tail: str = ""
    error: str | None = None
    needs_human: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "provider": self.provider, "status": self.status, "summary": self.summary,
            "simulated": self.simulated, "exit_code": self.exit_code,
            "duration_ms": self.duration_ms, "error": self.error,
            "needs_human": self.needs_human, "metadata": self.metadata,
        }


def sanitized_env(extra: dict[str, str] | None = None) -> dict[str, str]:
    """Return a copy of the environment without app/Liara secrets."""
    env: dict[str, str] = {}
    for key, value in os.environ.items():
        upper = key.upper()
        if upper in ENV_DENY_EXACT:
            continue
        if any(upper.startswith(prefix) for prefix in ENV_DENY_PREFIXES):
            continue
        if ENV_DENY_PATTERN.search(upper):
            continue
        env[key] = value
    env.setdefault("CI", "1")
    env.setdefault("NO_COLOR", "1")
    env.setdefault("PYTHONDONTWRITEBYTECODE", "1")
    if extra:
        env.update(extra)
    return env


def _clip(text: str, limit: int = MAX_OUTPUT_CHARS) -> str:
    text = text or ""
    return text if len(text) <= limit else text[: limit - 200] + "\n…[truncated]"


async def run_command(
    cmd: list[str],
    *,
    cwd: Path,
    max_seconds: float,
    env: dict[str, str] | None = None,
    stdin_devnull: bool = True,
) -> CommandResult:
    """Run a fixed command (never through a shell) with a hard timeout."""
    started = time.perf_counter()
    process = None
    try:
        process = await asyncio.create_subprocess_exec(
            *cmd,
            cwd=str(cwd),
            stdin=asyncio.subprocess.DEVNULL if stdin_devnull else None,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=env or sanitized_env(),
            start_new_session=True,
        )
        stdout_b, stderr_b = await asyncio.wait_for(
            process.communicate(), timeout=max(1.0, float(max_seconds))
        )
        return CommandResult(
            returncode=process.returncode,
            stdout=_clip(stdout_b.decode("utf-8", errors="replace")),
            stderr=_clip(stderr_b.decode("utf-8", errors="replace")),
            duration_ms=int((time.perf_counter() - started) * 1000),
        )
    except TimeoutError:
        if process is not None and process.returncode is None:
            try:
                os.killpg(os.getpgid(process.pid), 9)
            except Exception:  # pragma: no cover - best effort
                process.kill()
            await process.wait()
        return CommandResult(
            returncode=None, stdout="", stderr="Process timed out and was killed.",
            duration_ms=int((time.perf_counter() - started) * 1000), timed_out=True,
        )
    except FileNotFoundError as exc:
        return CommandResult(
            returncode=127, stdout="", stderr=f"Command not found: {cmd[0]} ({exc})",
            duration_ms=int((time.perf_counter() - started) * 1000),
        )
    except Exception as exc:  # pragma: no cover - defensive
        logger.exception("command execution failed")
        return CommandResult(
            returncode=1, stdout="", stderr=f"Execution error: {type(exc).__name__}",
            duration_ms=int((time.perf_counter() - started) * 1000),
        )


async def probe_binary(name: str, *, version_timeout: float = 10.0,
                       cwd: Path | None = None) -> tuple[bool, str | None]:
    path = shutil.which(name)
    if not path:
        return False, None
    result = await run_command([path, "--version"], cwd=cwd or Path.cwd(), max_seconds=version_timeout)
    version = (result.stdout or result.stderr).strip().splitlines()
    return True, version[0][:120] if version else None


class BaseCodingAgent(ABC):
    name = "base"
    simulated = False
    command_name: str | None = None

    @abstractmethod
    async def availability(self) -> AgentAvailability: ...

    @abstractmethod
    async def run(self, task: CodingAgentTask) -> CodingAgentResult: ...

    def describe(self) -> dict[str, Any]:
        return {"provider": self.name, "simulated": self.simulated, "command": self.command_name}
