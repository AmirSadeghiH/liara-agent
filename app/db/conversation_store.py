"""Persistence for the conversational surface.

Kept separate from :mod:`app.db.repository` so the workflow repository stays
focused and the existing call sites (API, MCP, tests) are untouched.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select

from app.core.utils import iso
from app.db.database import Database
from app.db.models import Conversation, ConversationMessage


def message_dict(row: ConversationMessage) -> dict[str, Any]:
    return {
        "id": row.id,
        "conversation_id": row.conversation_id,
        "role": row.role,
        "text": row.text,
        "blocks": row.blocks or [],
        "workflow_id": row.workflow_id,
        "data": row.data or {},
        "created_at": row.created_at,
    }


def conversation_dict(row: Conversation, *, message_count: int | None = None) -> dict[str, Any]:
    payload = {
        "id": row.id,
        "title": row.title,
        "project": row.project,
        "last_intent": row.last_intent,
        "workflow_ids": list(row.workflow_ids or []),
        "demo_mode": row.demo_mode,
        "simulated": row.simulated,
        "created_at": row.created_at,
        "updated_at": row.updated_at,
    }
    if message_count is not None:
        payload["message_count"] = message_count
    return payload


class ConversationStore:
    def __init__(self, db: Database) -> None:
        self.db = db

    # ------------------------------------------------------------------
    # conversations
    # ------------------------------------------------------------------
    async def create(self, payload: dict[str, Any]) -> Conversation:
        now = iso()
        row = Conversation(created_at=now, updated_at=now, **payload)
        async with self.db.session() as session:
            session.add(row)
        return row

    async def get(self, conversation_id: str) -> Conversation | None:
        async with self.db.session() as session:
            return await session.get(Conversation, conversation_id)

    async def list(self, *, limit: int = 40) -> list[Conversation]:
        stmt = select(Conversation).order_by(Conversation.updated_at.desc()).limit(limit)
        async with self.db.session() as session:
            return list((await session.execute(stmt)).scalars().all())

    async def update(self, conversation_id: str, **fields: Any) -> Conversation | None:
        allowed = {"title", "project", "last_intent", "workflow_ids"}
        unknown = set(fields) - allowed
        if unknown:
            raise ValueError(f"Unknown conversation fields: {sorted(unknown)}")
        async with self.db.session() as session:
            row = await session.get(Conversation, conversation_id)
            if row is None:
                return None
            for key, value in fields.items():
                setattr(row, key, value)
            row.updated_at = iso()
            return row

    # ------------------------------------------------------------------
    # messages
    # ------------------------------------------------------------------
    async def add_message(
        self,
        conversation_id: str,
        *,
        role: str,
        text: str,
        blocks: list[dict[str, Any]] | None = None,
        workflow_id: str | None = None,
        client_message_id: str | None = None,
        data: dict[str, Any] | None = None,
    ) -> ConversationMessage:
        row = ConversationMessage(
            conversation_id=conversation_id,
            role=role,
            text=text,
            blocks=blocks or [],
            workflow_id=workflow_id,
            client_message_id=client_message_id,
            data=data or {},
            created_at=iso(),
        )
        async with self.db.session() as session:
            session.add(row)
            await session.flush()
            session.expunge(row)
        return row

    async def list_messages(
        self, conversation_id: str, *, limit: int = 400
    ) -> list[ConversationMessage]:
        stmt = (
            select(ConversationMessage)
            .where(ConversationMessage.conversation_id == conversation_id)
            .order_by(ConversationMessage.id.asc())
            .limit(limit)
        )
        async with self.db.session() as session:
            return list((await session.execute(stmt)).scalars().all())

    async def find_by_client_id(
        self, conversation_id: str, client_message_id: str
    ) -> ConversationMessage | None:
        stmt = (
            select(ConversationMessage)
            .where(
                ConversationMessage.conversation_id == conversation_id,
                ConversationMessage.client_message_id == client_message_id,
            )
            .limit(1)
        )
        async with self.db.session() as session:
            return (await session.execute(stmt)).scalar_one_or_none()

    async def assistant_reply_after(
        self, conversation_id: str, message_id: int
    ) -> ConversationMessage | None:
        stmt = (
            select(ConversationMessage)
            .where(
                ConversationMessage.conversation_id == conversation_id,
                ConversationMessage.id > message_id,
                ConversationMessage.role == "assistant",
            )
            .order_by(ConversationMessage.id.asc())
            .limit(1)
        )
        async with self.db.session() as session:
            return (await session.execute(stmt)).scalar_one_or_none()
