"""Structured logging with unconditional secret redaction."""

from __future__ import annotations

import json
import logging
import re
import sys
from datetime import UTC, datetime
from typing import Any

_SECRETS: set[str] = set()

_TOKEN_PATTERNS = [
    re.compile(r"(?i)\b(authorization)\s*:\s*[^\s,;]+"),
    re.compile(r"(?i)\b(bearer)\s+[A-Za-z0-9._\-]{8,}"),
    re.compile(r"(?i)\b(api[_-]?key|token|secret|password|passwd|access[_-]?token)\b\s*[=:]\s*[\"']?([^\s\"',;}{]{4,})"),
    re.compile(r"liara[_\-][A-Za-z0-9_\-]{10,}"),
    re.compile(r"sk-[A-Za-z0-9]{16,}"),
]

MASK = "***REDACTED***"


def register_secret(value: str | None) -> None:
    """Register a literal secret so it is masked wherever it appears."""
    if value and len(value) >= 4:
        _SECRETS.add(value)


def clear_registered_secrets() -> None:
    _SECRETS.clear()


def redact_text(text: str, max_length: int | None = None) -> str:
    """Mask known secrets and token-shaped strings inside free text."""
    if not text:
        return text
    result = str(text)
    for secret in sorted(_SECRETS, key=len, reverse=True):
        if secret and secret in result:
            result = result.replace(secret, MASK)
    # Authorization header / bearer tokens
    result = _TOKEN_PATTERNS[0].sub(r"\1: " + MASK, result)
    result = _TOKEN_PATTERNS[1].sub(r"\1 " + MASK, result)
    result = _TOKEN_PATTERNS[2].sub(lambda m: f"{m.group(1)}={MASK}", result)
    result = _TOKEN_PATTERNS[3].sub(MASK, result)
    result = _TOKEN_PATTERNS[4].sub(MASK, result)
    if max_length is not None and len(result) > max_length:
        result = result[: max_length - 1] + "…"
    return result


def redact_value(value: Any) -> Any:
    """Recursively redact strings inside common container types."""
    if isinstance(value, str):
        return redact_text(value)
    if isinstance(value, dict):
        return {redact_text(str(k)): redact_value(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [redact_value(item) for item in value]
    return value


class RedactionFilter(logging.Filter):
    """Logging filter that redacts records before they reach a handler."""

    def filter(self, record: logging.LogRecord) -> bool:  # noqa: A003 - logging API
        try:
            if isinstance(record.msg, str):
                record.msg = redact_text(record.msg)
            if record.args:
                record.args = tuple(redact_value(a) for a in record.args)  # type: ignore[assignment]
        except Exception:  # pragma: no cover - logging must never raise
            record.msg = MASK
            record.args = ()
        return True


class JsonFormatter(logging.Formatter):
    """Minimal JSON log formatter (one object per line)."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": datetime.now(UTC).isoformat(timespec="milliseconds"),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        extra = getattr(record, "event_data", None)
        if isinstance(extra, dict):
            payload.update(redact_value(extra))
        if record.exc_info:
            payload["exception"] = redact_text(self.formatException(record.exc_info))
        return json.dumps(payload, ensure_ascii=False)


def configure_logging(level: str = "INFO", *, stream=None, json_output: bool = True) -> None:
    """Configure root logging for the web app and the MCP stdio server.

    The stdio MCP transport owns stdout, therefore every log handler must write
    to stderr.  We always install a stderr handler here.
    """
    target = stream if stream is not None else sys.stderr
    root = logging.getLogger()
    for handler in list(root.handlers):
        root.removeHandler(handler)
    handler = logging.StreamHandler(target)
    handler.addFilter(RedactionFilter())
    if json_output:
        handler.setFormatter(JsonFormatter())
    else:
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s"))
    root.addHandler(handler)
    root.setLevel(level.upper())

    # httpx logs request URLs at INFO level; keep them but ensure no headers leak.
    logging.getLogger("httpx").setLevel(max(logging.WARNING, root.level))
    logging.getLogger("httpcore").setLevel(max(logging.WARNING, root.level))
    logging.getLogger("aiosqlite").setLevel(logging.WARNING)


def log_event(logger: logging.Logger, level: int, message: str, **fields: Any) -> None:
    """Emit a structured, redacted log line."""
    logger.log(level, message, extra={"event_data": redact_value(fields)})
