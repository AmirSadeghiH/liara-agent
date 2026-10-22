"""Security primitives shared by HTTP routes, workflow nodes and MCP tools.

Everything that can change state must pass through the guards in this module.
The HTTP layer is *not* the only entry point: MCP tools and the LangGraph nodes
call the same services, so authorisation is enforced in the service layer.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import ipaddress
import re
import socket
import time
from pathlib import Path
from urllib.parse import urlparse

from fastapi import Request

from app.core.config import Settings
from app.core.errors import AuthRequired, PolicyViolation, ValidationError

PROJECT_NAME_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9._-]{0,62}$")
SAFE_FILE_NAME_RE = re.compile(r"^[A-Za-z0-9._-]{1,128}$")

SESSION_TTL_SECONDS = 12 * 3600
SESSION_COOKIE = "liarapilot_session"


# ---------------------------------------------------------------------------
# project / input validation
# ---------------------------------------------------------------------------
def validate_project_name(name: str) -> str:
    """Validate a Liara project name before it is used in a URL or a path."""
    candidate = (name or "").strip()
    if not PROJECT_NAME_RE.match(candidate):
        raise ValidationError(
            "Invalid project name. Allowed: letters, digits, dot, dash and underscore (max 63 chars)."
        )
    if ".." in candidate or "/" in candidate or "\\" in candidate:
        raise ValidationError("Invalid project name: path traversal sequences are not allowed.")
    return candidate


def ensure_deploy_allowed(settings: Settings, project: str) -> None:
    """Write operations require an explicit, non-empty project allowlist."""
    allowed = settings.allowed_deploy_projects
    if not allowed:
        raise PolicyViolation(
            "No projects are allowlisted for write operations. "
            "Set LIARA_DEPLOY_ALLOWED_PROJECTS to enable deployments.",
            details={"reason": "empty_allowlist", "project": project},
        )
    if project not in allowed:
        raise PolicyViolation(
            "This project is not in LIARA_DEPLOY_ALLOWED_PROJECTS.",
            details={"reason": "project_not_allowlisted", "project": project},
        )


def ensure_writes_enabled(settings: Settings, *, operation: str) -> None:
    if settings.demo_mode:
        return  # simulated writes never reach Liara
    if not settings.liara_allow_writes:
        raise PolicyViolation(
            "Write operations are disabled (LIARA_ALLOW_WRITES=false).",
            details={"operation": operation, "reason": "writes_disabled"},
        )


def ensure_deploys_enabled(settings: Settings, *, operation: str = "deploy") -> None:
    if settings.demo_mode:
        return
    ensure_writes_enabled(settings, operation=operation)
    if not settings.liara_enable_deploy:
        raise PolicyViolation(
            "Deployments are disabled (LIARA_ENABLE_DEPLOY=false).",
            details={"operation": operation, "reason": "deploy_disabled"},
        )


def ensure_git_push_allowed(settings: Settings) -> None:
    if not settings.coding_agent_allow_git_push:
        raise PolicyViolation(
            "Git push is disabled (CODING_AGENT_ALLOW_GIT_PUSH=false).",
            details={"reason": "git_push_disabled"},
        )


# ---------------------------------------------------------------------------
# filesystem confinement
# ---------------------------------------------------------------------------
def assert_within(root: Path, candidate: Path) -> Path:
    """Reject paths that escape *root* (including via symlinks)."""
    root_resolved = Path(root).resolve()
    candidate_resolved = Path(candidate).resolve()
    if candidate_resolved != root_resolved and root_resolved not in candidate_resolved.parents:
        raise PolicyViolation(
            "Path escapes the allowed workspace root.",
            details={"root": str(root_resolved), "candidate": str(candidate_resolved)},
        )
    return candidate_resolved


def safe_join(root: Path, *parts: str) -> Path:
    for part in parts:
        if not part or part in {".", ".."} or "/" in part or "\\" in part:
            raise PolicyViolation("Unsafe path segment rejected.", details={"segment": part})
    return assert_within(root, Path(root).joinpath(*parts))


# ---------------------------------------------------------------------------
# SSRF guard for health checks
# ---------------------------------------------------------------------------
BLOCKED_HOSTNAMES = {"metadata.google.internal", "metadata", "instance-data"}


def validate_healthcheck_url(url: str) -> str:
    """Validate a user supplied health-check URL and block internal targets."""
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValidationError("Health-check URL must be a valid http(s) URL.")
    host = parsed.hostname.lower()
    if host in BLOCKED_HOSTNAMES or host.endswith(".internal"):
        raise PolicyViolation("Health-check target is not allowed.", details={"host": host})
    try:
        infos = socket.getaddrinfo(host, None)
    except OSError:
        # DNS may be unavailable offline; allow the URL but the request will fail
        # and be reported as 'unverified'.
        return url
    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved:
            raise PolicyViolation(
                "Health-check target resolves to a private/loopback address.",
                details={"host": host},
            )
    return url


# ---------------------------------------------------------------------------
# application authentication (only enforced when APP_AUTH_ENABLED=true)
# ---------------------------------------------------------------------------
def _sign(secret: str, payload: str) -> str:
    return hmac.new(secret.encode("utf-8"), payload.encode("utf-8"), hashlib.sha256).hexdigest()


def create_session_token(secret: str, *, issued_at: float | None = None) -> str:
    ts = str(int(issued_at or time.time()))
    mac = _sign(secret, ts)
    raw = f"{ts}.{mac}".encode()
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def verify_session_token(secret: str, token: str | None, *, now: float | None = None) -> bool:
    if not token:
        return False
    try:
        padded = token + "=" * (-len(token) % 4)
        decoded = base64.urlsafe_b64decode(padded.encode()).decode()
        ts_str, mac = decoded.split(".", 1)
        ts = int(ts_str)
    except Exception:
        return False
    if not hmac.compare_digest(_sign(secret, ts_str), mac):
        return False
    return (now or time.time()) - ts <= SESSION_TTL_SECONDS


def _extract_token(request: Request) -> str | None:
    header_token = request.headers.get("x-app-token")
    if header_token:
        return header_token.strip()
    auth = request.headers.get("authorization", "")
    if auth.lower().startswith("bearer "):
        return auth[7:].strip()
    return request.cookies.get(SESSION_COOKIE)


def require_app_auth(request: Request) -> None:
    """FastAPI dependency: enforce app auth when it is enabled."""
    settings: Settings = request.app.state.settings
    if not settings.app_auth_enabled:
        return
    token = _extract_token(request)
    if not token:
        raise AuthRequired("Authentication required. Sign in or provide X-App-Token.")
    # Constant-time comparison against the configured access token, or a signed
    # session cookie issued by the login form.
    if hmac.compare_digest(token, settings.auth_token):
        return
    if verify_session_token(settings.app_secret_key.get_secret_value(), token):
        return
    raise AuthRequired("Invalid or expired credentials.")


def is_ui_authenticated(request: Request) -> bool:
    settings: Settings = request.app.state.settings
    if not settings.app_auth_enabled:
        return True
    token = request.cookies.get(SESSION_COOKIE)
    if verify_session_token(settings.app_secret_key.get_secret_value(), token):
        return True
    return bool(token and hmac.compare_digest(token, settings.auth_token))
