"""Security boundary tests: policy, approvals, workspace and packaging."""

from __future__ import annotations

import tarfile
from datetime import timedelta
from pathlib import Path

import pytest

from app.core.errors import (
    ConflictError,
    NotFoundError,
    PolicyViolation,
)
from app.core.errors import (
    ValidationError as AppValidationError,
)
from app.core.security import (
    assert_within,
    ensure_deploy_allowed,
    ensure_deploys_enabled,
    ensure_git_push_allowed,
    ensure_writes_enabled,
    safe_join,
    validate_healthcheck_url,
    validate_project_name,
)
from app.core.utils import fingerprint, iso, utcnow
from app.db.database import Database
from app.db.repository import Repository
from app.liara.source_packager import (
    assert_archive_has_no_secrets,
    create_source_archive,
    is_excluded,
)
from app.services.approval_service import ApprovalService
from app.services.audit_service import AuditService
from tests.conftest import make_settings


# ---------------------------------------------------------------------------
# policy guards
# ---------------------------------------------------------------------------
def test_empty_allowlist_blocks_all_writes(tmp_path):
    settings = make_settings(tmp_path, demo_mode=False)
    with pytest.raises(PolicyViolation) as excinfo:
        ensure_deploy_allowed(settings, "demo-django-store")
    assert excinfo.value.details["reason"] == "empty_allowlist"


def test_project_outside_allowlist_is_blocked(tmp_path):
    settings = make_settings(
        tmp_path, demo_mode=False, liara_deploy_allowed_projects="allowed-one"
    )
    ensure_deploy_allowed(settings, "allowed-one")
    with pytest.raises(PolicyViolation):
        ensure_deploy_allowed(settings, "some-other-project")


def test_writes_and_deploy_flags_are_separate(tmp_path):
    settings = make_settings(
        tmp_path, demo_mode=False, liara_allow_writes=True, liara_enable_deploy=False
    )
    ensure_writes_enabled(settings, operation="upload")  # allowed
    with pytest.raises(PolicyViolation):
        ensure_deploys_enabled(settings, operation="release")


def test_demo_mode_skips_write_flags_but_never_network(tmp_path):
    settings = make_settings(tmp_path, demo_mode=True, liara_allow_writes=False)
    ensure_writes_enabled(settings, operation="upload")
    ensure_deploys_enabled(settings)


def test_git_push_is_disabled_by_default(tmp_path):
    settings = make_settings(tmp_path)
    with pytest.raises(PolicyViolation):
        ensure_git_push_allowed(settings)


@pytest.mark.parametrize(
    "name",
    ["../etc/passwd", "bad/name", "bad name", "", "x" * 70, "name\\slash", "$(whoami)"],
)
def test_invalid_project_names_rejected(name):
    with pytest.raises(AppValidationError):
        validate_project_name(name)


def test_workspace_escape_is_blocked(tmp_path):
    root = tmp_path / "root"
    root.mkdir()
    with pytest.raises(PolicyViolation):
        assert_within(root, tmp_path / "outside")
    with pytest.raises(PolicyViolation):
        safe_join(root, "..", "outside")


def test_symlink_escape_is_blocked(tmp_path):
    root = tmp_path / "root"
    root.mkdir()
    outside = tmp_path / "outside.txt"
    outside.write_text("secret")
    link = root / "link"
    try:
        link.symlink_to(outside)
    except (OSError, NotImplementedError):  # pragma: no cover - Windows without privileges
        pytest.skip("symlinks unavailable")
    with pytest.raises(PolicyViolation):
        assert_within(root, link)


def test_healthcheck_url_rejects_loopback():
    with pytest.raises(PolicyViolation):
        validate_healthcheck_url("http://127.0.0.1:8000/health")
    with pytest.raises(AppValidationError):
        validate_healthcheck_url("file:///etc/passwd")


