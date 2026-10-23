"""Mock and Live adapters must expose exactly the same contract."""

from __future__ import annotations

import inspect

import pytest

from app.core.errors import AuthRequired, NotFoundError, PolicyViolation
from app.liara.adapter import LiaraAdapter, LiveLiaraAdapter
from app.liara.mock_adapter import MockLiaraAdapter, get_scenario
from tests.conftest import make_settings

CONTRACT = [
    "list_projects", "get_project", "get_logs", "get_cpu_metrics",
    "get_memory_metrics", "get_releases", "upload_source", "create_release", "ping",
]


def test_contract_methods_exist_on_both_adapters():
    abstract = {name for name in LiaraAdapter.__abstractmethods__}
    # ``ping`` has a default implementation but must stay overridable.
    assert set(CONTRACT) - {"ping"} <= abstract
    for name in CONTRACT:
        assert callable(getattr(MockLiaraAdapter, name))
        assert callable(getattr(LiveLiaraAdapter, name))


async def test_mock_adapter_full_roundtrip(tmp_path):
    adapter = MockLiaraAdapter(make_settings(tmp_path))
    projects = await adapter.list_projects()
    assert [p.name for p in projects]
    assert adapter.mode == "demo"
    assert adapter.simulated is True

    source_id = await adapter.upload_source("demo-django-store", archive=b"demo", filename="a.tar.gz")
    with pytest.raises(NotFoundError):
        await adapter.create_release("demo-django-store", source_id="unknown", port=8000,
                                     project_type="django")
    release_id = await adapter.create_release(
        "demo-django-store", source_id=source_id, port=8000, project_type="django"
    )
    page = await adapter.get_releases("demo-django-store")
    assert page.releases[0].id == release_id
    assert adapter.simulated_health("demo-django-store")["ok"] is True


async def test_mock_adapter_unknown_project(tmp_path):
    adapter = MockLiaraAdapter(make_settings(tmp_path))
    with pytest.raises(NotFoundError):
        await adapter.get_project("does-not-exist")


async def test_live_adapter_refuses_demo_mode(tmp_path):
    adapter = LiveLiaraAdapter(make_settings(tmp_path, demo_mode=True,
                                             liara_api_token="some-real-token"))
    with pytest.raises(PolicyViolation):
        await adapter.list_projects()
    await adapter.aclose()


async def test_live_adapter_requires_token(tmp_path):
    adapter = LiveLiaraAdapter(make_settings(tmp_path, demo_mode=False))
    with pytest.raises(AuthRequired):
        await adapter.list_projects()
    await adapter.aclose()


def test_scenario_selection(tmp_path):
    adapter = MockLiaraAdapter(make_settings(tmp_path, demo_scenario="healthy_site"))
    assert adapter.scenario.key == "healthy_site"
    adapter.use_scenario("memory_pressure")
    assert adapter.scenario.key == "memory_pressure"
    assert get_scenario("unknown").key == "django_500"


def test_mock_never_uses_network(monkeypatch, tmp_path):
    import socket

    def _boom(*args, **kwargs):  # pragma: no cover - should never run
        raise AssertionError("Demo mode must not open sockets")

    monkeypatch.setattr(socket, "socket", _boom)
    adapter = MockLiaraAdapter(make_settings(tmp_path))
    assert inspect.iscoroutinefunction(adapter.list_projects)
