"""Shared FastAPI dependencies."""

from __future__ import annotations

from fastapi import Request

from app.services.container import AppContainer


def get_container(request: Request) -> AppContainer:
    container = getattr(request.app.state, "container", None)
    if container is None:  # pragma: no cover - app not initialised
        raise RuntimeError("Application container is not initialised.")
    return container
