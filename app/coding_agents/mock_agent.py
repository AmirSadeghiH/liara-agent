"""Deterministic simulated coding agent used by Demo Mode.

It edits real files inside the isolated workspace (so the diff, tests and review
steps are genuine), but it makes **no** external calls.  Every result is marked
``simulated=True`` and the UI/report label it as simulated.
"""

from __future__ import annotations

import re
from pathlib import Path

from app.coding_agents.base import (
    AgentAvailability,
    BaseCodingAgent,
    CodingAgentResult,
    CodingAgentTask,
)

GUARDED_IMPORT = (
    "try:  # optional dependency: do not crash the whole application if it is missing\n"
    "    import django_filters  # noqa: F401\n"
    "except ModuleNotFoundError:  # pragma: no cover - defensive\n"
    "    django_filters = None\n"
)


class MockCodingAgent(BaseCodingAgent):
    name = "mock"
    simulated = True
    command_name = None

    async def availability(self) -> AgentAvailability:
        return AgentAvailability(
            provider="mock", installed=True, version="built-in", ready=True,
            reason="Simulated agent for Demo Mode (no external process is started).",
        )

    async def run(self, task: CodingAgentTask) -> CodingAgentResult:
        cause = str(task.metadata.get("cause_key", "unknown"))
        workflow_id = str(task.metadata.get("workflow_id", "demo"))
        changed: list[str] = []
        summary: str

        if cause == "missing_dependency":
            changed.extend(self._patch_missing_dependency(task.workspace))
            summary = (
                "وابستگی django-filter به requirements.txt اضافه شد و import آن در "
                "settings.py به‌صورت مقاوم (guarded) بازنویسی شد."
            )
        else:
            note = task.workspace / "docs" / f"ai-fix-{workflow_id}.md"
            note.parent.mkdir(parents=True, exist_ok=True)
            note.write_text(
                "# LiaraPilot repair note (simulated)\n\n"
                f"Cause: {cause}\n\n"
                "This demo run does not modify application code for this cause. "
                "In a real run the configured coding agent (Claude Code or Codex) "
                "would implement the change and the tests below would validate it.\n",
                encoding="utf-8",
            )
            changed.append(str(note.relative_to(task.workspace)))
            summary = "تغییر شبیه‌سازی‌شده ثبت شد؛ برای این علت، اصلاح کد در دمو انجام نشد."

        return CodingAgentResult(
            provider="mock",
            status="success",
            summary=summary,
            simulated=True,
            exit_code=0,
            duration_ms=180,
            stdout_tail="[mock] patch applied (no external process)",
            metadata={"files_changed": changed, "cause_key": cause},
        )

    # ------------------------------------------------------------------
    def _patch_missing_dependency(self, workspace: Path) -> list[str]:
        changed: list[str] = []

        requirements = workspace / "requirements.txt"
        if requirements.exists():
            content = requirements.read_text(encoding="utf-8")
        else:
            content = "# Python dependencies\n"
        if "django-filter" not in content and "django_filters" not in content:
            if content and not content.endswith("\n"):
                content += "\n"
            content = content.replace(
                "# Python dependencies\n",
                "# Python dependencies\n# Added by LiaraPilot repair (simulated)\n",
            )
            content += "django-filter==24.2\n"
            requirements.write_text(content, encoding="utf-8")
            changed.append("requirements.txt")

        settings = workspace / "store" / "settings.py"
        if settings.exists():
            text = settings.read_text(encoding="utf-8")
            if "import django_filters" in text and "try:  # optional dependency" not in text:
                patched, replacements = re.subn(
                    r"^import django_filters.*$", GUARDED_IMPORT.rstrip("\n"), text,
                    count=1, flags=re.MULTILINE,
                )
                if replacements:
                    settings.write_text(patched, encoding="utf-8")
                    changed.append("store/settings.py")

        return changed
