"""Liara client contract tests — fully offline (httpx MockTransport)."""

from __future__ import annotations

import json

import httpx
import pytest

from app.core.utils import utcnow
from app.liara.client import LiaraClient
from app.liara.errors import (
    LiaraAuthError,
    LiaraNetworkError,
    LiaraNotFoundError,
    LiaraRateLimitError,
    LiaraResponseError,
    LiaraServerError,
    LiaraTimeoutError,
    LiaraValidationError,
)
from tests.conftest import make_settings

TOKEN = "liara_this_is_a_fake_token_value"


def build_client(tmp_path, handler, **overrides):
    settings = make_settings(tmp_path, demo_mode=False, liara_api_token=TOKEN, **overrides)
    transport = httpx.MockTransport(handler)
    return LiaraClient(settings, transport=transport)


async def test_list_projects_sends_documented_request(tmp_path):
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["auth"] = request.headers.get("authorization")
        seen["method"] = request.method
        return httpx.Response(200, json={"projects": [
            {"_id": "abc", "project_id": "demo-app", "type": "django", "status": "running",
             "scale": 1, "planID": "basic-xs", "created_at": "2026-01-01T00:00:00Z",
             "isDeployed": True},
        ]})

    client = build_client(tmp_path, handler)
    projects = await client.list_projects()
    await client.aclose()

    assert seen["url"] == "https://api.liara.ir/v1/projects"
    assert seen["method"] == "GET"
    # Documented request examples send the raw token (no "Bearer" prefix).
    assert seen["auth"] == TOKEN
    assert projects[0].name == "demo-app"
    assert projects[0].id == "abc"
    assert projects[0].is_deployed is True


async def test_bearer_scheme_is_opt_in(tmp_path):
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["auth"] = request.headers.get("authorization")
        return httpx.Response(200, json={"projects": []})

    client = build_client(tmp_path, handler, liara_auth_scheme="Bearer")
    await client.list_projects()
    await client.aclose()
    assert seen["auth"] == f"Bearer {TOKEN}"


@pytest.mark.parametrize(
    ("status", "error_cls"),
    [
        (401, LiaraAuthError),
        (403, LiaraAuthError),
        (404, LiaraNotFoundError),
        (422, LiaraValidationError),
        (500, LiaraServerError),
    ],
)
async def test_http_errors_map_to_typed_errors(tmp_path, status, error_cls):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status, json={"message": "nope"})

    client = build_client(tmp_path, handler, liara_max_retries=0)
    with pytest.raises(error_cls):
        await client.list_projects()
    await client.aclose()


async def test_rate_limit_is_retried_with_bounded_attempts(tmp_path):
    calls = {"n": 0}
    sleeps: list[float] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] < 2:
            return httpx.Response(429, headers={"retry-after": "0"}, json={})
        return httpx.Response(200, json={"projects": []})

    async def fake_sleep(delay: float) -> None:
        sleeps.append(delay)

    client = build_client(tmp_path, handler, liara_max_retries=2)
    client._sleep = fake_sleep  # noqa: SLF001 - test seam
    projects = await client.list_projects()
    await client.aclose()

    assert projects == []
    assert calls["n"] == 2
    assert sleeps and all(delay <= 5.0 for delay in sleeps)


async def test_rate_limit_exhaustion_raises(tmp_path):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(429, headers={"retry-after": "0"}, json={})

    client = build_client(tmp_path, handler, liara_max_retries=1)

    async def fake_sleep(delay: float) -> None:
        return None

    client._sleep = fake_sleep  # noqa: SLF001
    with pytest.raises(LiaraRateLimitError):
        await client.list_projects()
    await client.aclose()


async def test_timeout_retried_then_raised(tmp_path):
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        raise httpx.ConnectTimeout("too slow", request=request)

    client = build_client(tmp_path, handler, liara_max_retries=1)

    async def fake_sleep(delay: float) -> None:
        return None

    client._sleep = fake_sleep  # noqa: SLF001
    with pytest.raises(LiaraTimeoutError):
        await client.list_projects()
    await client.aclose()
    assert calls["n"] == 2  # initial + one retry


async def test_network_error_is_distinct_from_auth_error(tmp_path):
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("boom", request=request)

    client = build_client(tmp_path, handler, liara_max_retries=0)
    with pytest.raises(LiaraNetworkError):
        await client.list_projects()
    await client.aclose()


async def test_post_is_never_retried(tmp_path):
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(503, json={})

    client = build_client(tmp_path, handler, liara_max_retries=3)

    async def fake_sleep(delay: float) -> None:
        return None

    client._sleep = fake_sleep  # noqa: SLF001
    with pytest.raises(LiaraServerError):
        await client.upload_source("demo", archive=b"x", filename="a.tar.gz")
    await client.aclose()
    assert calls["n"] == 1


