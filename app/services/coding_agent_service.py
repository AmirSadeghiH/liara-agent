"""Repair loop: isolated workspace, coding agent, tests and diff review.

Security boundaries enforced here:

* workspaces live under ``CODING_AGENT_WORKSPACE_ROOT`` and are never symlinked
  outside it,
* ``.env`` / VCS internals / credentials are stripped before any agent runs,
* only fixed, allowlisted test commands are executed (never user input),
* the coding agent never receives the Liara token (see ``base.sanitized_env``),
* changes to sensitive files or an oversized diff block deployment,
* nothing is pushed to a Git remote: this service only creates a local branch.
"""

from __future__ import annotations

import asyncio
import difflib
import hashlib
import importlib.util
import logging
import os
import shutil
import stat
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from app.agent.prompts import build_repair_prompt
from app.coding_agents.base import (
    AgentAvailability,
    BaseCodingAgent,
    CodingAgentTask,
    run_command,
    sanitized_env,
)
from app.coding_agents.claude_code import ClaudeCodeAdapter
from app.coding_agents.codex import CodexAdapter
from app.coding_agents.manual import ManualHandoffAdapter
from app.coding_agents.mock_agent import MockCodingAgent
from app.core.config import Settings
from app.core.errors import NotFoundError, PolicyViolation, ValidationError
from app.core.security import assert_within
from app.core.utils import new_id
from app.db.repository import Repository
from app.services.audit_service import AuditService

logger = logging.getLogger(__name__)

MAX_DIFF_CHARS = 24_000
MAX_DIFF_FILES = 40
MAX_CHANGED_FILES = 25
TEST_TIMEOUT_SECONDS = 300
SENSITIVE_NAMES = {".env", ".netrc", ".npmrc", "id_rsa", "id_ed25519", ".pgpass"}
SENSITIVE_SUFFIXES = {".pem", ".key", ".p12", ".pfx"}


@dataclass
class WorkspaceInfo:
    path: Path
    branch: str
    git: dict[str, Any] = field(default_factory=dict)
    reused: bool = False

    def as_dict(self) -> dict[str, Any]:
        return {"path": str(self.path), "branch": self.branch, "git": self.git,
                "reused": self.reused}


def _remove_tree(path: Path) -> None:
    """Remove a workspace, including read-only files created by Git.

    Git object files are marked read-only on Windows, which makes a plain
    ``shutil.rmtree`` fail with ``WinError 5`` and leaves a half-deleted
    workspace behind.  The same helper is used for a fresh attempt and cleanup.
    """
    def _retry(func, target, exc):  # noqa: ANN001 - shutil callback signature
        try:
            os.chmod(target, stat.S_IWRITE)
            func(target)
        except OSError:
            if isinstance(exc, tuple):
                raise exc[1]
            raise

    if not path.exists():
        return
    if sys.version_info >= (3, 12):
        shutil.rmtree(path, onexc=_retry)
    else:  # pragma: no cover - Python < 3.12
        shutil.rmtree(path, onerror=_retry)


MAX_SNAPSHOT_BYTES = 512_000


@dataclass(frozen=True)
class FileSnapshot:
    """Content captured before the agent runs.

    A digest is kept for every file (binary and oversized files included) so
    change detection stays correct; text content is kept only when it can be
    diffed.  Reading the file again *after* the agent ran would compare the new
    content with itself and silently produce an empty diff.
    """

    digest: str
    content: str | None


def _read_snapshot(path: Path) -> FileSnapshot:
    raw = path.read_bytes()
    digest = hashlib.sha256(raw).hexdigest()
    if b"\x00" in raw[:8000] or len(raw) > MAX_SNAPSHOT_BYTES:
        return FileSnapshot(digest=digest, content=None)
    return FileSnapshot(digest=digest, content=raw.decode("utf-8", errors="replace"))


def snapshot_workspace(root: Path) -> dict[str, FileSnapshot]:
    result: dict[str, FileSnapshot] = {}
    for path in sorted(root.rglob("*")):
        if not path.is_file() or path.is_symlink():
            continue
        rel = path.relative_to(root).as_posix()
        if rel.startswith(".git/") or "/.git/" in rel or rel == ".git":
            continue
        try:
            result[rel] = _read_snapshot(path)
        except OSError:  # pragma: no cover
            continue
    return result


