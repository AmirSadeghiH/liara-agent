"""Pydantic request/response schemas for the internal API."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator


class WorkflowCreateRequest(BaseModel):
    project: str | None = Field(default=None, max_length=80)
    request: str = Field(min_length=3, max_length=4000)
    max_attempts: int | None = Field(default=None, ge=1, le=3)

    @field_validator("request")
    @classmethod
    def _strip(cls, value: str) -> str:
        return value.strip()


class DiagnosisRequest(BaseModel):
    project: str = Field(min_length=1, max_length=80)
    request: str = Field(default="علت خطا را بررسی کن.", max_length=4000)


class ResumeRequest(BaseModel):
    approval_id: str | None = None
    wait: bool = False


class ApprovalDecisionRequest(BaseModel):
    actor: str = Field(default="ui", max_length=64)
    note: str | None = Field(default=None, max_length=500)


class DemoRunRequest(BaseModel):
    scenario: str | None = None
    project: str | None = None
    request: str | None = Field(default=None, max_length=4000)


class ErrorBody(BaseModel):
    code: str
    message: str
    details: dict[str, Any] = Field(default_factory=dict)


class ErrorResponse(BaseModel):
    error: ErrorBody


class ProjectOut(BaseModel):
    id: str
    name: str
    type: str | None = None
    status: str | None = None
    scale: int | None = None
    plan_id: str | None = None
    is_deployed: bool | None = None
    created_at: str | None = None


class ProjectListResponse(BaseModel):
    mode: Literal["demo", "live"]
    simulated: bool
    notice: str | None = None
    projects: list[ProjectOut]


class WorkflowAccepted(BaseModel):
    workflow_id: str
    thread_id: str
    project: str | None
    status: str
    current_step: str | None
    simulated: bool
    demo_mode: bool
    created_at: str


class ConversationCreateRequest(BaseModel):
    title: str | None = Field(default=None, max_length=160)


class ConversationMessageRequest(BaseModel):
    text: str = Field(min_length=1, max_length=4000)
    client_message_id: str | None = Field(
        default=None, max_length=64, pattern=r"^[A-Za-z0-9_.:-]+$"
    )

    @field_validator("text")
    @classmethod
    def _strip_text(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("text must not be empty")
        return stripped


class SelectProjectRequest(BaseModel):
    project: str = Field(min_length=1, max_length=80)


class ConversationDecisionRequest(BaseModel):
    note: str | None = Field(default=None, max_length=500)
    actor: str = Field(default="chat", max_length=64)