async def test_auth_header_is_never_audited(tmp_path):
    records: list[dict] = []

    async def hook(record: dict) -> None:
        records.append(record)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"projects": []})

    settings = make_settings(tmp_path, demo_mode=False, liara_api_token=TOKEN)
    client = LiaraClient(settings, transport=httpx.MockTransport(handler), audit_hook=hook)
    await client.list_projects()
    await client.aclose()

    assert records
    serialised = json.dumps(records)
    assert TOKEN not in serialised
    assert "authorization" not in serialised.lower()
    assert records[0]["path"] == "/v1/projects"
    assert records[0]["status_code"] == 200


async def test_error_body_secrets_are_redacted(tmp_path):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"message": f"invalid token {TOKEN}"})

    client = build_client(tmp_path, handler, liara_max_retries=0)
    with pytest.raises(LiaraAuthError) as excinfo:
        await client.list_projects()
    await client.aclose()
    assert TOKEN not in json.dumps(excinfo.value.details)


async def test_logs_require_since_and_fall_back_to_epoch(tmp_path):
    seen: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(dict(request.url.params))
        if "since" in seen[-1] and "-" in seen[-1]["since"]:
            return httpx.Response(400, json={"message": "invalid since"})
        return httpx.Response(200, json=[{"type": "stdout", "datetime": "2026-01-01T00:00:00Z",
                                          "message": "hello"}])

    client = build_client(tmp_path, handler, liara_max_retries=0)
    entries = await client.get_logs("demo", since=utcnow())
    await client.aclose()

    assert len(seen) == 2
    assert seen[1]["since"].isdigit()
    assert entries[0].message == "hello"


async def test_logs_validate_response_type(tmp_path):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"unexpected": "object"})

    client = build_client(tmp_path, handler)
    with pytest.raises(LiaraResponseError):
        await client.get_logs("demo", since=utcnow())
    await client.aclose()


async def test_metrics_are_parsed_from_documented_shape(tmp_path):
    payload = {
        "end": 1717000000,
        "result": [
            {"applet": "demo", "values": [[1717000000, "12.5"], [1717000060, 13.75], [1717000120, "bad"]]},
        ],
    }

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/projects/demo/metrics/cpu"
        assert "since" in request.url.params
        return httpx.Response(200, json=payload)

    client = build_client(tmp_path, handler)
    series = await client.get_cpu_metrics("demo")
    await client.aclose()

    assert series.count == 2
    assert series.maximum == 13.75
    assert series.average == 13.12
    assert series.points[0].value == 12.5


async def test_empty_metrics_marked_unavailable(tmp_path):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"end": 1, "result": []})

    client = build_client(tmp_path, handler)
    series = await client.get_memory_metrics("demo")
    await client.aclose()
    assert series.count == 0
    assert series.unavailable_reason


async def test_release_payload_matches_docs(tmp_path):
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/sources"):
            return httpx.Response(200, json={"sourceID": "src-123"})
        captured["body"] = json.loads(request.content)
        captured["path"] = request.url.path
        return httpx.Response(200, json={"releaseID": "rel-456"})

    client = build_client(tmp_path, handler)
    source_id = await client.upload_source("demo", archive=b"gz-bytes", filename="src.tar.gz")
    release_id = await client.create_release(
        "demo", source_id=source_id, port=8000, project_type="django"
    )
    await client.aclose()

    assert source_id == "src-123"
    assert release_id == "rel-456"
    assert captured["path"] == "/v2/projects/demo/releases"
    assert captured["body"] == {"sourceID": "src-123", "port": 8000, "type": "django"}


async def test_release_requires_valid_arguments(tmp_path):
    def handler(request: httpx.Request) -> httpx.Response:  # pragma: no cover
        raise AssertionError("no request expected")

    client = build_client(tmp_path, handler)
    with pytest.raises(LiaraValidationError):
        await client.create_release("demo", source_id="", port=8000, project_type="django")
    with pytest.raises(LiaraValidationError):
        await client.create_release("demo", source_id="src", port=0, project_type="django")
    with pytest.raises(LiaraValidationError):
        await client.create_release("demo", source_id="src", port=8000, project_type="")
    await client.aclose()


async def test_missing_release_id_is_an_error(tmp_path):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"ok": True})

    client = build_client(tmp_path, handler)
    with pytest.raises(LiaraResponseError):
        await client.create_release("demo", source_id="src", port=8000, project_type="django")
    await client.aclose()


async def test_project_details_do_not_expose_env_values(tmp_path):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"project": {
            "project_id": "demo", "type": "django", "status": "running",
            "envs": [{"key": "SECRET_KEY", "value": "super-secret-value"}, {"key": "DEBUG"}],
        }})

    client = build_client(tmp_path, handler)
    details = await client.get_project("demo")
    await client.aclose()
    assert details.env_keys == ["SECRET_KEY", "DEBUG"]
    assert "super-secret-value" not in repr(details)


async def test_only_documented_paths_are_allowed(tmp_path):
    settings = make_settings(tmp_path, demo_mode=False, liara_api_token=TOKEN)
    client = LiaraClient(settings, transport=httpx.MockTransport(lambda r: httpx.Response(200)))
    with pytest.raises(AssertionError):
        await client._request("GET", "/admin/secret")  # noqa: SLF001 - internal guard
    await client.aclose()