def compute_diff(
    before: dict[str, FileSnapshot], after: dict[str, FileSnapshot], root: Path
) -> dict[str, Any]:
    changed = sorted(
        path for path in set(before) | set(after)
        if (before.get(path) and before[path].digest) != (after.get(path) and after[path].digest)
    )
    added = [p for p in changed if p not in before]
    deleted = [p for p in changed if p not in after]
    modified = [p for p in changed if p in before and p in after]
    diff_lines: list[str] = []
    truncated = False
    for rel in changed[:MAX_DIFF_FILES]:
        old = before.get(rel)
        new = after.get(rel)
        if (old is not None and old.content is None) or (new is not None and new.content is None):
            diff_lines.append(f"--- {rel}\n+++ {rel}\n(binary or oversized file changed)\n")
            continue
        old_text = old.content if old is not None else ""
        new_text = new.content if new is not None else ""
        diff_lines.extend(
            difflib.unified_diff(
                old_text.splitlines(), new_text.splitlines(),
                fromfile=f"a/{rel}", tofile=f"b/{rel}", lineterm="", n=2,
            )
        )
        diff_lines.append("")
    text = "\n".join(diff_lines)
    if len(text) > MAX_DIFF_CHARS:
        text = text[:MAX_DIFF_CHARS] + "\n…[diff truncated]"
        truncated = True
    return {
        "files": changed,
        "added": added,
        "modified": modified,
        "deleted": deleted,
        "diff": text,
        "truncated": truncated or len(changed) > MAX_DIFF_FILES,
        "file_count": len(changed),
    }


def review_diff(changed_files: list[str]) -> dict[str, Any]:
    violations: list[str] = []
    warnings: list[str] = []
    for rel in changed_files:
        name = Path(rel).name
        if name in SENSITIVE_NAMES or name.startswith(".env"):
            violations.append(f"Sensitive file must not be modified: {rel}")
        if Path(rel).suffix.lower() in SENSITIVE_SUFFIXES:
            violations.append(f"Credential-like file must not be modified: {rel}")
        if rel.startswith(".git/") or "/.git/" in rel:
            violations.append(f"Git internals must not be modified: {rel}")
        if rel.startswith("/") or ".." in Path(rel).parts:
            violations.append(f"Path outside workspace: {rel}")
    if len(changed_files) > MAX_CHANGED_FILES:
        violations.append(
            f"Too many changed files ({len(changed_files)} > {MAX_CHANGED_FILES}); "
            "the change looks unrelated to the incident."
        )
    if any(rel.startswith("tests/") for rel in changed_files):
        warnings.append("Test files were modified; review them before deployment.")
    return {"ok": not violations, "violations": violations, "warnings": warnings}


