"""Demo Mode orchestration: scenarios and one-click incident runs."""

from __future__ import annotations

from typing import Any

from app.core.config import Settings
from app.core.errors import PolicyViolation, ValidationError
from app.liara.mock_adapter import SCENARIO_LABELS_FA, SCENARIOS, MockLiaraAdapter
from app.services.workflow_service import WorkflowRunner

DEFAULT_REQUESTS = {
    "django_500": (
        "سایت فروشگاهی من روی لیارا خطای 500 می‌دهد. لاگ‌ها را بررسی کن، "
        "بگو مشکل از CPU یا RAM است یا نه و علت احتمالی را با شواهد توضیح بده."
    ),
    "memory_pressure": (
        "سرویس API من مکرراً قطع می‌شود و خطای 502 می‌دهد. بررسی کن مشکل از حافظه است یا نه."
    ),
    "healthy_site": "وضعیت سایت من را بررسی کن و بگو آیا مشکلی وجود دارد.",
}


class DemoService:
    def __init__(self, settings: Settings, adapter: Any, runner: WorkflowRunner) -> None:
        self.settings = settings
        self.adapter = adapter
        self.runner = runner

    @property
    def is_demo(self) -> bool:
        return self.settings.demo_mode and isinstance(self.adapter, MockLiaraAdapter)

    def scenarios(self) -> list[dict[str, Any]]:
        current = getattr(self.adapter, "scenario", None)
        return [
            {
                "key": key,
                "label_fa": SCENARIO_LABELS_FA.get(key, key),
                "title_fa": scenario.title_fa,
                "summary_fa": scenario.summary_fa,
                "project": scenario.project,
                "has_incident": scenario.has_incident,
                "active": bool(current and current.key == key),
                "simulated": True,
            }
            for key, scenario in SCENARIOS.items()
        ]

    async def run(
        self,
        *,
        scenario: str | None = None,
        project: str | None = None,
        request_text: str | None = None,
        actor: str = "demo",
    ) -> dict[str, Any]:
        if not self.settings.demo_mode:
            raise PolicyViolation(
                "Demo scenarios are only available while DEMO_MODE=true.",
                details={"reason": "live_mode"},
            )
        if not isinstance(self.adapter, MockLiaraAdapter):
            raise PolicyViolation("The active Liara adapter is not the demo adapter.")
        key = (scenario or self.settings.demo_scenario or "django_500").strip()
        if key not in SCENARIOS:
            raise ValidationError(
                "Unknown demo scenario.", details={"scenario": key, "available": list(SCENARIOS)}
            )
        active = self.adapter.use_scenario(key)
        target_project = project or active.project
        text = (request_text or DEFAULT_REQUESTS.get(key) or DEFAULT_REQUESTS["django_500"]).strip()
        started = await self.runner.start(
            request_text=text, project=target_project, actor=actor,
        )
        return {
            **started,
            "scenario": {
                "key": key,
                "title_fa": active.title_fa,
                "summary_fa": active.summary_fa,
                "project": target_project,
                "simulated": True,
            },
        }
