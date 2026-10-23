"""Manual handoff adapter used when no coding CLI is configured/installed.

It writes a complete, self-contained repair request into the workspace and stops
the workflow at ``needs_human`` instead of pretending that code was changed.
"""

from __future__ import annotations

from app.coding_agents.base import (
    AgentAvailability,
    BaseCodingAgent,
    CodingAgentResult,
    CodingAgentTask,
)

HANDOFF_FILE = "LIARAPILOT_FIX_REQUEST.md"


class ManualHandoffAdapter(BaseCodingAgent):
    name = "manual"
    simulated = False
    command_name = None

    async def availability(self) -> AgentAvailability:
        return AgentAvailability(
            provider="manual", installed=True, version="built-in", ready=True,
            reason="No coding CLI selected; repair requests are handed to a human.",
        )

    async def run(self, task: CodingAgentTask) -> CodingAgentResult:
        path = task.workspace / HANDOFF_FILE
        path.write_text(
            "# LiaraPilot — manual repair request\n\n"
            "No coding agent CLI (Claude Code / Codex) is configured, so this task was not "
            "executed automatically. Apply the change below, run the tests, then resume the "
            "workflow from LiaraPilot.\n\n"
            f"## Branch\n`{task.branch}`\n\n"
            "## Task\n" + task.prompt + "\n\n"
            "## Evidence\n" + task.evidence_summary + "\n\n"
            "## Safety rules\n"
            "- Never commit `.env`, credentials or `.git` internals.\n"
            "- Run the project's test suite before requesting deployment.\n"
            "- Deployment still requires an explicit approval in LiaraPilot.\n",
            encoding="utf-8",
        )
        return CodingAgentResult(
            provider="manual",
            status="needs_human",
            needs_human=True,
            summary=(
                "هیچ ایجنت کدنویسی واقعی فعال نیست. درخواست اصلاح در فایل "
                f"{HANDOFF_FILE} داخل Workspace نوشته شد و گردش‌کار برای اجرای دستی متوقف شد."
            ),
            metadata={"handoff_file": str(path)},
        )