class WorkspaceManager:
    """Creates isolated workspaces and local AI-fix branches."""

    def __init__(self, settings: Settings, audit: AuditService) -> None:
        self.settings = settings
        self.audit = audit

    def _workspace_path(self, workflow_id: str) -> Path:
        root = self.settings.workspace_root
        root.mkdir(parents=True, exist_ok=True)
        if not workflow_id.replace("-", "").isalnum():
            raise ValidationError("Invalid workflow id for workspace path.")
        path = assert_within(root, root / workflow_id)
        return path

    async def create(
        self, *, workflow_id: str, project: str, preserve: bool = False
    ) -> WorkspaceInfo:
        destination = self._workspace_path(workflow_id)
        reused = bool(preserve and destination.is_dir())
        if reused:
            # Retry inside the same approved repair plan: keep the previous
            # attempt's changes so the agent can fix the failing test instead of
            # silently starting over from the fixture.
            origin = "preserved_workspace"
        else:
            _remove_tree(destination)
            destination.mkdir(parents=True)

            if self.settings.demo_mode:
                source = self.settings.demo_fixture_root / "django_store"
                if not source.is_dir():
                    raise NotFoundError("Demo fixture repository is missing from the installation.")
                shutil.copytree(source, destination, dirs_exist_ok=True)
                origin = "demo_fixture"
            else:
                repo_path = (self.settings.coding_agent_repo_path or "").strip()
                if not repo_path:
                    raise PolicyViolation(
                        "CODING_AGENT_REPO_PATH is not configured. Live repair needs a local clone "
                        "of the application repository; no repository is guessed.",
                        details={"reason": "repo_not_configured"},
                    )
                repo = await asyncio.to_thread(lambda: Path(repo_path).expanduser().resolve())
                if not repo.is_dir():
                    raise PolicyViolation(
                        "CODING_AGENT_REPO_PATH does not exist.", details={"path": str(repo)}
                    )
                shutil.copytree(repo, destination, dirs_exist_ok=True)
                origin = "local_repo"

        # Never let a .env file enter the workspace.
        for env_file in list(destination.glob(".env*")):
            if env_file.is_file() and env_file.name != ".env.example":
                env_file.unlink(missing_ok=True)

        branch = f"ai-fix/{workflow_id}"
        git = await self._prepare_git(destination, branch)
        await self.audit.record(
            "workspace.created" if not reused else "workspace.reused",
            target=workflow_id,
            detail={"project": project, "branch": branch, "origin": origin,
                    "git": git.get("initialised"), "simulated": self.settings.demo_mode,
                    "reused": reused},
            trace_id=workflow_id,
        )
        return WorkspaceInfo(path=destination, branch=branch, git=git, reused=reused)

    async def _prepare_git(self, workspace: Path, branch: str) -> dict[str, Any]:
        """Initialise an isolated repository inside the workspace.

        The workspace lives inside the application's own checkout (``data/workspaces``),
        so a plain ``git rev-parse`` would resolve to the *host* repository. Branching
        there would silently switch the developer's checkout to ``ai-fix/...``. We
        therefore require the workspace to be its own repository root before running
        any branch operation.
        """
        git = shutil.which("git")
        if not git:
            return {"available": False, "reason": "git not installed", "initialised": False}

        target = os.path.normcase(str(await asyncio.to_thread(workspace.resolve)))

        async def toplevel() -> str | None:
            result = await run_command(
                [git, "rev-parse", "--show-toplevel"], cwd=workspace, max_seconds=15
            )
            if not result.ok or not result.stdout.strip():
                return None
            try:
                resolved = await asyncio.to_thread(Path(result.stdout.strip()).resolve)
            except OSError:  # pragma: no cover - defensive
                return None
            return os.path.normcase(str(resolved))

        initialised = False
        if await toplevel() != target:
            init = await run_command([git, "init", "-q"], cwd=workspace, max_seconds=30)
            if not init.ok:
                return {"available": True, "initialised": False, "reason": init.stderr[-300:]}
            initialised = True
        if await toplevel() != target:
            return {
                "available": True,
                "initialised": initialised,
                "reason": "workspace is not an isolated git repository; branch operations were skipped.",
            }
        checkout = await run_command([git, "checkout", "-B", branch], cwd=workspace, max_seconds=30)
        if not checkout.ok:
            return {"available": True, "initialised": initialised, "reason": checkout.stderr[-300:]}
        if initialised:
            await run_command([git, "add", "-A"], cwd=workspace, max_seconds=30)
            await run_command(
                [git, "-c", "user.name=LiaraPilot", "-c", "user.email=pilot@liarapilot.local",
                 "commit", "-q", "-m", "baseline before LiaraPilot repair"],
                cwd=workspace, max_seconds=30,
            )
        return {
            "available": True,
            "initialised": initialised,
            "branch": branch,
            "push": "disabled",
            "message": "Local branch only. LiaraPilot never pushes to a remote by default.",
        }

    def cleanup(self, workflow_id: str) -> None:
        path = self._workspace_path(workflow_id)
        try:
            _remove_tree(path)
        except OSError:
            logger.warning("workspace cleanup failed", extra={"event_data": {"path": str(path)}})


