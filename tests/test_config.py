"""Configuration validation tests."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.core.config import ConfigError, Settings, load_settings
from tests.conftest import make_settings


def test_defaults_are_demo_safe(tmp_path):
    settings = make_settings(tmp_path)
    assert settings.demo_mode is True
    assert settings.llm_provider == "disabled"
    assert settings.coding_agent_provider == "none"
    assert settings.liara_allow_writes is False
    assert settings.liara_enable_deploy is False
    assert settings.coding_agent_allow_git_push is False
    assert settings.allowed_deploy_projects == []
    readiness = settings.live_readiness()
    assert readiness["live_ready"] is False
    assert any("DEMO_MODE" in blocker for blocker in readiness["blockers"])


def test_unknown_variable_is_rejected(tmp_path):
    env_file = tmp_path / ".env"
    env_file.write_text("DEMO_MODE=true\nLIARAPILOT_TOTALLY_UNKNOWN=1\n", encoding="utf-8")
    with pytest.raises(ConfigError) as excinfo:
        load_settings(env_file=env_file, data_dir=tmp_path)
    assert "LIARAPILOT_TOTALLY_UNKNOWN" in str(excinfo.value)


def test_non_local_bind_requires_auth(tmp_path):
    with pytest.raises(ValidationError):
        make_settings(tmp_path, app_host="0.0.0.0", app_auth_enabled=False)


def test_auth_enabled_requires_token(tmp_path):
    with pytest.raises(ValidationError):
        make_settings(tmp_path, app_host="0.0.0.0", app_auth_enabled=True, app_access_token="")


def test_placeholder_token_is_not_treated_as_configured(tmp_path):
    settings = make_settings(tmp_path, liara_api_token="CHANGE_ME_GENERATE_A_RANDOM_SECRET")
    assert settings.has_liara_token is False


def test_auth_scheme_normalisation(tmp_path):
    assert make_settings(tmp_path, liara_auth_scheme="bearer").liara_auth_scheme == "Bearer"
    assert make_settings(tmp_path, liara_auth_scheme="token").liara_auth_scheme == "token"
    with pytest.raises(ValidationError):
        make_settings(tmp_path, liara_auth_scheme="basic")


def test_repair_attempts_are_capped(tmp_path):
    with pytest.raises(ValidationError):
        make_settings(tmp_path, coding_agent_max_repair_attempts=9)


def test_invalid_healthcheck_url_is_rejected(tmp_path):
    with pytest.raises(ValidationError):
        make_settings(tmp_path, deploy_healthcheck_url="ftp://example.com/health")


def test_non_sqlite_database_is_rejected(tmp_path):
    with pytest.raises(ValidationError):
        make_settings(tmp_path, database_url="postgresql+asyncpg://user:pw@host/db")


def test_public_status_never_contains_secrets(tmp_path):
    settings = make_settings(
        tmp_path,
        liara_api_token="liara_SUPERSECRETTOKEN123",
        llm_api_key="sk-supersecretkeyvalue",
        app_secret_key="a-very-secret-signing-key",
        app_access_token="app-access-secret",
    )
    rendered = repr(settings.public_status())
    for secret in (
        "liara_SUPERSECRETTOKEN123",
        "sk-supersecretkeyvalue",
        "a-very-secret-signing-key",
        "app-access-secret",
    ):
        assert secret not in rendered


def test_ready_requires_live_mode_and_token(tmp_path):
    live = make_settings(
        tmp_path, demo_mode=False, liara_api_token="real-looking-token",
        liara_deploy_allowed_projects="demo-django-store",
    )
    readiness = live.live_readiness()
    assert readiness["live_ready"] is True
    assert any("LIARA_ALLOW_WRITES" in warning for warning in readiness["warnings"])


def test_settings_load_from_env_file(tmp_path):
    env_file = tmp_path / ".env"
    env_file.write_text("DEMO_MODE=true\nAPP_NAME=TestPilot\n", encoding="utf-8")
    settings = Settings(_env_file=str(env_file), data_dir=tmp_path)
    assert settings.app_name == "TestPilot"
    assert settings.demo_mode is True
