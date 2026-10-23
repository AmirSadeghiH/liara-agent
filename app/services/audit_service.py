"""Append-only audit trail (SQLite + JSONL).

Audit records never contain secrets: every payload is passed through the
redactor before it is persisted or written to disk.
"""

from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path
from typing import Any

from app.core.logging import redact_value
from app.core.utils import iso, new_id
from app.db.repository import Repository

logger = logging.getLogger(__name__)


class AuditService:
    def __init__(self, repo: Repository, audit_path: Path, *, enabled: bool = True) -> None:
        self.repo = repo
        self.audit_path = Path(audit_path)
        self.enabled = enabled
        self._lock = asyncio.Lock()

    async def record(
        self,
        action: str,
        *,
        actor: str = "system",
        target: str | None = None,
        outcome: str = "ok",
        detail: dict[str, Any] | None = None,
        trace_id: str | None = None,
    ) -> None:
        if not self.enabled:
            return
        safe_detail = redact_value(detail or {})
        event = {
            "id": new_id("aud"),
            "at": iso(),
            "actor": actor,
            "action": action,
            "target": target,
            "outcome": outcome,
            "trace_id": trace_id,
            "detail": safe_detail,
        }
        try:
            await self.repo.add_audit(event)
        except Exception:  # pragma: no cover - auditing must not break the request
            logger.exception("failed to persist audit event")
        await self._append_jsonl(event)

    async def _append_jsonl(self, event: dict[str, Any]) -> None:
        async with self._lock:
            try:
                self.audit_path.parent.mkdir(parents=True, exist_ok=True)
                line = json.dumps(event, ensure_ascii=False, default=str)
                await asyncio.to_thread(self._write_line, line)
            except Exception:  # pragma: no cover
                logger.exception("failed to append audit jsonl")

    def _write_line(self, line: str) -> None:
        with self.audit_path.open("a", encoding="utf-8") as handle:
            handle.write(line + "\n")

    async def liara_hook(self, record: dict[str, Any]) -> None:
        """Audit hook passed to :class:`LiaraClient` (no headers, no token)."""
        await self.record(
            "liara.request",
            actor="liara-client",
            target=record.get("endpoint"),
            outcome=str(record.get("outcome", "unknown")),
            detail={
                k: v for k, v in record.items()
                if k in {"method", "path", "status_code", "duration_ms", "attempt", "error_code"}
            },
        )
