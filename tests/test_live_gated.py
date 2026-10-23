"""Live Liara integration tests — skipped unless explicitly enabled.

Run them with::

    set LIARAPILOT_RUN_LIVE=1
    set LIARA_API_TOKEN=<real token>
    set DEMO_MODE=false
    pytest -m live

They are excluded from the default run (see ``pytest.ini`` marker policy in
``pyproject.toml`` / this module's ``pytestmark``).
"""

from __future__ import annotations

import os

import pytest

from app.liara.adapter import LiveLiaraAdapter
from app.liara.errors import LiaraAuthError
from tests.conftest import make_settings

pytestmark = [
    pytest.mark.live,
    pytest.mark.skipif(
        os.environ.get("LIARAPILOT_RUN_LIVE") != "1",
        reason="live tests disabled (set LIARAPILOT_RUN_LIVE=1 with a real token)",
    ),
]


@pytest.fixture
def live_settings(tmp_path):
    token = os.environ.get("LIARA_API_TOKEN", "")
    if not token:
        pytest.skip("LIARA_API_TOKEN is required for live tests")
    return make_settings(tmp_path, demo_mode=False, liara_api_token=token)


async def test_live_authentication_and_project_list(live_settings):
    adapter = LiveLiaraAdapter(live_settings)
    try:
        result = await adapter.ping()
        assert result["ok"] is True
        assert result["mode"] == "live"
    finally:
        await adapter.aclose()


async def test_live_invalid_token_raises_auth_error(live_settings, tmp_path):
    bad = make_settings(tmp_path, demo_mode=False, liara_api_token="definitely-not-valid")
    adapter = LiveLiaraAdapter(bad)
    try:
        with pytest.raises(LiaraAuthError):
            await adapter.list_projects()
    finally:
        await adapter.aclose()


async def test_live_project_metrics_shape(live_settings):
    adapter = LiveLiaraAdapter(live_settings)
    try:
        projects = await adapter.list_projects()
        if not projects:
            pytest.skip("token has no projects")
        project = projects[0].name
        cpu = await adapter.get_cpu_metrics(project)
        memory = await adapter.get_memory_metrics(project)
        # The shape may be empty for a freshly created app, but it must parse.
        assert cpu.name == "cpu"
        assert memory.name == "memory"
        logs = await adapter.get_logs(project)
        assert isinstance(logs, list)
    finally:
        await adapter.aclose()
