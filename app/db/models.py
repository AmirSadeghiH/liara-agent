"""SQL persistence models.

SQLite is used for the MVP, but the models avoid SQLite-specific types so a
PostgreSQL migration only requires changing ``DATABASE_URL`` and the driver.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import JSON, Boolean, Integer, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class TimestampMixin:
    created_at: Mapped[str] = mapped_column(String(40), nullable=False)
    updated_at: Mapped[str] = mapped_column(String(40), nullable=False)


class WorkflowRun(Base, TimestampMixin):
    __tablename__ = "workflow_runs"

    id: Mapped[str] = mapped_column(String(48), primary_key=True)
    thread_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    project: Mapped[str | None] = mapped_column(String(80), nullable=True, index=True)
    request_text: Mapped[str] = mapped_column(Text, nullable=False, default="")
    status: Mapped[str] = mapped_column(String(32), nullable=False, index=True, default="queued")
    current_step: Mapped[str | None] = mapped_column(String(64), nullable=True)
    risk_level: Mapped[str | None] = mapped_column(String(16), nullable=True)
    demo_mode: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    simulated: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    attempt: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=3)
    diagnosis: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    repair_plan: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    test_results: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    deployment: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    verification: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    final_report: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    workspace: Mapped[str | None] = mapped_column(Text, nullable=True)
    branch: Mapped[str | None] = mapped_column(String(120), nullable=True)
    pending_approval_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    stop_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    completed_at: Mapped[str | None] = mapped_column(String(40), nullable=True)
    created_by: Mapped[str] = mapped_column(String(64), nullable=False, default="ui")


class WorkflowEvent(Base):
    __tablename__ = "workflow_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    workflow_id: Mapped[str] = mapped_column(String(48), nullable=False, index=True)
    step: Mapped[str | None] = mapped_column(String(64), nullable=True)
    step_key: Mapped[str | None] = mapped_column(String(120), nullable=True, index=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="running")
    message: Mapped[str | None] = mapped_column(Text, nullable=True)
    data: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[str] = mapped_column(String(40), nullable=False)


class EvidenceRecord(Base):
    __tablename__ = "evidence_records"

    id: Mapped[str] = mapped_column(String(48), primary_key=True)
    workflow_id: Mapped[str] = mapped_column(String(48), nullable=False, index=True)
    project: Mapped[str | None] = mapped_column(String(80), nullable=True)
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    source: Mapped[str] = mapped_column(String(160), nullable=False)
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    payload: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    redacted: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    simulated: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    observed_at: Mapped[str] = mapped_column(String(40), nullable=False)
    created_at: Mapped[str] = mapped_column(String(40), nullable=False)


class ApprovalRequest(Base):
    __tablename__ = "approval_requests"

    id: Mapped[str] = mapped_column(String(96), primary_key=True)
    workflow_id: Mapped[str] = mapped_column(String(48), nullable=False, index=True)
    project: Mapped[str | None] = mapped_column(String(80), nullable=True)
    action: Mapped[str] = mapped_column(String(64), nullable=False)
    stage: Mapped[str] = mapped_column(String(32), nullable=False, default="repair")
    risk_level: Mapped[str] = mapped_column(String(16), nullable=False, default="medium")
    title: Mapped[str] = mapped_column(Text, nullable=False, default="")
    reason: Mapped[str] = mapped_column(Text, nullable=False, default="")
    params: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="pending", index=True)
    requested_at: Mapped[str] = mapped_column(String(40), nullable=False)
    expires_at: Mapped[str] = mapped_column(String(40), nullable=False)
    decided_at: Mapped[str | None] = mapped_column(String(40), nullable=True)
    decided_by: Mapped[str | None] = mapped_column(String(64), nullable=True)
    decision_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    consumed_at: Mapped[str | None] = mapped_column(String(40), nullable=True)
    simulated: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)


class DeploymentRecord(Base):
    __tablename__ = "deployment_records"

    id: Mapped[str] = mapped_column(String(48), primary_key=True)
    workflow_id: Mapped[str] = mapped_column(String(48), nullable=False, index=True)
    project: Mapped[str] = mapped_column(String(80), nullable=False)
    stage: Mapped[str] = mapped_column(String(32), nullable=False, default="prepared")
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending")
    source_id: Mapped[str | None] = mapped_column(String(120), nullable=True)
    release_id: Mapped[str | None] = mapped_column(String(120), nullable=True)
    port: Mapped[int | None] = mapped_column(Integer, nullable=True)
    project_type: Mapped[str | None] = mapped_column(String(64), nullable=True)
    simulated: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    approval_id: Mapped[str | None] = mapped_column(String(96), nullable=True)
    params: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    detail: Mapped[str | None] = mapped_column(Text, nullable=True)
    package: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[str] = mapped_column(String(40), nullable=False)
    updated_at: Mapped[str] = mapped_column(String(40), nullable=False)


class CodingAgentRun(Base):
    __tablename__ = "coding_agent_runs"

    id: Mapped[str] = mapped_column(String(48), primary_key=True)
    workflow_id: Mapped[str] = mapped_column(String(48), nullable=False, index=True)
    provider: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="running")
    simulated: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    prompt_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    workspace: Mapped[str | None] = mapped_column(Text, nullable=True)
    branch: Mapped[str | None] = mapped_column(String(120), nullable=True)
    exit_code: Mapped[int | None] = mapped_column(Integer, nullable=True)
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    files_changed: Mapped[list[Any] | None] = mapped_column(JSON, nullable=True)
    diff: Mapped[str | None] = mapped_column(Text, nullable=True)
    test_results: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[str] = mapped_column(String(40), nullable=False)
    updated_at: Mapped[str] = mapped_column(String(40), nullable=False)


class AuditEvent(Base):
    __tablename__ = "audit_events"

    id: Mapped[str] = mapped_column(String(48), primary_key=True)
    at: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    actor: Mapped[str] = mapped_column(String(64), nullable=False, default="system")
    action: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    target: Mapped[str | None] = mapped_column(String(160), nullable=True)
    outcome: Mapped[str] = mapped_column(String(32), nullable=False, default="ok")
    trace_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    detail: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)


class Conversation(Base, TimestampMixin):
    """A persistent chat thread (the primary product surface)."""

    __tablename__ = "conversations"

    id: Mapped[str] = mapped_column(String(48), primary_key=True)
    title: Mapped[str] = mapped_column(String(160), nullable=False, default="گفت‌وگوی جدید")
    project: Mapped[str | None] = mapped_column(String(80), nullable=True, index=True)
    last_intent: Mapped[str | None] = mapped_column(String(32), nullable=True)
    workflow_ids: Mapped[list[str] | None] = mapped_column(JSON, nullable=True)
    demo_mode: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    simulated: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_by: Mapped[str] = mapped_column(String(64), nullable=False, default="ui")


class ConversationMessage(Base):
    """One chat message.  ``blocks`` holds validated Generative-UI blocks."""

    __tablename__ = "conversation_messages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    conversation_id: Mapped[str] = mapped_column(String(48), nullable=False, index=True)
    role: Mapped[str] = mapped_column(String(16), nullable=False, default="assistant")
    text: Mapped[str] = mapped_column(Text, nullable=False, default="")
    blocks: Mapped[list[dict[str, Any]] | None] = mapped_column(JSON, nullable=True)
    workflow_id: Mapped[str | None] = mapped_column(String(48), nullable=True, index=True)
    client_message_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    data: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[str] = mapped_column(String(40), nullable=False)