class TestRunner:
    """Runs only fixed, allowlisted commands (no shell, no user input)."""

    def detect(self, workspace: Path) -> tuple[list[str] | None, str]:
        has_python_tests = (workspace / "tests").is_dir() or any(workspace.glob("test_*.py"))
        if has_python_tests and importlib.util.find_spec("pytest") is not None:
            return [
                sys.executable, "-m", "pytest", "-q", "--maxfail=1", "-p", "no:cacheprovider",
            ], "pytest"
        package_json = workspace / "package.json"
        if package_json.exists() and shutil.which("npm"):
            try:
                import json

                scripts = json.loads(package_json.read_text(encoding="utf-8")).get("scripts", {})
            except Exception:
                scripts = {}
            if isinstance(scripts, dict) and scripts.get("test"):
                return ["npm", "test", "--silent"], "npm test"
        return [sys.executable, "-m", "compileall", "-q", str(workspace)], "python -m compileall"

    async def run(self, workspace: Path, *, max_seconds: int = TEST_TIMEOUT_SECONDS,
                  simulated: bool = False) -> dict[str, Any]:
        command, runner = self.detect(workspace)
        if not command:
            return {"status": "skipped", "runner": runner, "reason": "no test runner detected"}
        started = time.perf_counter()
        result = await run_command(
            command, cwd=workspace, max_seconds=max_seconds,
            env=sanitized_env({"PYTHONPATH": str(workspace)}),
        )
        passed = result.ok
        output = (result.stdout + ("\n" + result.stderr if result.stderr else "")).strip()
        await asyncio.sleep(0)
        return {
            "status": "passed" if passed else "failed",
            "runner": runner,
            "command": " ".join(command),
            "exit_code": result.returncode,
            "duration_ms": int((time.perf_counter() - started) * 1000),
            "output_tail": output[-6000:],
            "timed_out": result.timed_out,
            "simulated_patch": simulated,
            "executed_locally": True,
        }


