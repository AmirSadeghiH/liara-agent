"""Two-stage deployment: source preparation/upload, then approved release.

Stage 1 (``prepare``) packages the exact tested workspace and uploads it to
Liara, producing a ``sourceID``.  Stage 2 (``deploy``) requires a *consumed*
approval bound to the exact deployment parameters and creates the release.

The two stages are separate API operations by design.  Nothing is reported as
deployed until Liara returns a ``releaseID``; nothing is reported as verified
until :class:`VerificationService` says so.
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Any

from app.core.config import Settings
from app.core.errors import ConflictError, PolicyViolation, ValidationError
from app.core.security import (
    ensure_deploy_allowed,
    ensure_deploys_enabled,
    ensure_writes_enabled,
    validate_project_name,
)
from app.core.utils import iso, new_id
from app.db.repository import Repository
from app.liara.adapter import LiaraAdapter
from app.liara.source_packager import assert_archive_has_no_secrets, create_source_archive
from app.services.approval_service import ApprovalService
from app.services.audit_service import AuditService

logger = logging.getLogger(__name__)

RELEASE_POLL_TRIES = 6
RELEASE_POLL_INTERVAL_SECONDS = 5.0


class DeploymentService:
    def __init__(
        self,
        adapter: LiaraAdapter,
        repo: Repository,
        settings: Settings,
        audit: AuditService,
        approvals: ApprovalService,
        *,
        sleep=asyncio.sleep,
    ) -> None:
        self.adapter = adapter
        self.repo = repo
        self.settings = settings
        self.audit = audit
        self.approvals = approvals
        self._sleep = sleep

    # ------------------------------------------------------------------
    # stage 1: prepare + upload source
    # ------------------------------------------------------------------
    async def prepare(
        self,
        *,
        workflow_id: str,
        project: str,
        workspace: Path,
        attempt: int = 0,
    ) -> dict[str, Any]:
        project = validate_project_name(project)
        if not self.adapter.simulated:
            ensure_writes_enabled(self.settings, operation="source_upload")
            ensure_deploy_allowed(self.settings, project)

        workspace = Path(workspace)
        if not workspace.is_dir():
            raise ValidationError("Repair workspace is missing; cannot package the source.")

        artifact_dir = self.settings.data_path / "artifacts" / workflow_id
        archive_path = artifact_dir / f"source-{attempt}.tar.gz"
        package = create_source_archive(
            workspace, archive_path, max_mb=self.settings.liara_source_upload_max_mb
        )
        assert_archive_has_no_secrets(archive_path)

        archive_bytes = archive_path.read_bytes()
        source_id = await self.adapter.upload_source(
            project, archive=archive_bytes, filename=archive_path.name
        )

        project_type, port, port_source = await self._resolve_release_shape(project)
        params = {
            "project": project,
            "source_id": source_id,
            "port": port,
            "project_type": project_type,
            "package_sha256": package.sha256,
        }

        deployment_id = f"dep-{workflow_id}-{attempt}"
        existing = await self.repo.get_deployment(deployment_id)
        payload = {
            "stage": "source_uploaded",
            "status": "prepared",
            "source_id": source_id,
            "port": port,
            "project_type": project_type,
            "simulated": self.adapter.simulated,
            "params": params,
            "package": package.as_dict(),
            "detail": "Source uploaded; release not created yet.",
        }
        if existing is None:
            await self.repo.create_deployment({
                "id": deployment_id, "workflow_id": workflow_id, "project": project, **payload,
            })
        else:
            await self.repo.update_deployment(deployment_id, **payload)

        await self.audit.record(
            "deployment.source_uploaded",
            target=workflow_id,
            detail={
                "project": project, "source_id": source_id, "simulated": self.adapter.simulated,
                "package": package.as_dict(), "port": port, "port_source": port_source,
            },
            trace_id=workflow_id,
        )

        return {
            "deployment_id": deployment_id,
            "project": project,
            "source_id": source_id,
            "port": port,
            "port_source": port_source,
            "project_type": project_type,
            "package": package.as_dict(),
            "params": params,
            "simulated": self.adapter.simulated,
            "stage": "source_uploaded",
        }

    async def _resolve_release_shape(self, project: str) -> tuple[str, int, str]:
        project_type = ""
        try:
            details = await self.adapter.get_project(project)
            project_type = (details.type or "").strip()
        except Exception:
            logger.warning("could not read project type", exc_info=True)

        port: int | None = None
        try:
            page = await self.adapter.get_releases(project, count=5)
            for release in page.releases:
                if release.port:
                    port = int(release.port)
                    break
        except Exception:
            logger.warning("could not read previous release port", exc_info=True)

        port_source = "previous_release"
        if port is None:
            port = self.settings.liara_default_port
            port_source = "LIARA_DEFAULT_PORT"
        if not project_type:
            raise ValidationError(
                "Project platform type (type) could not be determined from the Liara API. "
                "The release payload requires an explicit type; refusing to guess.",
                details={"field": "type"},
            )
        return project_type, port, port_source

    # ------------------------------------------------------------------
    # stage 2: create release (approval required)
    # ------------------------------------------------------------------
    async def deploy(
        self,
        *,
        workflow_id: str,
        approval_id: str | None,
        project: str,
        source_id: str,
        port: int,
        project_type: str,
        attempt: int = 0,
    ) -> dict[str, Any]:
        project = validate_project_name(project)
        if not self.adapter.simulated:
            ensure_deploys_enabled(self.settings, operation="release_create")
            ensure_deploy_allowed(self.settings, project)

        params = {
            "project": project,
            "source_id": source_id,
            "port": int(port),
            "project_type": project_type,
        }
        existing = await self.repo.get_deployment(f"dep-{workflow_id}-{attempt}")

        # Idempotency: a repeated resume must never create a second release.
        if existing is not None and existing.release_id:
            return {
                "deployment_id": existing.id,
                "release_id": existing.release_id,
                "project": project,
                "source_id": source_id,
                "simulated": existing.simulated,
                "stage": "deployed",
                "idempotent_replay": True,
                "release_state": (existing.params or {}).get("release_state"),
            }

        approval = await self.approvals.validate_and_consume(
            approval_id, workflow_id=workflow_id, params=params, required_stage="deploy"
        )

        if self.adapter.simulated:
            release_id = await self.adapter.create_release(
                project, source_id=source_id, port=int(port), project_type=project_type
            )
            release_state = "ready"
            detail = "Simulated release created in Demo Mode (no request sent to Liara)."
        else:
            release_id = await self.adapter.create_release(
                project, source_id=source_id, port=int(port), project_type=project_type
            )
            release_state = await self._wait_for_release(project, release_id)
            detail = f"Release submitted to Liara (state={release_state})."

        if existing is None:
            await self.repo.create_deployment({
                "id": f"dep-{workflow_id}-{attempt}",
                "workflow_id": workflow_id,
                "project": project,
                "stage": "deployed",
                "status": "submitted",
                "source_id": source_id,
                "release_id": release_id,
                "port": int(port),
                "project_type": project_type,
                "simulated": self.adapter.simulated,
                "approval_id": approval.id,
                "params": {**params, "release_state": release_state},
                "detail": detail,
            })
        else:
            await self.repo.update_deployment(
                existing.id,
                stage="deployed",
                status="submitted",
                release_id=release_id,
                approval_id=approval.id,
                params={**params, "release_state": release_state},
                detail=detail,
            )

        await self.audit.record(
            "deployment.release_created",
            target=workflow_id,
            detail={
                "project": project, "release_id": release_id, "source_id": source_id,
                "simulated": self.adapter.simulated, "approval_id": approval.id,
                "release_state": release_state,
            },
            trace_id=workflow_id,
        )
        return {
            "deployment_id": f"dep-{workflow_id}-{attempt}",
            "release_id": release_id,
            "release_state": release_state,
            "project": project,
            "source_id": source_id,
            "port": int(port),
            "simulated": self.adapter.simulated,
            "stage": "deployed",
            "idempotent_replay": False,
            "created_at": iso(),
        }

    async def _wait_for_release(self, project: str, release_id: str) -> str:
        """Poll the documented releases endpoint; 'unknown' if not observable."""
        for attempt in range(RELEASE_POLL_TRIES):
            try:
                page = await self.adapter.get_releases(project, count=20)
                for release in page.releases:
                    if release.id == release_id:
                        if release.is_ready or (release.state or "").lower() in {"failed", "error"}:
                            return release.state or "unknown"
            except Exception:
                logger.warning("release status poll failed", exc_info=True)
            if attempt < RELEASE_POLL_TRIES - 1:
                await self._sleep(RELEASE_POLL_INTERVAL_SECONDS)
        return "unknown"

    # ------------------------------------------------------------------
    # convenience
    # ------------------------------------------------------------------
    @staticmethod
    def new_deployment_id() -> str:
        return new_id("dep")

    async def latest_for_workflow(self, workflow_id: str) -> Any:
        rows = await self.repo.list_deployments(workflow_id=workflow_id, limit=1)
        return rows[0] if rows else None

    def guard_cancel_conflict(self, status: str) -> None:
        if status in {"deploying", "verifying"}:
            raise ConflictError(
                "The deployment is already in progress and cannot be cancelled; "
                "the HTTP request to Liara cannot be recalled.",
                details={"status": status},
            )

    def assert_not_demo_write(self) -> None:
        if not self.settings.demo_mode and self.adapter.simulated:  # pragma: no cover
            raise PolicyViolation("Simulated adapter active while DEMO_MODE=false.")
