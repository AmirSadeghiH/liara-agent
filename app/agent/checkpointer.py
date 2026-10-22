"""Durable LangGraph checkpointer (SQLite).

Using a file-backed saver means a workflow interrupted for human approval
survives a server restart: ``POST /api/workflows/{id}/resume`` rebuilds the graph
with the same ``thread_id`` and continues from the persisted checkpoint.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

logger = logging.getLogger(__name__)


@asynccontextmanager
async def open_checkpointer(path: Path) -> AsyncIterator[AsyncSqliteSaver]:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    async with AsyncSqliteSaver.from_conn_string(str(path)) as saver:
        await saver.setup()
        logger.info("LangGraph checkpointer ready", extra={"event_data": {"path": str(path)}})
        yield saver
