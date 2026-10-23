"""Validate the LiaraPilot configuration without exposing secrets.

Exit code 0 means the configuration is structurally valid and the app can start.
Exit code 1 means a readable configuration error was printed (and nothing else).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.core.config import ConfigError, load_settings  # noqa: E402


def main() -> int:
    try:
        settings = load_settings()
    except ConfigError as exc:
        print("[config] INVALID", file=sys.stderr)
        print(str(exc), file=sys.stderr)
        return 1

    readiness = settings.live_readiness()
    summary = {
        "app": settings.app_name,
        "env": settings.app_env,
        "demo_mode": settings.demo_mode,
        "demo_scenario": settings.demo_scenario,
        "database": settings.database_url.split("///")[-1],
        "checkpoints": str(settings.checkpoint_file),
        "audit_log": str(settings.audit_path),
        "llm_provider": settings.llm_provider,
        "coding_agent": settings.coding_agent_provider,
        "host": settings.app_host,
        "port": settings.app_port,
        "live_ready": readiness["live_ready"],
        "blockers": readiness["blockers"],
        "warnings": readiness["warnings"],
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))

    try:
        settings.ensure_directories()
    except OSError as exc:
        print(f"[config] cannot create data directories: {exc}", file=sys.stderr)
        return 1

    if settings.demo_mode:
        print("[config] OK - Demo mode is ready (no token or LLM required).")
    elif readiness["live_ready"]:
        print("[config] OK - Live mode prerequisites are satisfied.")
    else:
        print("[config] OK to start, but Live mode is not ready:", file=sys.stderr)
        for blocker in readiness["blockers"]:
            print(f"  - {blocker}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
