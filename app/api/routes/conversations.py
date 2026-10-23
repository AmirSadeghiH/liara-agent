"""Conversational API: the primary product surface.

The chat owns no business logic of its own; it delegates to
:class:`app.services.conversation_service.ConversationService`, which in turn uses
the existing diagnosis, workflow, approval and coding services.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Request, status

from app.api.deps import get_container
from app.api.schemas import (
    ConversationCreateRequest,
    ConversationDecisionRequest,
    ConversationMessageRequest,
    SelectProjectRequest,
)
from app.core.security import require_app_auth

router = APIRouter(prefix="/api/conversations", tags=["conversations"],
                   dependencies=[Depends(require_app_auth)])


@router.get("", summary="List conversations (most recent first)")
async def list_conversations(request: Request) -> dict[str, Any]:
    container = get_container(request)
    rows = await container.conversations.list()
    return {
        "count": len(rows),
        "conversations": rows,
        "mode": "demo" if container.settings.demo_mode else "live",
        "simulated": container.adapter.simulated,
    }


@router.post("", status_code=status.HTTP_201_CREATED, summary="Start a new conversation")
async def create_conversation(
    payload: ConversationCreateRequest, request: Request
) -> dict[str, Any]:
    container = get_container(request)
    row = await container.conversations.create(title=payload.title)
    from app.db.conversation_store import conversation_dict

    return {
        "conversation": conversation_dict(row),
        "mode": "demo" if container.settings.demo_mode else "live",
        "simulated": container.adapter.simulated,
    }


@router.get("/{conversation_id}", summary="Conversation with persisted messages and UI blocks")
async def get_conversation(conversation_id: str, request: Request) -> dict[str, Any]:
    container = get_container(request)
    return await container.conversations.detail(conversation_id)


@router.post("/{conversation_id}/messages", summary="Send a message and receive the result")
async def post_message(
    conversation_id: str, payload: ConversationMessageRequest, request: Request
) -> dict[str, Any]:
    container = get_container(request)
    return await container.conversations.post_message(
        conversation_id,
        text=payload.text,
        client_message_id=payload.client_message_id,
    )


@router.get("/{conversation_id}/live", summary="Current workflow blocks for this conversation")
async def live_state(conversation_id: str, request: Request) -> dict[str, Any]:
    container = get_container(request)
    return await container.conversations.live(conversation_id)


@router.post("/{conversation_id}/select-project", summary="Set the active project of a conversation")
async def select_project(
    conversation_id: str, payload: SelectProjectRequest, request: Request
) -> dict[str, Any]:
    container = get_container(request)
    return await container.conversations.select_project(conversation_id, project=payload.project)


@router.post(
    "/{conversation_id}/approvals/{approval_id}/approve",
    summary="Approve a server-side approval from inside the chat",
)
async def approve(
    conversation_id: str, approval_id: str, payload: ConversationDecisionRequest,
    request: Request,
) -> dict[str, Any]:
    container = get_container(request)
    return await container.conversations.decide(
        conversation_id, approval_id, decision="approved",
        actor=payload.actor, note=payload.note,
    )


@router.post(
    "/{conversation_id}/approvals/{approval_id}/reject",
    summary="Reject a server-side approval from inside the chat",
)
async def reject(
    conversation_id: str, approval_id: str, payload: ConversationDecisionRequest,
    request: Request,
) -> dict[str, Any]:
    container = get_container(request)
    return await container.conversations.decide(
        conversation_id, approval_id, decision="rejected",
        actor=payload.actor, note=payload.note,
    )


@router.post(
    "/{conversation_id}/workflows/{workflow_id}/cancel",
    summary="Cancel a linked workflow when the backend allows it",
)
async def cancel_workflow(
    conversation_id: str, workflow_id: str, request: Request
) -> dict[str, Any]:
    container = get_container(request)
    return await container.conversations.cancel_workflow(conversation_id, workflow_id)