# ---------------------------------------------------------------------------
# source packaging
# ---------------------------------------------------------------------------
def build_workspace(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    (root / "app").mkdir(parents=True)
    (root / ".git").mkdir()
    (root / "node_modules" / "pkg").mkdir(parents=True)
    (root / "app" / "main.py").write_text("print('ok')\n")
    (root / ".env").write_text("LIARA_API_TOKEN=super-secret\n")
    (root / ".env.local").write_text("X=1\n")
    (root / ".git" / "config").write_text("[remote]\n")
    (root / "node_modules" / "pkg" / "index.js").write_text("x")
    (root / "server.pem").write_text("KEY")
    (root / "__pycache__").mkdir()
    (root / "__pycache__" / "a.pyc").write_text("x")
    return root


def test_packager_excludes_secrets_and_vendor_dirs(tmp_path):
    root = build_workspace(tmp_path)
    result = create_source_archive(root, tmp_path / "out.tar.gz", max_mb=5)
    members = set()
    with tarfile.open(result.path, "r:gz") as tar:
        members = {m.name for m in tar.getmembers()}
    assert "app/main.py" in members
    assert not any(name.startswith(".git") for name in members)
    assert not any(name.startswith("node_modules") for name in members)
    assert not any(name.startswith("__pycache__") for name in members)
    assert ".env" not in members
    assert ".env.local" not in members
    assert "server.pem" not in members
    assert result.file_count == 1
    assert result.sha256
    assert_archive_has_no_secrets(result.path)


def test_packager_enforces_size_limit(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    (root / "big.bin").write_bytes(b"0" * (2 * 1024 * 1024))
    with pytest.raises(PolicyViolation):
        create_source_archive(root, tmp_path / "out.tar.gz", max_mb=1)


def test_exclusion_rules():
    assert is_excluded(".env")
    assert is_excluded(".env.production")
    assert is_excluded("sub/dir/node_modules/x.js")
    assert is_excluded(".git/config")
    assert not is_excluded("app/main.py")
    assert not is_excluded("requirements.txt")


def test_archive_with_secret_is_rejected(tmp_path):
    fake = tmp_path / "bad.tar.gz"
    with tarfile.open(fake, "w:gz") as tar:
        data = b"TOKEN=x"
        info = tarfile.TarInfo(".env")
        info.size = len(data)
        import io

        tar.addfile(info, io.BytesIO(data))
    with pytest.raises(PolicyViolation):
        assert_archive_has_no_secrets(fake)


# ---------------------------------------------------------------------------
# approvals
# ---------------------------------------------------------------------------
async def build_approval_service(tmp_path):
    settings = make_settings(tmp_path)
    db = Database(settings.database_url)
    await db.init()
    repo = Repository(db)
    audit = AuditService(repo, settings.audit_path)
    service = ApprovalService(repo, settings, audit)
    return settings, db, repo, service


async def create_pending(service: ApprovalService, params: dict | None = None):
    params = params or {"project": "demo-django-store", "source_id": "src-1", "port": 8000}
    return await service.create(
        workflow_id="wf-sec", stage="deploy", action="create_release",
        project="demo-django-store", title="release", reason="test", params=params,
        risk_level="high",
    )


async def test_approval_is_single_use(tmp_path):
    settings, db, repo, service = await build_approval_service(tmp_path)
    approval = await create_pending(service)
    await service.decide(approval.id, decision="approved")
    params = approval.params
    await service.validate_and_consume(approval.id, workflow_id="wf-sec", params=params,
                                       required_stage="deploy")
    with pytest.raises(PolicyViolation) as excinfo:
        await service.validate_and_consume(approval.id, workflow_id="wf-sec", params=params,
                                           required_stage="deploy")
    assert "already" in excinfo.value.message.lower()
    await db.dispose()


async def test_approval_expiry_blocks_consumption(tmp_path):
    settings, db, repo, service = await build_approval_service(tmp_path)
    approval = await create_pending(service)
    await service.decide(approval.id, decision="approved")
    await repo.update_approval(
        approval.id, expires_at=iso(utcnow() - timedelta(minutes=1))
    )
    with pytest.raises(PolicyViolation):
        await service.validate_and_consume(
            approval.id, workflow_id="wf-sec", params=approval.params, required_stage="deploy"
        )
    await db.dispose()


async def test_approval_is_bound_to_parameters(tmp_path):
    settings, db, repo, service = await build_approval_service(tmp_path)
    approval = await create_pending(service)
    await service.decide(approval.id, decision="approved")
    tampered = {**approval.params, "port": 9999}
    with pytest.raises(PolicyViolation) as excinfo:
        await service.validate_and_consume(
            approval.id, workflow_id="wf-sec", params=tampered, required_stage="deploy"
        )
    assert excinfo.value.details["reason"] == "fingerprint_mismatch"
    await db.dispose()


async def test_rejected_approval_cannot_be_consumed(tmp_path):
    settings, db, repo, service = await build_approval_service(tmp_path)
    approval = await create_pending(service)
    await service.decide(approval.id, decision="rejected")
    with pytest.raises(PolicyViolation):
        await service.validate_and_consume(
            approval.id, workflow_id="wf-sec", params=approval.params, required_stage="deploy"
        )
    await db.dispose()


async def test_deciding_twice_conflicts(tmp_path):
    settings, db, repo, service = await build_approval_service(tmp_path)
    approval = await create_pending(service)
    await service.decide(approval.id, decision="approved")
    with pytest.raises(ConflictError):
        await service.decide(approval.id, decision="rejected")
    await db.dispose()


async def test_approval_creation_is_idempotent(tmp_path):
    settings, db, repo, service = await build_approval_service(tmp_path)
    first = await create_pending(service)
    second = await service.create(
        workflow_id="wf-sec", stage="deploy", action="create_release",
        project="demo-django-store", title="other", reason="other", params={"a": 1},
        attempt=0,
    )
    assert first.id == second.id
    await db.dispose()


def test_fingerprint_is_order_independent():
    assert fingerprint({"a": 1, "b": 2}) == fingerprint({"b": 2, "a": 1})
    assert fingerprint({"a": 1}) != fingerprint({"a": 2})


# ---------------------------------------------------------------------------
# API-level security
# ---------------------------------------------------------------------------
def test_api_rejects_invalid_project_names(client):
    response = client.post("/api/diagnose", json={"project": "../../etc/passwd"})
    assert response.status_code == 422


def test_unknown_approval_returns_404(client):
    assert client.post("/api/approvals/apv-does-not-exist/approve", json={}).status_code == 404


def test_deploy_tool_without_approval_is_blocked(client):
    from app.mcp.tool_registry import ToolHandlers

    handlers = ToolHandlers(client.app.state.container)
    import asyncio

    async def call():
        return await handlers.liara_deploy_approved_source("wf-unknown", "apv-fake")

    with pytest.raises((PolicyViolation, AppValidationError, NotFoundError)):
        asyncio.run(call())


def test_auth_disabled_by_default(client):
    assert client.get("/api/projects").status_code == 200


def test_auth_enforced_when_enabled(tmp_path):
    from fastapi.testclient import TestClient

    from app.main import create_app

    settings = make_settings(
        tmp_path, app_auth_enabled=True, app_access_token="test-access-token"
    )
    with TestClient(create_app(settings)) as secured:
        assert secured.get("/api/projects").status_code == 401
        assert secured.get("/api/projects",
                           headers={"X-App-Token": "test-access-token"}).status_code == 200
        assert secured.get("/api/projects", headers={"X-App-Token": "wrong"}).status_code == 401
        # health stays public for probes
        assert secured.get("/api/health").status_code == 200
        # HTML pages redirect to the login form
        page = secured.get("/", follow_redirects=False)
        assert page.status_code == 303
        assert page.headers["location"].startswith("/login")


def test_secrets_do_not_appear_in_api_responses(client):
    settings = client.app.state.settings
    body = client.get("/api/settings/status").text
    assert settings.app_secret_key.get_secret_value() not in body
    assert settings.liara_token not in body or not settings.liara_token


def test_audit_log_contains_no_token(client):
    client.get("/api/projects")
    client.post("/api/settings/test-liara-connection")
    audit_path = client.app.state.settings.audit_path
    assert audit_path.exists(), "audit log must be created"
    content = audit_path.read_text(encoding="utf-8")
    assert content.strip(), "audit log must contain events"
    assert "authorization" not in content.lower()
    token = client.app.state.settings.liara_token
    if token:
        assert token not in content


# ---------------------------------------------------------------------------
# workspace isolation (regression: never branch the host repository)
# ---------------------------------------------------------------------------
def _git(git: str, cwd: Path, *args: str) -> str:
    import subprocess

    result = subprocess.run(
        [git, "-C", str(cwd), *args], capture_output=True, text=True, check=True
    )
    return result.stdout.strip()


def test_workspace_git_repository_is_isolated_from_the_host_checkout(tmp_path):
    """A workspace inside the host repo must get its own repository.

    Regression test for a bug where ``git checkout -B ai-fix/...`` ran inside the
    enclosing checkout and silently switched the developer's branch.
    """
    import asyncio
    import shutil
    import subprocess

    from app.services.coding_agent_service import WorkspaceManager

    git = shutil.which("git")
    if not git:
        pytest.skip("git is not installed")

    host = tmp_path / "host"
    host.mkdir()
    subprocess.run([git, "init", "-q", str(host)], check=True)
    (host / "app.py").write_text("print('host')\n", encoding="utf-8")
    _git(git, host, "add", "-A")
    subprocess.run(
        [git, "-C", str(host), "-c", "user.name=test", "-c", "user.email=test@example.com",
         "commit", "-qm", "init"],
        check=True,
    )
    host_branch = _git(git, host, "rev-parse", "--abbrev-ref", "HEAD")

    workspace = host / "data" / "workspaces" / "wf-test"
    workspace.mkdir(parents=True)
    (workspace / "app.py").write_text("print('workspace')\n", encoding="utf-8")

    manager = WorkspaceManager(make_settings(tmp_path), None)  # audit unused by _prepare_git
    info = asyncio.run(manager._prepare_git(workspace, "ai-fix/wf-test"))

    assert info["initialised"] is True
    assert Path(_git(git, workspace, "rev-parse", "--show-toplevel")) == workspace.resolve()
    assert _git(git, workspace, "rev-parse", "--abbrev-ref", "HEAD") == "ai-fix/wf-test"

    # the enclosing repository is untouched
    assert _git(git, host, "rev-parse", "--abbrev-ref", "HEAD") == host_branch
    assert _git(git, host, "branch", "--list", "ai-fix/*") == ""
