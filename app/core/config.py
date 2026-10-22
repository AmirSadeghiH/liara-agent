"""Application configuration.

All values come from environment variables / the local ``.env`` file.  The
settings object is validated eagerly: an invalid or contradictory
configuration produces one human readable error instead of failing later at
runtime.

Security note: secrets are held as plain strings inside the process, but they
are never serialised by :meth:`Settings.public_status` and never written to
logs, audit records, the UI or model prompts.
"""

from __future__ import annotations

import ipaddress
import logging
import os
from functools import lru_cache
from pathlib import Path
from typing import Literal
from urllib.parse import urlparse

from pydantic import SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

LOGGER = logging.getLogger(__name__)

PLACEHOLDER_VALUES = {
    "",
    "change_me",
    "change_me_generate_a_random_secret",
    "changeme",
    "your-token",
    "your_token",
    "your-api-key",
    "<api-token>",
    "<api-key>",
    "none",
    "null",
}

LOOPBACK_HOSTS = {"127.0.0.1", "localhost", "::1", "127.0.1.1"}

# Non-settings variables that may legitimately appear in .env / the environment.
ALLOWED_EXTRA_ENV_KEYS = {"LIARAPILOT_CONFIGURED", "LIARAPILOT_RUN_LIVE"}


class ConfigError(RuntimeError):
    """Raised when the runtime configuration is unsafe or inconsistent."""


def _is_placeholder(value: str | None) -> bool:
    return (value or "").strip().lower() in PLACEHOLDER_VALUES


def _looks_like_loopback(host: str) -> bool:
    host = (host or "").strip().lower()
    if host in LOOPBACK_HOSTS:
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


