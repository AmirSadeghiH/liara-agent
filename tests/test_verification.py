"""Verification service tests — no false success claims."""

from __future__ import annotations

import httpx

from app.core.config import Settings
from app.services.audit_service import AuditService
from app.services.verification_service import VerificationService
from tests.conftest import make_settings


class StubAdapter:
    """A non-simulated adapter stub (as if it were a live Liara project)."""

    mode = "live"
    simulated = False

    def __init__(self) -> None:
        self.entries: list = []

    async def get_logs(self, project, since=None):
        return self.entries

    async def aclose(self) -> None:
        return None


async def build_service(tmp_path, adapter, settings_overrides=None, transport=None):
    settings = make_settings(tmp_path, demo_mode=False, **(settings_overrides or {}))
    from app.db.database import Database
    from app.db.repository import Repository

    db = Database(settings.database_url)
    await db.init()
    repo = Repository(db)
    audit = AuditService(repo, settings.audit_path)
    service = VerificationService(adapter, settings, audit, transport=transport)
    return service, db


async def test_missing_healthcheck_url_is_unverified(tmp_path):
    adapter = StubAdapter()
    service, db = await build_service(tmp_path, adapter)
    result = await service.verify(workflow_id="wf-1", project="demo", deployment={})
    await db.dispose()
    assert result["status"] == "unverified"
    assert result["ok"] is False
    assert "DEPLOY_HEALTHCHECK_URL" in result["reason"]


async def test_healthcheck_success_is_verified(tmp_path):
    adapter = StubAdapter()

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"status": "ok"})

    service, db = await build_service(
        tmp_path, adapter,
        {"deploy_healthcheck_url": "https://demo-app.example.com/healthz"},
        transport=httpx.MockTransport(handler),
    )
    result = await service.verify(workflow_id="wf-2", project="demo", deployment={})
    await db.dispose()
    assert result["status"] == "verified"
    assert result["observed_status"] == 200


async def test_healthcheck_failure_is_not_success(tmp_path):
    adapter = StubAdapter()

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500)

    service, db = await build_service(
        tmp_path, adapter,
        {"deploy_healthcheck_url": "https://demo-app.example.com/healthz",
         "deploy_healthcheck_retries": 2},
        transport=httpx.MockTransport(handler),
    )
    result = await service.verify(workflow_id="wf-3", project="demo", deployment={})
    await db.dispose()
    assert result["status"] == "failed"
    assert result["ok"] is False
    assert result["observed_status"] == 500


async def test_private_target_is_refused(tmp_path):
    adapter = StubAdapter()
    service, db = await build_service(
        tmp_path, adapter, {"deploy_healthcheck_url": "http://10.0.0.5/health"}
    )
    result = await service.verify(workflow_id="wf-4", project="demo", deployment={})
    await db.dispose()
    assert result["status"] == "unverified"
    assert result["observed_status"] is None


async def test_demo_verification_is_marked_simulated(tmp_path):
    from app.liara.mock_adapter import MockLiaraAdapter

    settings = make_settings(tmp_path, demo_mode=True)
    adapter = MockLiaraAdapter(settings)
    from app.db.database import Database
    from app.db.repository import Repository

    db = Database(settings.database_url)
    await db.init()
    audit = AuditService(Repository(db), settings.audit_path)
    service = VerificationService(adapter, settings, audit)
    result = await service.verify(workflow_id="wf-5", project="demo-django-store", deployment={})
    await db.dispose()
    assert result["simulated"] is True
    assert result["status"] in {"verified", "failed"}
    assert "شبیه" in result["note"]


def test_expected_status_is_configurable(tmp_path):
    settings: Settings = make_settings(
        tmp_path, deploy_healthcheck_expect_status=204
    )
    assert settings.deploy_healthcheck_expect_status == 204