class CodingAgentService:
    """Step-wise repair pipeline used by the graph and by MCP tools."""

    def __init__(
        self,
        settings: Settings,
        repo: Repository,
        audit: AuditService,
        *,
        workspace_manager: WorkspaceManager | None = None,
        test_runner: TestRunner | None = None,
    ) -> None:
        self.settings = settings
        self.repo = repo
        self.audit = audit
        self.workspaces = workspace_manager or WorkspaceManager(settings, audit)
        self.tests = test_runner or TestRunner()
        self.agents: dict[str, BaseCodingAgent] = {
            "mock": MockCodingAgent(),
            "claude_code": ClaudeCodeAdapter(),
            "codex": CodexAdapter(),
            "manual": ManualHandoffAdapter(),
        }

    # ------------------------------------------------------------------
    # capabilities
    # ------------------------------------------------------------------
    async def availability(self, provider: str | None = None) -> dict[str, Any]:
        name = provider or self.settings.coding_agent_provider
        if self.settings.demo_mode and name in {"none", "mock"}:
            agent = self.agents["mock"]
        else:
            agent = self.agents.get(name, self.agents["manual"])
        info: AgentAvailability = await agent.availability()
        return {
            **info.as_dict(),
            "configured_provider": self.settings.coding_agent_provider,
            "auto_execute": self.settings.coding_agent_auto_execute,
            "effective_in_demo": self.settings.demo_mode,
        }

    async def status_report(self) -> dict[str, Any]:
        return {
            "configured_provider": self.settings.coding_agent_provider,
            "auto_execute": self.settings.coding_agent_auto_execute,
            "git_push_allowed": self.settings.coding_agent_allow_git_push,
            "providers": [await self.availability(p) for p in ("claude_code", "codex")],
        }

    def select_agent(self) -> BaseCodingAgent:
        if self.settings.demo_mode:
            return self.agents["mock"]
        provider = self.settings.coding_agent_provider
        if provider == "none":
            return self.agents["manual"]
        agent = self.agents.get(provider, self.agents["manual"])
        if not agent.simulated and not self.settings.coding_agent_auto_execute:
            return self.agents["manual"]
        return agent

    # ------------------------------------------------------------------
    # step 1: isolated workspace + branch
    # ------------------------------------------------------------------
    async def prepare_workspace(
        self, *, workflow_id: str, project: str, attempt: int = 0
    ) -> dict[str, Any]:
        run_id = new_id("car")
        await self.repo.create_agent_run({
            "id": run_id,
            "workflow_id": workflow_id,
            "provider": "pending",
            "status": "preparing",
            "simulated": self.settings.demo_mode,
        })
        started = time.perf_counter()
        try:
            workspace = await self.workspaces.create(
                workflow_id=workflow_id, project=project, preserve=attempt > 0
            )
        except (PolicyViolation, NotFoundError, ValidationError) as exc:
            message = getattr(exc, "message", str(exc))
            await self.repo.update_agent_run(
                run_id, status="needs_human", error=message,
                duration_ms=int((time.perf_counter() - started) * 1000),
            )
            await self.audit.record(
                "coding_agent.blocked", target=workflow_id, outcome="needs_human",
                detail={"reason": message}, trace_id=workflow_id,
            )
            return {
                "run_id": run_id, "status": "needs_human", "needs_human": True,
                "summary": message, "workspace": None, "branch": None, "git": {},
                "simulated": self.settings.demo_mode,
            }
        command, runner = self.tests.detect(workspace.path)
        await self.repo.update_agent_run(
            run_id, status="prepared", workspace=str(workspace.path), branch=workspace.branch,
            duration_ms=int((time.perf_counter() - started) * 1000),
        )
        return {
            "run_id": run_id,
            "status": "success",
            "needs_human": False,
            "workspace": str(workspace.path),
            "branch": workspace.branch,
            "git": workspace.git,
            "test_command": " ".join(command) if command else None,
            "test_runner": runner,
            "simulated": self.settings.demo_mode,
            "workspace_reused": workspace.reused,
            "summary": (
                f"Workspace قبلی حفظ شد (تلاش {attempt}) و شاخه {workspace.branch} دوباره بررسی شد."
                if workspace.reused else
                f"Workspace ایزوله ساخته شد و شاخه {workspace.branch} ایجاد شد."
            ),
        }

    # ------------------------------------------------------------------
    # step 2: run the selected coding agent
    # ------------------------------------------------------------------
    async def execute_agent(
        self,
        *,
        run_id: str,
        workflow_id: str,
        project: str,
        workspace: str,
        branch: str,
        diagnosis: dict[str, Any],
        repair_plan: dict[str, Any],
        evidence_summary: dict[str, Any],
        attempt: int = 0,
        previous_failure: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        agent = self.select_agent()
        root = Path(workspace)
        command, runner = self.tests.detect(root)
        prompt = build_repair_prompt(
            project=project,
            workflow_id=workflow_id,
            diagnosis=diagnosis,
            evidence_summary=evidence_summary,
            branch=branch,
            test_command=(" ".join(command) if command else runner),
            max_attempts=self.settings.coding_agent_max_repair_attempts,
            attempt=attempt,
            previous_failure=previous_failure,
        )
        before = snapshot_workspace(root)
        started = time.perf_counter()
        task = CodingAgentTask(
            workspace=root,
            branch=branch,
            prompt=prompt,
            evidence_summary=str(evidence_summary.get("error_samples", ""))[:4000],
            max_turns=self.settings.coding_agent_max_turns,
            timeout_seconds=self.settings.coding_agent_timeout_seconds,
            metadata={
                "workflow_id": workflow_id,
                "project": project,
                "cause_key": repair_plan.get("cause_key")
                or diagnosis.get("repair_hint", {}).get("cause_key"),
            },
        )
        try:
            result = await agent.run(task)
        except Exception as exc:  # pragma: no cover - adapter bugs must not crash the graph
            logger.exception("coding agent crashed")
            result = None
            error = f"{type(exc).__name__}: {exc}"
        else:
            error = result.error

        after = snapshot_workspace(root)
        diff = compute_diff(before, after, root)
        duration_ms = int((time.perf_counter() - started) * 1000)

        if result is None:
            status, needs_human, summary, provider = "failed", True, "ایجنت کدنویسی با خطا متوقف شد.", agent.name
            exit_code = None
        else:
            status, needs_human, summary = result.status, result.needs_human, result.summary
            provider, exit_code = result.provider, result.exit_code
            if result.status == "success" and not diff["files"]:
                status = "needs_human"
                needs_human = True
                summary = "ایجنت هیچ تغییری در Workspace ایجاد نکرد؛ انتشار کد بدون تغییر مجاز نیست."

        await self.repo.update_agent_run(
            run_id,
            provider=provider,
            status=status,
            exit_code=exit_code,
            duration_ms=duration_ms,
            files_changed=diff["files"],
            diff=diff["diff"][:MAX_DIFF_CHARS],
            error=error,
            workspace=workspace,
            branch=branch,
            simulated=agent.simulated,
            # The legacy column name is kept, but it stores the short activity
            # summary now; the diagnosis already has its own card.
            prompt_summary=(summary or diagnosis.get("probable_cause") or "")[:500],
        )
        await self.audit.record(
            "coding_agent.completed",
            target=workflow_id,
            outcome=status,
            detail={
                "provider": provider, "simulated": agent.simulated,
                "files_changed": diff["files"], "branch": branch, "attempt": attempt,
            },
            trace_id=workflow_id,
        )
        return {
            "run_id": run_id,
            "provider": provider,
            "status": status,
            "needs_human": needs_human,
            "simulated": agent.simulated,
            "summary": summary,
            "workspace": workspace,
            "branch": branch,
            "files_changed": diff["files"],
            "diff": diff["diff"],
            "diff_truncated": diff["truncated"],
            "test_runner": runner,
            "exit_code": exit_code,
            "duration_ms": duration_ms,
            "stdout_tail": (result.stdout_tail[-2000:] if result else ""),
            "stderr_tail": (result.stderr_tail[-2000:] if result else ""),
            "error": error,
            "label": "SIMULATED PATCH" if agent.simulated else "REAL EXECUTION",
        }

    # ------------------------------------------------------------------
    # step 3: tests
    # ------------------------------------------------------------------
    async def run_tests_for(
        self, *, workflow_id: str, run_id: str | None, workspace: str, simulated: bool
    ) -> dict[str, Any]:
        result = await self.tests.run(
            Path(workspace), max_seconds=TEST_TIMEOUT_SECONDS, simulated=simulated
        )
        if run_id:
            await self.repo.update_agent_run(run_id, test_results=result)
        await self.audit.record(
            "tests.executed",
            target=workflow_id,
            outcome=result["status"],
            detail={"runner": result.get("runner"), "exit_code": result.get("exit_code"),
                    "simulated_patch": simulated},
            trace_id=workflow_id,
        )
        return result

    # ------------------------------------------------------------------
    # step 4: review
    # ------------------------------------------------------------------
    def review_changes(self, files: list[str]) -> dict[str, Any]:
        return review_diff(files)

    # ------------------------------------------------------------------
    # convenience orchestration (used by MCP "prepare repair")
    # ------------------------------------------------------------------
    async def run_repair(
        self,
        *,
        workflow_id: str,
        project: str,
        diagnosis: dict[str, Any],
        repair_plan: dict[str, Any],
        evidence_summary: dict[str, Any],
        attempt: int = 0,
        previous_failure: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        prepared = await self.prepare_workspace(
            workflow_id=workflow_id, project=project, attempt=attempt
        )
        if prepared.get("needs_human"):
            return {**prepared, "tests": None, "diff": "", "files_changed": []}
        executed = await self.execute_agent(
            run_id=prepared["run_id"], workflow_id=workflow_id, project=project,
            workspace=prepared["workspace"], branch=prepared["branch"],
            diagnosis=diagnosis, repair_plan=repair_plan,
            evidence_summary=evidence_summary, attempt=attempt,
            previous_failure=previous_failure,
        )
        tests = None
        review = {"ok": True, "violations": [], "warnings": []}
        if executed["status"] == "success" and executed["files_changed"]:
            review = self.review_changes(executed["files_changed"])
            if review["ok"]:
                tests = await self.run_tests_for(
                    workflow_id=workflow_id, run_id=executed["run_id"],
                    workspace=executed["workspace"], simulated=executed["simulated"],
                )
                if tests["status"] != "passed":
                    executed["status"] = "failed"
                    executed["needs_human"] = True
            else:
                executed["status"] = "failed"
                executed["needs_human"] = True
        return {**executed, "tests": tests, "review": review}
