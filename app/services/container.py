"""Application service container.

A single place wires settings, persistence, the Liara adapter and every service.
The HTTP app, the MCP stdio server and the tests all construct this container, so
business logic is never duplicated per transport.
"""

from __future__ import annotations

import logging
from contextlib import AsyncExitStack
from typing import Any

from app.agent.checkpointer import open_checkpointer
from app.agent.graph import build_graph
from app.agent.llm import LLMAdvisor
from app.agent.nodes import WorkflowDeps
from app.core.config import Settings
from app.core.utils import iso
from app.db.database import Database
from app.db.repository import Repository
from app.liara.adapter import LiaraAdapter, LiveLiaraAdapter
from app.liara.mock_adapter import MockLiaraAdapter
from app.services.approval_service import ApprovalService
from app.services.audit_service import AuditService
from app.services.coding_agent_service import CodingAgentService
from app.services.demo_service import DemoService
from app.services.deployment_service import DeploymentService
from app.services.diagnosis_service import DiagnosisService
from app.services.verification_service import VerificationService
from app.services.workflow_service import WorkflowRunner

logger = logging.getLogger(__name__)


class AppContainer:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        settings.ensure_directories()

        self.db = Database(settings.database_url)
        self.repo = Repository(self.db)
        self.audit = AuditService(self.repo, settings.audit_path)

        self.adapter: LiaraAdapter = (
            MockLiaraAdapter(settings)
            if settings.demo_mode
            else LiveLiaraAdapter(settings, audit_hook=self.audit.liara_hook)
        )

        self.advisor = LLMAdvisor(settings)
        self.diagnosis = DiagnosisService(
            self.adapter, self.repo, settings, self.audit, advisor=self.advisor
        )
        self.approvals = ApprovalService(self.repo, settings, self.audit)
        self.coding = CodingAgentService(settings, self.repo, self.audit)
        self.deployment = DeploymentService(
            self.adapter, self.repo, settings, self.audit, self.approvals
        )
        self.verification = VerificationService(self.adapter, settings, self.audit)
        self.runner = WorkflowRunner(
            settings, self.repo, self.audit, self.approvals, self.adapter
        )
        self.demo = DemoService(settings, self.adapter, self.runner)

        self.graph: Any = None
        self.checkpointer: Any = None
        self._stack: AsyncExitStack | None = None

    # ------------------------------------------------------------------
    async def start(self) -> None:
        await self.db.init()
        stack = AsyncExitStack()
        self.checkpointer = await stack.enter_async_context(
            open_checkpointer(self.settings.checkpoint_file)
        )
        self._stack = stack
        deps = WorkflowDeps(
            settings=self.settings,
            repo=self.repo,
            adapter=self.adapter,
            diagnosis=self.diagnosis,
            approvals=self.approvals,
            coding=self.coding,
            deployment=self.deployment,
            verification=self.verification,
            audit=self.audit,
        )
        self.graph = build_graph(deps, self.checkpointer)
        self.runner.attach(self.graph)
        await self.audit.record(
            "app.started",
            detail={
                "mode": "demo" if self.settings.demo_mode else "live",
                "llm": self.settings.llm_provider,
                "coding_agent": self.settings.coding_agent_provider,
            },
        )

    async def stop(self) -> None:
        if self._stack is not None:
            await self._stack.aclose()
            self._stack = None
        try:
            await self.adapter.aclose()
        finally:
            await self.db.dispose()

    # ------------------------------------------------------------------
    async def health(self) -> dict[str, Any]:
        db_ok = await self.db.healthcheck()
        return {
            "status": "ok" if db_ok else "degraded",
            "database": "ok" if db_ok else "unavailable",
            "mode": "demo" if self.settings.demo_mode else "live",
            "simulated": self.adapter.simulated,
            "llm": self.settings.llm_provider,
            "coding_agent": self.settings.coding_agent_provider,
            "time": iso(),
        }

    async def readiness(self) -> dict[str, Any]:
        db_ok = await self.db.healthcheck()
        readiness = self.settings.live_readiness()
        agent = await self.coding.availability()
        checks = {
            "database": {"ok": db_ok, "path": self.settings.database_url.split("///")[-1]},
            "checkpoints": {
                "ok": self.settings.checkpoint_file.parent.exists(),
                "path": str(self.settings.checkpoint_file),
            },
            "data_dir_writable": {"ok": self.settings.data_path.exists(),
                                  "path": str(self.settings.data_path)},
            "liara_adapter": {
                "mode": self.adapter.mode,
                "simulated": self.adapter.simulated,
                "token_configured": self.settings.has_liara_token,
            },
            "coding_agent": agent,
        }
        ready = db_ok and all(
            checks[key]["ok"] for key in ("database", "checkpoints", "data_dir_writable")
        )
        if not self.settings.demo_mode:
            ready = ready and bool(readiness["live_ready"])
        return {
            "ready": ready,
            "mode": "demo" if self.settings.demo_mode else "live",
            "checks": checks,
            "live": readiness,
            "capabilities": {
                "demo_mode": self.settings.demo_mode,
                "writes_enabled": self.settings.liara_allow_writes,
                "deploy_enabled": self.settings.liara_enable_deploy,
                "git_push_enabled": self.settings.coding_agent_allow_git_push,
                "llm_enabled": self.settings.has_llm,
                "real_coding_agent": self.settings.coding_agent_provider != "none",
            },
        }