class Settings(BaseSettings):
    """Typed application settings."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="forbid",
        case_sensitive=False,
        # Unknown keys in .env raise a clear validation error (see main.py).
        validate_default=True,
    )

    # ----- application -----
    app_name: str = "LiaraPilot"
    app_env: Literal["development", "production", "test"] = "development"
    app_host: str = "127.0.0.1"
    app_port: int = 8000
    log_level: str = "INFO"
    app_secret_key: SecretStr = SecretStr("CHANGE_ME_GENERATE_A_RANDOM_SECRET")
    app_auth_enabled: bool = False
    app_access_token: SecretStr = SecretStr("")
    data_dir: Path = Path("./data")

    # ----- demo -----
    demo_mode: bool = True
    demo_scenario: str = "django_500"
    demo_step_delay_seconds: float = 0.35

    # ----- persistence -----
    database_url: str = "sqlite+aiosqlite:///./data/liarapilot.db"
    langgraph_checkpoint_path: Path = Path("./data/langgraph-checkpoints.sqlite")

    # ----- llm -----
    llm_provider: Literal["disabled", "openai_compatible"] = "disabled"
    llm_base_url: str = "https://api.openai.com/v1"
    llm_api_key: SecretStr = SecretStr("")
    llm_model: str = ""
    llm_temperature: float = 0.1
    llm_timeout_seconds: float = 60.0

    # ----- liara -----
    liara_base_url: str = "https://api.liara.ir"
    liara_api_token: SecretStr = SecretStr("")
    liara_auth_scheme: str = "token"
    liara_request_timeout_seconds: float = 30.0
    liara_max_retries: int = 2
    liara_deploy_allowed_projects: str = ""
    liara_allow_writes: bool = False
    liara_enable_deploy: bool = False
    liara_source_upload_max_mb: int = 50
    # Used only when no previous release exposes a port. Recorded as
    # ``port_source=LIARA_DEFAULT_PORT`` in the deployment record.
    liara_default_port: int = 3000

    # ----- coding agent -----
    coding_agent_provider: Literal["none", "claude_code", "codex"] = "none"
    coding_agent_workspace_root: Path = Path("./data/workspaces")
    # Optional path to a local clone used to build the repair workspace in Live
    # mode. Empty means "manual handoff only" (no repository is guessed).
    coding_agent_repo_path: str = ""
    coding_agent_timeout_seconds: int = 900
    coding_agent_max_repair_attempts: int = 3
    coding_agent_max_turns: int = 8
    coding_agent_auto_execute: bool = False
    coding_agent_allow_git_push: bool = False

    # ----- HITL -----
    hitl_approval_ttl_minutes: int = 15
    hitl_require_production_deploy_approval: bool = True
    hitl_require_git_push_approval: bool = True
    hitl_require_high_risk_approval: bool = True

    # ----- verification -----
    deploy_healthcheck_url: str = ""
    deploy_healthcheck_expect_status: int = 200
    deploy_healthcheck_retries: int = 6
    deploy_healthcheck_interval_seconds: float = 10.0
    deploy_healthcheck_timeout_seconds: float = 10.0

    # ----- audit -----
    audit_log_path: Path = Path("./data/audit.jsonl")
    log_redact_secrets: bool = True

    # ------------------------------------------------------------------
    # validators
    # ------------------------------------------------------------------
    @field_validator("liara_auth_scheme")
    @classmethod
    def _validate_auth_scheme(cls, value: str) -> str:
        raw = (value or "").strip()
        lowered = raw.lower()
        if lowered in {"token", "", "api_key", "apikey"}:
            return "token"
        if lowered == "bearer":
            return "Bearer"
        raise ValueError("LIARA_AUTH_SCHEME must be 'token' or 'Bearer'")

    @field_validator("liara_max_retries", "liara_source_upload_max_mb", "hitl_approval_ttl_minutes",
                     "coding_agent_max_repair_attempts", "coding_agent_max_turns")
    @classmethod
    def _validate_positive_int(cls, value: int) -> int:
        if value < 0:
            raise ValueError("value must be >= 0")
        return value

    @field_validator("coding_agent_max_repair_attempts")
    @classmethod
    def _cap_repair_attempts(cls, value: int) -> int:
        if value > 3:
            raise ValueError("CODING_AGENT_MAX_REPAIR_ATTEMPTS must be <= 3 (safety cap)")
        return value or 1

    @field_validator("demo_step_delay_seconds")
    @classmethod
    def _cap_demo_delay(cls, value: float) -> float:
        return max(0.0, min(float(value), 5.0))

    @field_validator("liara_base_url", "llm_base_url")
    @classmethod
    def _validate_base_url(cls, value: str) -> str:
        parsed = urlparse(value)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError("must be a valid http(s) URL")
        return value.rstrip("/")

    @field_validator("deploy_healthcheck_url")
    @classmethod
    def _validate_healthcheck_url(cls, value: str) -> str:
        if not value:
            return ""
        parsed = urlparse(value)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError("DEPLOY_HEALTHCHECK_URL must be empty or a valid http(s) URL")
        return value

    @field_validator("log_level")
    @classmethod
    def _validate_log_level(cls, value: str) -> str:
        level = (value or "INFO").upper()
        if level not in {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}:
            raise ValueError("LOG_LEVEL must be one of DEBUG/INFO/WARNING/ERROR/CRITICAL")
        return level

    @field_validator("database_url")
    @classmethod
    def _validate_database_url(cls, value: str) -> str:
        if not value.startswith("sqlite"):
            raise ValueError(
                "Only SQLite is supported in the MVP (sqlite+aiosqlite:///./data/liarapilot.db). "
                "The repository layer is database agnostic for a later PostgreSQL migration."
            )
        return value

    @model_validator(mode="after")
    def _validate_security_invariants(self) -> Settings:
        if not _looks_like_loopback(self.app_host) and not self.app_auth_enabled:
            raise ValueError(
                f"Refusing to bind to non-local host {self.app_host!r} with APP_AUTH_ENABLED=false. "
                "Enable app authentication or bind to 127.0.0.1."
            )
        if self.app_auth_enabled and _is_placeholder(self.app_access_token.get_secret_value()):
            raise ValueError("APP_AUTH_ENABLED=true requires a non-empty APP_ACCESS_TOKEN")
        if self.app_env == "production" and _is_placeholder(self.app_secret_key.get_secret_value()):
            raise ValueError("APP_ENV=production requires a random APP_SECRET_KEY")
        if not self.demo_mode and _is_placeholder(self.liara_api_token.get_secret_value()):
            LOGGER.warning(
                "DEMO_MODE=false but LIARA_API_TOKEN is empty; live Liara calls will fail "
                "with an authentication error (readiness reports this)."
            )
        if self.liara_enable_deploy and self.demo_mode:
            LOGGER.info("LIARA_ENABLE_DEPLOY=true is ignored while DEMO_MODE=true.")
        return self

    # ------------------------------------------------------------------
    # derived values
    # ------------------------------------------------------------------
    @property
    def data_path(self) -> Path:
        return Path(self.data_dir).expanduser().resolve()

    @property
    def workspace_root(self) -> Path:
        return Path(self.coding_agent_workspace_root).expanduser().resolve()

    @property
    def audit_path(self) -> Path:
        return Path(self.audit_log_path).expanduser().resolve()

    @property
    def checkpoint_file(self) -> Path:
        return Path(self.langgraph_checkpoint_path).expanduser().resolve()

    @property
    def allowed_deploy_projects(self) -> list[str]:
        return [p.strip() for p in (self.liara_deploy_allowed_projects or "").split(",") if p.strip()]

    @property
    def demo_fixture_root(self) -> Path:
        return Path(__file__).resolve().parents[1] / "demo_fixtures"

    @property
    def has_liara_token(self) -> bool:
        return not _is_placeholder(self.liara_api_token.get_secret_value())

    @property
    def has_llm(self) -> bool:
        return (
            self.llm_provider != "disabled"
            and bool(self.llm_model.strip())
            and not _is_placeholder(self.llm_api_key.get_secret_value())
        )

    @property
    def auth_token(self) -> str:
        return self.app_access_token.get_secret_value()

    @property
    def liara_token(self) -> str:
        return self.liara_api_token.get_secret_value()

    def ensure_directories(self) -> None:
        for path in (self.data_path, self.workspace_root, self.checkpoint_file.parent,
                     self.audit_path.parent):
            path.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------
    # readiness / diagnostics
    # ------------------------------------------------------------------
    def live_readiness(self) -> dict[str, object]:
        """Return a secret-free description of whether live mode can run."""
        blockers: list[str] = []
        warnings: list[str] = []
        if self.demo_mode:
            blockers.append("DEMO_MODE=true — external Liara calls are simulated.")
        if not self.has_liara_token:
            blockers.append("LIARA_API_TOKEN is empty or still a placeholder.")
        if not _looks_like_loopback(self.app_host) and not self.app_auth_enabled:
            blockers.append("Non-local bind requires APP_AUTH_ENABLED=true.")
        if not self.allowed_deploy_projects:
            warnings.append("LIARA_DEPLOY_ALLOWED_PROJECTS is empty — all write operations are blocked.")
        if not self.liara_allow_writes:
            warnings.append("LIARA_ALLOW_WRITES=false — source uploads are blocked.")
        if not self.liara_enable_deploy:
            warnings.append("LIARA_ENABLE_DEPLOY=false — release creation is blocked.")
        if not self.deploy_healthcheck_url:
            warnings.append("DEPLOY_HEALTHCHECK_URL is empty — post-deploy health is 'unverified'.")
        if not self.has_llm:
            warnings.append("LLM is disabled — diagnosis uses the deterministic rule engine.")
        return {
            "demo_mode": self.demo_mode,
            "live_ready": not blockers and not self.demo_mode,
            "blockers": blockers,
            "warnings": warnings,
            "liara_base_url": self.liara_base_url,
            "auth_scheme": self.liara_auth_scheme,
            "write_policy": {
                "allow_writes": self.liara_allow_writes,
                "enable_deploy": self.liara_enable_deploy,
                "allowed_projects": self.allowed_deploy_projects,
                "git_push_allowed": self.coding_agent_allow_git_push,
            },
        }

    def public_status(self) -> dict[str, object]:
        """Configuration status safe to render in the UI (no secrets)."""
        return {
            "app_name": self.app_name,
            "app_env": self.app_env,
            "demo_mode": self.demo_mode,
            "demo_scenario": self.demo_scenario,
            "llm": {
                "provider": self.llm_provider,
                "model": self.llm_model or None,
                "configured": self.has_llm,
            },
            "liara": {
                "base_url": self.liara_base_url,
                "token_configured": self.has_liara_token,
                "auth_scheme": self.liara_auth_scheme,
                "timeout_seconds": self.liara_request_timeout_seconds,
                "max_retries": self.liara_max_retries,
                "source_upload_max_mb": self.liara_source_upload_max_mb,
            },
            "coding_agent": {
                "provider": self.coding_agent_provider,
                "auto_execute": self.coding_agent_auto_execute,
                "git_push": self.coding_agent_allow_git_push,
                "max_repair_attempts": self.coding_agent_max_repair_attempts,
            },
            "hitl": {
                "approval_ttl_minutes": self.hitl_approval_ttl_minutes,
                "require_production_deploy_approval": self.hitl_require_production_deploy_approval,
                "require_git_push_approval": self.hitl_require_git_push_approval,
            },
            "verification": {
                "healthcheck_url_configured": bool(self.deploy_healthcheck_url),
                "expect_status": self.deploy_healthcheck_expect_status,
            },
            "auth_enabled": self.app_auth_enabled,
            "readiness": self.live_readiness(),
        }


def _validate_env_file_keys(env_file: str | Path | None = None) -> None:
    """Reject unknown keys in the local ``.env`` file with a readable error.

    Process environment variables are *not* enumerated (they belong to the host
    and would produce false positives); the project's own ``.env`` file is the
    configuration surface we control.
    """
    path = Path(env_file or ".env")
    if not path.is_file():
        return
    known = {name.upper() for name in Settings.model_fields}
    unknown: list[str] = []
    try:
        for raw_line in path.read_text(encoding="utf-8").splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key = line.split("=", 1)[0].strip().upper()
            if key in known or key in ALLOWED_EXTRA_ENV_KEYS:
                continue
            unknown.append(key)
    except OSError as exc:  # pragma: no cover - unreadable file
        raise ConfigError(f"Cannot read {path}: {exc}") from exc
    if unknown:
        raise ConfigError(
            "Unknown configuration key(s) in .env: "
            + ", ".join(sorted(set(unknown)))
            + ". Remove them or fix the spelling (see .env.example)."
        )


def load_settings(env_file: str | Path | None = None, **overrides: object) -> Settings:
    """Load settings, mapping pydantic validation errors to a readable error."""
    _validate_env_file_keys(env_file)
    try:
        return Settings(**overrides)  # type: ignore[arg-type]
    except Exception as exc:  # pydantic.ValidationError and subclasses
        raise ConfigError(f"Invalid configuration: {exc}") from exc


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Process-wide settings instance (overridable in tests)."""
    settings = load_settings()
    os.environ.setdefault("LIARAPILOT_CONFIGURED", "1")
    return settings


def reset_settings_cache() -> None:
    get_settings.cache_clear()
