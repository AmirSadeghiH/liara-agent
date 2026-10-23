"""Liara API response schemas.

Field names mirror the official OpenAPI specification
(https://developers.liara.ir).  We deliberately keep unknown fields so that a
non-breaking addition on Liara's side does not break the MVP, while required
fields are validated strictly enough to detect contract changes.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.core.utils import parse_iso


class _Tolerant(BaseModel):
    """Base model that accepts unknown vendor fields."""

    model_config = ConfigDict(extra="allow", populate_by_name=True)


class ProjectSummary(_Tolerant):
    """Item of ``GET /v1/projects`` -> ``projects[]``."""

    id: str = Field(alias="_id")
    name: str = Field(alias="project_id", description="Project name, used in API paths")
    type: str | None = None
    status: str | None = None
    scale: int | None = None
    plan_id: str | None = Field(default=None, alias="planID")
    created_at: str | None = None
    is_deployed: bool | None = Field(default=None, alias="isDeployed")

    @field_validator("type", "status", mode="before")
    @classmethod
    def _stringify(cls, value: Any) -> Any:
        return str(value) if value is not None else None


class ProjectList(_Tolerant):
    projects: list[ProjectSummary] = Field(default_factory=list)


class ProjectDetails(_Tolerant):
    """``GET /v1/projects/{name}`` -> ``project``.

    Environment variable *values* are intentionally not stored: only key names
    are retained so that secrets returned by Liara never reach the UI or an LLM.
    """

    id: str | None = Field(default=None, alias="_id")
    name: str | None = Field(default=None, alias="project_id")
    type: str | None = None
    status: str | None = None
    scale: int | None = None
    plan_id: str | None = Field(default=None, alias="planID")
    is_deployed: bool | None = Field(default=None, alias="isDeployed")
    created_at: str | None = None
    hourly_price: float | None = Field(default=None, alias="hourlyPrice")
    env_keys: list[str] = Field(default_factory=list)
    zero_downtime: bool | None = Field(default=None, alias="zeroDowntime")
    read_only_root_filesystem: bool | None = Field(default=None, alias="readOnlyRootFilesystem")
    reserved_disk_space: int | None = Field(default=None, alias="reservedDiskSpace")

    @model_validator(mode="before")
    @classmethod
    def _extract_env_keys(cls, data: Any) -> Any:
        """Keep only environment variable *names*; values are dropped here."""
        if isinstance(data, dict):
            envs = data.get("envs")
            if isinstance(envs, list):
                keys = [e.get("key") for e in envs if isinstance(e, dict) and e.get("key")]
                data = {**data, "env_keys": keys, "envs": [{"key": key} for key in keys]}
        return data


class ProjectDetailsEnvelope(_Tolerant):
    project: ProjectDetails


class LogEntry(_Tolerant):
    """Item of ``GET /v1/projects/{name}/logs``."""

    type: str = "stdout"
    datetime: str | None = None
    message: str = ""

    @property
    def level(self) -> str:
        lowered = (self.message or "").lower()
        stream = (self.type or "").lower()
        if "critical" in lowered or "traceback" in lowered:
            return "critical"
        if "error" in lowered or "exception" in lowered or stream in {"stderr", "error"}:
            return "error"
        if "warn" in lowered:
            return "warning"
        return "info"

    @property
    def timestamp(self) -> datetime | None:
        return parse_iso(self.datetime)


class MetricPoint(_Tolerant):
    timestamp: float
    value: float


class MetricSeries(_Tolerant):
    """Normalised metric series parsed from ``Reports``/``summary`` payloads."""

    name: str
    applet: str | None = None
    unit: str = "%"
    points: list[MetricPoint] = Field(default_factory=list)
    unavailable_reason: str | None = None

    @property
    def count(self) -> int:
        return len(self.points)

    @property
    def last(self) -> float | None:
        return self.points[-1].value if self.points else None

    @property
    def average(self) -> float | None:
        return round(sum(p.value for p in self.points) / len(self.points), 2) if self.points else None

    @property
    def maximum(self) -> float | None:
        return round(max(p.value for p in self.points), 2) if self.points else None

    @property
    def minimum(self) -> float | None:
        return round(min(p.value for p in self.points), 2) if self.points else None

    @property
    def latest_timestamp(self) -> float | None:
        return self.points[-1].timestamp if self.points else None

    def as_summary(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "unit": self.unit,
            "count": self.count,
            "last": self.last,
            "average": self.average,
            "maximum": self.maximum,
            "minimum": self.minimum,
            "unavailable_reason": self.unavailable_reason,
            "applet": self.applet,
        }


class RawReports(_Tolerant):
    """``GET /v1/projects/{name}/metrics/{cpu|memory}`` response."""

    end: float | None = None
    result: list[dict[str, Any]] = Field(default_factory=list)


class ReleaseInfo(_Tolerant):
    id: str | None = Field(default=None, alias="_id")
    type: str | None = None
    image_name: str | None = Field(default=None, alias="imageName")
    project_type: str | None = Field(default=None, alias="projectType")
    state: str | None = None
    port: int | None = None
    created_at: str | None = Field(default=None, alias="createdAt")
    finished_at: str | None = Field(default=None, alias="finishedAt")
    tag: str | None = None
    source_available: bool | None = Field(default=None, alias="sourceAvailable")
    git_info: dict[str, Any] | None = Field(default=None, alias="gitInfo")

    @property
    def is_ready(self) -> bool:
        return (self.state or "").lower() in {"ready", "running", "success", "succeeded", "deployed"}


class ReleasePage(_Tolerant):
    """``GET /v1/projects/{name}/releases`` response."""

    total: int = 0
    current_release: str | None = Field(default=None, alias="currentRelease")
    ready_releases_count: int = Field(default=0, alias="readyReleasesCount")
    releases: list[ReleaseInfo] = Field(default_factory=list)
    platform: str | None = None


class SourceUploadResult(BaseModel):
    source_id: str = Field(alias="sourceID")


class ReleaseDeployResult(BaseModel):
    release_id: str = Field(alias="releaseID")


def parse_metric_reports(
    payload: dict[str, Any], *, name: str, unit: str = "%", since: float | None = None
) -> MetricSeries:
    """Convert a documented ``Reports`` payload into a normalised series.

    The documented shape is::

        {"end": 1700000000, "result": [{"applet": "...", "values": [[ts, "12.5"], ...]}]}

    Values may be numbers or numeric strings; malformed points are skipped
    instead of failing the whole report.
    """
    series = MetricSeries(name=name, unit=unit)
    result = payload.get("result")
    if not isinstance(result, list) or not result:
        series.unavailable_reason = "Liara returned an empty metrics series."
        return series
    points: list[MetricPoint] = []
    applet: str | None = None
    for block in result:
        if not isinstance(block, dict):
            continue
        applet = applet or block.get("applet")
        for raw in block.get("values") or []:
            if not isinstance(raw, (list, tuple)) or len(raw) < 2:
                continue
            ts, value = raw[0], raw[1]
            try:
                ts_f = float(ts)
                val_f = float(value)
            except (TypeError, ValueError):
                continue
            # ``since`` is sent to Liara, which already filters the window; re-filtering
            # locally would silently drop valid points when clocks differ.
            points.append(MetricPoint(timestamp=ts_f, value=val_f))
    points.sort(key=lambda p: p.timestamp)
    series.points = points
    series.applet = applet
    if not points:
        series.unavailable_reason = "Metrics response contained no usable data points."
    return series
