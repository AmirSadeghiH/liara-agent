"""Conversation orchestration for the single-chat product surface.

This service is the conversation router: it interprets the user's message using
the persisted conversation context, calls the *existing* diagnosis / workflow /
approval services (never a second HTTP hop), and decides which registered
Generative-UI blocks describe the real result.

Security boundaries:

* the router can only select from ``ui_blocks.BLOCK_REGISTRY``,
* an approval button only works for an approval that the server considers
  pending and that belongs to a workflow linked to this conversation,
* read-only questions never start a mutating workflow,
* the LLM (when enabled) can refine the diagnosis prose; it never authorises an
  action, changes Demo/Live mode or invents evidence.
"""

from __future__ import annotations

import logging
from datetime import timedelta
from typing import Any

from app.api.serializers import approval_dict, evidence_dict, workflow_detail
from app.core.errors import ConflictError, NotFoundError, ValidationError
from app.core.security import validate_project_name
from app.core.utils import iso, new_id, utcnow
from app.db.conversation_store import (
    ConversationStore,
    conversation_dict,
    message_dict,
)
from app.db.models import Conversation
from app.db.repository import TERMINAL_STATUSES, Repository
from app.services.approval_service import ApprovalService
from app.services.audit_service import AuditService
from app.services.coding_agent_service import CodingAgentService
from app.services.diagnosis_service import DiagnosisService, sanitize_log_message
from app.services import ui_blocks
from app.services.workflow_service import WorkflowRunner

logger = logging.getLogger(__name__)

ACTIVE_STATUSES = {"queued", "running", "testing", "deploying", "verifying", "waiting_for_approval"}

FA_DIGITS = str.maketrans("0123456789", "۰۱۲۳۴۵۶۷۸۹")


def fa_number(value: Any) -> str:
    return str(value).translate(FA_DIGITS)


def _normalise(text: str) -> str:
    return (
        (text or "")
        .replace("ي", "ی")
        .replace("ك", "ک")
        .replace("\u200c", " ")
        .lower()
    )


INTENT_KEYWORDS: list[tuple[str, tuple[str, ...]]] = [
    ("deploy", ("منتشر", "انتشار", "دیپلوی", "deploy", "release", "publish")),
    ("repair", ("درستش کن", "درست کن", "اصلاح", "رفع", "تعمیر", "fix", "repair", "کد رو", "کد را")),
    ("metrics", ("cpu", "ram", "حافظه", "مصرف منابع", "منابع", "متریک", "metrics", "memory")),
    ("logs", ("لاگ", "log", "logs", "خطاهای سرور")),
    ("report", ("گزارش", "report", "خلاصه", "جمع بندی", "جمع‌بندی")),
    ("metrics", ("سی پی یو", "سی‌پی‌یو")),
    # "وضعیت سایت را بررسی کن" is a status question, while "بررسی کن مشکل کجاست"
    # is a diagnosis request.  Status therefore wins before the broad "بررسی".
    ("status", ("وضعیت", "سلامت", "health", "status", "اوکی", "ok")),
    ("diagnose", ("۵۰۰", "500", "خطا", "مشکل", "چرا", "عیب", "تشخیص", "diagnose", "error", "بررسی")),
]

MODE_NOTICE_DEMO = (
    "این پاسخ در حالت DEMO ساخته شده است؛ داده‌ها شبیه‌سازی‌شده‌اند و هیچ تغییری در لیارا ثبت نمی‌شود."
)


class ConversationService:
    def __init__(
        self,
        *,
        store: ConversationStore,
        repo: Repository,
        adapter: Any,
        diagnosis: DiagnosisService,
        approvals: ApprovalService,
        runner: WorkflowRunner,
        coding: CodingAgentService,
        audit: AuditService,
        settings: Any,
    ) -> None:
        self.store = store
        self.repo = repo
        self.adapter = adapter
        self.diagnosis = diagnosis
        self.approvals = approvals
        self.runner = runner
        self.coding = coding
        self.audit = audit
        self.settings = settings

    # ------------------------------------------------------------------
    # conversations
    # ------------------------------------------------------------------
    async def create(self, *, title: str | None = None, actor: str = "ui") -> Conversation:
        return await self.store.create({
            "id": new_id("conv"),
            "title": (title or "گفت‌وگوی جدید")[:160],
            "project": None,
            "demo_mode": self.settings.demo_mode,
            "simulated": bool(self.adapter.simulated),
            "workflow_ids": [],
            "created_by": actor,
        })

    async def list(self) -> list[dict[str, Any]]:
        rows = await self.store.list()
        return [conversation_dict(row) for row in rows]

    async def _load(self, conversation_id: str) -> Conversation:
        row = await self.store.get(conversation_id)
        if row is None:
            raise NotFoundError("گفت‌وگو پیدا نشد.", details={"conversation_id": conversation_id})
        return row

    async def detail(self, conversation_id: str) -> dict[str, Any]:
        row = await self._load(conversation_id)
        messages = await self.store.list_messages(conversation_id)
        return {
            "conversation": conversation_dict(row, message_count=len(messages)),
            "messages": [message_dict(item) for item in messages],
            "mode": "demo" if self.settings.demo_mode else "live",
            "simulated": bool(self.adapter.simulated),
            "server_time": iso(),
        }

    # ------------------------------------------------------------------
    # planning helpers
    # ------------------------------------------------------------------
    async def _projects(self) -> list[dict[str, Any]]:
        try:
            rows = await self.adapter.list_projects()
        except Exception:
            logger.warning("could not list projects", exc_info=True)
            return []
        return [
            {
                "id": item.id,
                "name": item.name,
                "type": item.type,
                "status": item.status,
                "is_deployed": item.is_deployed,
                "plan_id": item.plan_id,
            }
            for item in rows
        ]

    @staticmethod
    def detect_intent(text: str) -> str:
        normalised = _normalise(text)
        for intent, keywords in INTENT_KEYWORDS:
            if any(keyword in normalised for keyword in keywords):
                return intent
        return "status"

    @staticmethod
    def _mention(text: str, projects: list[dict[str, Any]]) -> str | None:
        normalised = _normalise(text)
        matches = [p["name"] for p in projects if _normalise(p["name"]) in normalised]
        if not matches:
            return None
        matches.sort(key=len, reverse=True)
        return matches[0]

    async def _resolve_project(
        self, text: str, conversation: Conversation, projects: list[dict[str, Any]]
    ) -> tuple[str | None, bool]:
        """Return ``(project, needs_picker)`` without guessing a project."""
        names = [p["name"] for p in projects]
        explicit = self._mention(text, projects)
        if explicit:
            return explicit, False
        if conversation.project and conversation.project in names:
            return conversation.project, False
        if conversation.project and conversation.project not in names:
            # Context is stale: never silently keep a project the account lost.
            return None, len(names) > 1
        if len(names) == 1:
            return names[0], False
        if not names:
            return None, False
        return None, True

    async def _workflow_detail(self, workflow_id: str) -> dict[str, Any] | None:
        row = await self.repo.get_workflow(workflow_id)
        if row is None:
            return None
        events = await self.repo.list_events(workflow_id)
        evidence = await self.repo.list_evidence(workflow_id)
        approvals = await self.repo.list_approvals(workflow_id=workflow_id, limit=50)
        agent_runs = await self.repo.list_agent_runs(workflow_id)
        deployments = await self.repo.list_deployments(workflow_id=workflow_id, limit=20)
        detail = workflow_detail(
            row, events=events, evidence=evidence, approvals=approvals,
            agent_runs=agent_runs, deployments=deployments,
        )
        runs = detail.get("coding_agent_runs") or []
        if runs:
            detail["_review"] = self.coding.review_changes(
                list(runs[-1].get("files_changed") or [])
            )
        return detail

    def _blocks_for(self, detail: dict[str, Any]) -> list[dict[str, Any]]:
        return ui_blocks.workflow_blocks(detail, review=detail.get("_review"))

    # ------------------------------------------------------------------
    # message handling
    # ------------------------------------------------------------------
    async def post_message(
        self,
        conversation_id: str,
        *,
        text: str,
        client_message_id: str | None = None,
        actor: str = "chat",
    ) -> dict[str, Any]:
        conversation = await self._load(conversation_id)
        clean = text.strip()
        if len(clean) < 1:
            raise ValidationError("متن پیام خالی است.")

        # Idempotency: a double click must not start two workflows.
        if client_message_id:
            existing = await self.store.find_by_client_id(conversation_id, client_message_id)
            if existing is not None:
                reply = await self.store.assistant_reply_after(conversation_id, existing.id)
                return {
                    "conversation": conversation_dict(conversation),
                    "user_message": message_dict(existing),
                    "assistant_message": message_dict(reply) if reply else None,
                    "deduplicated": True,
                }

        user_message = await self.store.add_message(
            conversation_id, role="user", text=clean,
            client_message_id=client_message_id,
        )
        if (conversation.title or "") in {"", "گفت‌وگوی جدید"}:
            conversation = await self.store.update(
                conversation_id, title=clean[:60]
            ) or conversation
        projects = await self._projects()
        intent = self.detect_intent(clean)
        project, needs_picker = await self._resolve_project(clean, conversation, projects)
        mode = "demo" if self.settings.demo_mode else "live"
        simulated = bool(self.adapter.simulated)

        if not projects:
            reply_text = (
                "هیچ پروژه‌ای در دسترس نیست. اتصال لیارا را در تنظیمات بررسی کنید؛ "
                "تا آن زمان هیچ عملیاتی اجرا نمی‌شود."
            )
            assistant = await self.store.add_message(
                conversation_id, role="assistant", text=reply_text,
                blocks=ui_blocks.validate_blocks([])[0],
                data={"intent": intent, "mode": mode},
            )
            await self.store.update(conversation_id, last_intent=intent)
            return self._pair(conversation, user_message, assistant)

        if needs_picker:
            blocks = [ui_blocks.project_picker_block(
                projects,
                reason="برای این درخواست، پروژه هدف مشخص نیست. یک پروژه انتخاب کنید تا ادامه دهم.",
            )]
            assistant = await self.store.add_message(
                conversation_id, role="assistant",
                text=(
                    "برای اینکه بررسی را روی پروژه درست انجام دهم، پروژه هدف را انتخاب کنید. "
                    "پس از انتخاب، درخواست قبلی را دوباره نمی‌پرسیم."
                ),
                blocks=blocks,
                # The request is kept so selecting a project continues it; the
                # user never has to retype the question.
                data={
                    "intent": intent, "mode": mode, "needs_project": True,
                    "pending_request": clean[:2000],
                },
            )
            await self.store.update(conversation_id, last_intent=intent)
            return self._pair(conversation, user_message, assistant)

        # At this point a project is known (single project or explicit mention).
        assert project is not None
        if conversation.project != project:
            conversation = await self.store.update(conversation_id, project=project) or conversation

        result = await self._run_intent(
            conversation=conversation, project=project, text=clean,
            intent=intent, actor=actor,
        )

        await self._audit(
            conversation_id, intent, project, result.get("workflow_id")
        )
        assistant = await self.store.add_message(
            conversation_id,
            role="assistant",
            text=result["text"],
            blocks=result["blocks"],
            workflow_id=result.get("workflow_id"),
            data={
                "intent": intent,
                "mode": mode,
                "live": bool(result.get("live")),
                "reply_to": user_message.id,
            },
        )
        if result.get("workflow_id") and result["workflow_id"] not in (conversation.workflow_ids or []):
            workflow_ids = list(conversation.workflow_ids or []) + [result["workflow_id"]]
            conversation = await self.store.update(
                conversation_id, workflow_ids=workflow_ids[-12:], last_intent=intent
            ) or conversation
        else:
            conversation = await self.store.update(
                conversation_id, last_intent=intent
            ) or conversation
        return self._pair(conversation, user_message, assistant, extra={
            "workflow_id": result.get("workflow_id"),
        })

    async def _run_intent(
        self, *, conversation: Conversation, project: str, text: str,
        intent: str, actor: str,
    ) -> dict[str, Any]:
        """Run one already-resolved intent.

        Shared by ``post_message`` and the project-selection continuation so the
        pending request follows exactly the same safe path as a typed one.
        """
        if intent in {"metrics", "logs", "status"}:
            title = {"metrics": "بررسی منابع", "logs": "بررسی لاگ‌ها", "status": "بررسی وضعیت"}[intent]
            return await self._read_only(project=project, intent=intent, title=title)
        if intent == "diagnose":
            return await self._diagnose(project=project, text=text)
        if intent == "report":
            return await self._report(conversation)
        if intent in {"repair", "deploy"}:
            return await self._start_workflow(
                conversation=conversation, project=project, text=text,
                intent=intent, actor=actor,
            )
        return await self._read_only(project=project, intent="status", title="بررسی وضعیت")

    @staticmethod
    def _pair(
        conversation: Conversation, user_message: Any, assistant: Any,
        *, extra: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return {
            "conversation": conversation_dict(conversation),
            "user_message": message_dict(user_message),
            "assistant_message": message_dict(assistant),
            **(extra or {}),
        }

    async def _audit(
        self, conversation_id: str, intent: str, project: str | None, workflow_id: str | None
    ) -> None:
        await self.audit.record(
            "conversation.intent", target=conversation_id, outcome="routed",
            detail={"intent": intent, "project": project, "workflow_id": workflow_id},
        )

    # ------------------------------------------------------------------
    # read-only intents
    # ------------------------------------------------------------------
    async def _read_only(self, *, project: str, intent: str, title: str) -> dict[str, Any]:
        blocks: list[dict[str, Any]] = []
        parts: list[str] = []
        simulated = bool(self.adapter.simulated)
        range_minutes = 60

        project_row = next((p for p in await self._projects() if p["name"] == project), None)
        if project_row:
            blocks.append(ui_blocks.project_overview_block(
                project_row, simulated=simulated,
                mode="demo" if self.settings.demo_mode else "live",
                notice=MODE_NOTICE_DEMO if simulated else None,
            ))

        if intent in {"metrics", "status"}:
            since = utcnow().timestamp() - range_minutes * 60
            cpu, memory = await self._gather_metrics(project, since)
            blocks.append(ui_blocks.metrics_block(
                project=project, range_minutes=range_minutes,
                cpu=cpu, memory=memory, simulated=simulated,
            ))
            cpu_text = self._metrics_sentence("CPU", cpu)
            mem_text = self._metrics_sentence("RAM", memory)
            parts.append(f"بازه {fa_number(range_minutes)} دقیقه گذشته: {cpu_text} {mem_text}")
            if cpu.get("unavailable_reason") or memory.get("unavailable_reason"):
                parts.append("بخشی از داده‌ها در دسترس نبود؛ عدد صفر جای آن نمایش داده نمی‌شود.")

        if intent in {"logs", "status"}:
            log_payload = await self._logs(project, range_minutes)
            if log_payload["lines"]:
                blocks.append(ui_blocks.logs_block(
                    project=project, range_minutes=range_minutes,
                    lines=log_payload["lines"], flagged=log_payload["flagged"],
                    simulated=simulated,
                ))
                errors = sum(1 for line in log_payload["lines"]
                             if line["level"] in {"error", "critical"})
                parts.append(
                    f"{fa_number(len(log_payload['lines']))} خط لاگ بررسی شد؛ "
                    f"{fa_number(errors)} خط در سطح error/critical است."
                )
                if log_payload["flagged"]:
                    parts.append(
                        f"{fa_number(log_payload['flagged'])} خط حاوی متن شبیه دستور بود و "
                        "به‌عنوان داده غیرقابل‌اعتماد خنثی شد."
                    )
            else:
                parts.append("لاگی برای این بازه در دسترس نبود؛ نتیجه‌ای از خودم نمی‌سازم.")

        if intent == "status":
            parts.insert(0, f"وضعیت فعلی {project} را از داده‌های موجود بررسی کردم.")
        else:
            parts.insert(0, f"{title} برای {project} انجام شد.")
        if simulated:
            parts.append(MODE_NOTICE_DEMO)

        valid, errors = ui_blocks.validate_blocks(blocks)
        if errors:
            logger.warning("dropped invalid ui blocks", extra={"event_data": {"errors": errors}})
        return {"text": "\n\n".join(parts), "blocks": valid, "live": False, "workflow_id": None}

    async def _gather_metrics(self, project: str, since: float) -> tuple[dict[str, Any], dict[str, Any]]:
        import asyncio

        cpu, memory = await asyncio.gather(
            self.adapter.get_cpu_metrics(project, since=since),
            self.adapter.get_memory_metrics(project, since=since),
            return_exceptions=True,
        )

        def _payload(series: Any) -> dict[str, Any]:
            if isinstance(series, BaseException):
                return {"unavailable_reason": str(series)[:200], "points": []}
            return {
                **series.as_summary(),
                "points": [{"t": p.timestamp, "v": p.value} for p in series.points[-120:]],
            }

        return _payload(cpu), _payload(memory)

    @staticmethod
    def _metrics_sentence(label: str, series: dict[str, Any]) -> str:
        points = series.get("points") or []
        if not points:
            reason = series.get("unavailable_reason") or "داده‌ای برنگشت"
            return f"{label}: ناموجود ({reason})."
        unit = series.get("unit") or "%"
        latest = series.get("last")
        maximum = series.get("maximum")
        average = series.get("average")
        return (
            f"{label}: آخرین {fa_number(latest)}{unit}، میانگین {fa_number(average)}{unit}، "
            f"بیشینه {fa_number(maximum)}{unit}."
        )

    async def _logs(self, project: str, minutes: int) -> dict[str, Any]:
        since = utcnow() - timedelta(minutes=minutes)
        entries = await self.adapter.get_logs(project, since=since)
        lines: list[dict[str, Any]] = []
        flagged = 0
        for entry in entries[-120:]:
            message, was_flagged = sanitize_log_message(entry.message)
            flagged += int(was_flagged)
            lines.append({
                "datetime": entry.datetime,
                "level": entry.level,
                "message": message,
                "flagged": was_flagged,
            })
        return {"lines": lines, "flagged": flagged}

    async def _diagnose(self, *, project: str, text: str) -> dict[str, Any]:
        workflow_id = new_id("diag")
        await self.repo.create_workflow({
            "id": workflow_id,
            "thread_id": f"thread-{workflow_id}",
            "project": project,
            "request_text": text,
            "status": "running",
            "current_step": "diagnose_issue",
            "demo_mode": self.settings.demo_mode,
            "simulated": self.adapter.simulated,
            "attempt": 0,
            "max_attempts": 0,
            "created_by": "chat-diagnose",
        })
        await self.repo.add_event(
            workflow_id, step="diagnose_issue", status="running",
            message="تشخیص سریع (بدون تغییر در لیارا) آغاز شد.",
            step_key=f"{workflow_id}:chat-diagnose:start",
        )
        bundle, report = await self.diagnosis.diagnose(
            workflow_id=workflow_id, project=project, attempt=0, request_text=text
        )
        diagnosis = report.as_dict()
        final_report = {
            "workflow_id": workflow_id,
            "project": project,
            "mode": bundle.mode,
            "simulated": bundle.simulated,
            "outcome": "diagnosed",
            "stop_reason": "diagnosis_only",
            "generated_at": iso(),
            "problem": {"request": text, "observation": report.observation},
            "evidence": {
                "refs": report.evidence_refs,
                "statements": report.evidence,
                "unavailable_sources": report.unavailable_sources,
                "resource_assessment": report.resource_assessment,
            },
            "diagnosis": {
                "probable_cause": report.probable_cause,
                "cause_key": report.probable_cause_key,
                "alternatives": report.alternatives,
                "confidence": report.confidence,
                "recommended_action": report.recommended_action,
                "risk": report.risk,
                "verification_method": report.verification_method,
                "engine": report.engine,
            },
            "change": None,
            "tests": None,
            "deployment": None,
            "verification": None,
            "human_actions": {"repair_approval": None, "deployment_approval": None},
            "remaining_limitations": [
                "این پاسخ فقط تشخیص است و هیچ اصلاح یا انتشاری را شروع نکرده است."
            ],
        }
        await self.repo.set_workflow_status(
            workflow_id, "completed", current_step="diagnose_issue",
            diagnosis=diagnosis, final_report=final_report,
            stop_reason="no_incident_detected" if not report.has_incident else "diagnosis_only",
        )
        await self.repo.add_event(
            workflow_id, step="diagnose_issue", status="completed",
            message=f"تشخیص کامل شد: {report.probable_cause_key}",
            step_key=f"{workflow_id}:chat-diagnose:done",
            data={"cause_key": report.probable_cause_key, "confidence": report.confidence},
        )
        evidence_rows = [evidence_dict(row) for row in await self.repo.list_evidence(workflow_id)]
        blocks: list[dict[str, Any]] = [
            ui_blocks.diagnosis_block(
                diagnosis, project=project, simulated=bool(bundle.simulated)
            )
        ]
        if evidence_rows:
            blocks.append(ui_blocks.evidence_block(
                evidence_rows, unavailable=report.unavailable_sources
            ))
        since = utcnow().timestamp() - 3600
        cpu, memory = await self._gather_metrics(project, since)
        if cpu.get("points") or memory.get("points"):
            blocks.append(ui_blocks.metrics_block(
                project=project, range_minutes=60,
                cpu=cpu, memory=memory, simulated=bool(bundle.simulated),
            ))
        valid, errors = ui_blocks.validate_blocks(blocks)
        if errors:
            logger.warning("dropped invalid diagnosis blocks", extra={"event_data": {"errors": errors}})
        if report.has_incident:
            text_out = (
                f"بررسی کامل شد. محتمل‌ترین علت: {report.probable_cause}\n\n"
                f"{report.recommended_action}\n\n"
                "اگر بخواهید همین‌جا اصلاح را شروع کنم، بنویسید «حالا اصلاحش کن»؛ "
                "عملیات حساس فقط با تأیید شما اجرا می‌شود."
            )
        else:
            text_out = (
                "شواهد فعلی نشان‌دهنده حادثه نیست. هیچ اصلاحی پیشنهاد نمی‌شود "
                "و هیچ عملیاتی اجرا نشد."
            )
        if evidence_rows and errors:
            text_out += "\n\nبخشی از نمایش‌های گرافیکی حذف شد؛ جزئیات متنی بالا کامل است."
        return {
            "text": text_out,
            "blocks": valid,
            "live": False,
            "workflow_id": workflow_id,
            "diagnosis_only": True,
        }

    async def _report(self, conversation: Conversation) -> dict[str, Any]:
        workflow_ids = list(conversation.workflow_ids or [])
        for workflow_id in reversed(workflow_ids):
            detail = await self._workflow_detail(workflow_id)
            if detail is None:
                continue
            blocks = self._blocks_for(detail)
            valid, errors = ui_blocks.validate_blocks(blocks)
            if errors:
                logger.warning("dropped invalid report blocks", extra={"event_data": {"errors": errors}})
            report = detail.get("final_report") or {}
            if report:
                text_out = (
                    f"گزارش نهایی گردش‌کار {workflow_id}: وضعیت {detail.get('status')}، "
                    f"نتیجه {report.get('outcome')} و دلیل توقف {report.get('stop_reason')}."
                )
                if report.get("verification", {}).get("status") == "unverified":
                    text_out += " بررسی سلامت تأییدنشده است، نه سالم."
            else:
                text_out = (
                    f"گردش‌کار {workflow_id} هنوز گزارش نهایی ندارد؛ وضعیت فعلی: "
                    f"{detail.get('status')} در مرحله {detail.get('current_step')}."
                )
            return {
                "text": text_out,
                "blocks": valid,
                "live": bool(workflow_id in workflow_ids),
                "workflow_id": workflow_id,
            }
        return {
            "text": (
                "هنوز گردش‌کاری در این گفت‌وگو ثبت نشده است. اول یک بررسی یا اصلاح را شروع کنید؛ "
                "سپس گزارش از داده‌های همان گردش‌کار ساخته می‌شود."
            ),
            "blocks": [],
            "live": False,
            "workflow_id": None,
        }

    # ------------------------------------------------------------------
    # workflow intents
    # ------------------------------------------------------------------
    async def _start_workflow(
        self, *, conversation: Conversation, project: str, text: str, intent: str, actor: str
    ) -> dict[str, Any]:
        # Never start a parallel workflow for the same project and the same repair
        # loop.  The existing run is the source of truth.
        for workflow_id in reversed(conversation.workflow_ids or []):
            row = await self.repo.get_workflow(workflow_id)
            if row is None or row.project != project:
                continue
            if row.status in ACTIVE_STATUSES:
                detail = await self._workflow_detail(workflow_id)
                if detail:
                    blocks, _ = ui_blocks.validate_blocks(self._blocks_for(detail))
                    return {
                        "text": (
                            f"یک گردش‌کار فعال برای {project} وجود دارد "
                            f"(وضعیت: {row.status}، مرحله: {row.current_step}). "
                            "برای جلوگیری از اجرای موازی، همان را ادامه می‌دهم."
                        ),
                        "blocks": blocks,
                        "live": True,
                        "workflow_id": workflow_id,
                    }

        started = await self.runner.start(
            request_text=text, project=project, actor=actor,
            max_attempts=self.settings.coding_agent_max_repair_attempts,
        )
        workflow_id = started["workflow_id"]
        detail = await self._workflow_detail(workflow_id)
        blocks = ui_blocks.validate_blocks(self._blocks_for(detail))[0] if detail else []
        if intent == "deploy":
            text_out = (
                "گردش‌کار اصلاح و انتشار شروع شد. آماده‌سازی سورس و ساخت Release "
                "به تأیید جداگانه نیاز دارد؛ آن را همین‌جا می‌بینید. "
                "تا زمانی که تأیید نکنید، هیچ انتشار واقعی انجام نمی‌شود."
            )
        else:
            text_out = (
                "گردش‌کار اصلاح شروع شد. پیشرفت، شواهد، تست‌ها و Diff را همین‌جا می‌بینید. "
                "اجرای عملیات حساس فقط پس از تأیید معتبر سرور انجام می‌شود."
            )
        if self.settings.demo_mode:
            text_out += "\n\nاین اجرا در حالت DEMO است."
        return {"text": text_out, "blocks": blocks, "live": True, "workflow_id": workflow_id}

    # ------------------------------------------------------------------
    # project selection
    # ------------------------------------------------------------------
    async def select_project(self, conversation_id: str, *, project: str) -> dict[str, Any]:
        conversation = await self._load(conversation_id)
        projects = await self._projects()
        names = {p["name"] for p in projects}
        clean = validate_project_name(project)
        if clean not in names:
            raise ValidationError(
                "پروژه انتخاب‌شده در فهرست پروژه‌های قابل‌دسترسی نیست.",
                details={"project": clean},
            )
        conversation = await self.store.update(conversation_id, project=clean) or conversation
        row = next(p for p in projects if p["name"] == clean)

        # Continuing the unanswered request: only the *latest* message counts, so
        # an old picker card that is clicked again cannot replay a finished request.
        messages = await self.store.list_messages(conversation_id, limit=400)
        last = messages[-1] if messages else None
        pending_data = (last.data or {}) if last is not None and last.role == "assistant" else {}
        pending_request = str(pending_data.get("pending_request") or "").strip()

        if pending_request:
            intent = self.detect_intent(pending_request)
            result = await self._run_intent(
                conversation=conversation, project=clean, text=pending_request,
                intent=intent, actor="chat",
            )
            assistant = await self.store.add_message(
                conversation_id,
                role="assistant",
                text=result["text"],
                blocks=result["blocks"],
                workflow_id=result.get("workflow_id"),
                data={
                    "intent": intent,
                    "mode": "demo" if self.settings.demo_mode else "live",
                    "live": bool(result.get("live")),
                    "continued_after_project_selection": True,
                },
            )
            workflow_id = result.get("workflow_id")
            updates: dict[str, Any] = {"last_intent": intent}
            if workflow_id and workflow_id not in (conversation.workflow_ids or []):
                updates["workflow_ids"] = list(conversation.workflow_ids or []) + [workflow_id]
            conversation = await self.store.update(conversation_id, **updates) or conversation
            await self._audit(conversation_id, intent, clean, workflow_id)
            return {
                "conversation": conversation_dict(conversation),
                "assistant_message": message_dict(assistant),
                "workflow_id": workflow_id,
                "continued": True,
            }

        blocks = [ui_blocks.project_overview_block(
            row,
            simulated=bool(self.adapter.simulated),
            mode="demo" if self.settings.demo_mode else "live",
            notice=MODE_NOTICE_DEMO if self.adapter.simulated else None,
        )]
        assistant = await self.store.add_message(
            conversation_id,
            role="assistant",
            text=(
                f"پروژه فعال روی {clean} تنظیم شد. از این به بعد درخواست‌ها روی همین پروژه "
                "اجرا می‌شوند و لازم نیست نامش را تکرار کنید."
            ),
            blocks=ui_blocks.validate_blocks(blocks)[0],
            data={"intent": "select_project", "active_project": clean},
        )
        await self.audit.record(
            "conversation.project_selected", target=conversation_id,
            detail={"project": clean}, outcome="ok",
        )
        return {
            "conversation": conversation_dict(conversation),
            "assistant_message": message_dict(assistant),
        }

    # ------------------------------------------------------------------
    # live workflow state (replaces blocks, never duplicates cards)
    # ------------------------------------------------------------------
    async def live(self, conversation_id: str) -> dict[str, Any]:
        conversation = await self._load(conversation_id)
        states: list[dict[str, Any]] = []
        for workflow_id in list(conversation.workflow_ids or [])[-6:]:
            detail = await self._workflow_detail(workflow_id)
            if detail is None:
                continue
            blocks, errors = ui_blocks.validate_blocks(self._blocks_for(detail))
            if errors:
                logger.warning("dropped invalid live blocks", extra={"event_data": {"errors": errors}})
            states.append({
                "workflow_id": workflow_id,
                "status": detail.get("status"),
                "current_step": detail.get("current_step"),
                "pending_approval_id": detail.get("pending_approval_id"),
                "simulated": bool(detail.get("simulated")),
                "blocks": blocks,
                "server_time": iso(),
            })
        return {
            "conversation_id": conversation_id,
            "project": conversation.project,
            "states": states,
            "server_time": iso(),
        }

    # ------------------------------------------------------------------
    # approvals and cancellation from inside the chat
    # ------------------------------------------------------------------
    async def decide(
        self, conversation_id: str, approval_id: str, *, decision: str,
        actor: str = "chat", note: str | None = None,
    ) -> dict[str, Any]:
        conversation = await self._load(conversation_id)
        approval = await self.approvals.get(approval_id)
        if approval.workflow_id not in set(conversation.workflow_ids or []):
            raise NotFoundError(
                "این درخواست تأیید به این گفت‌وگو تعلق ندارد.",
                details={"approval_id": approval_id},
            )
        workflow = await self.repo.get_workflow(approval.workflow_id)
        if workflow is None:
            raise NotFoundError("گردش‌کار این تأیید پیدا نشد.")
        if workflow.status in TERMINAL_STATUSES:
            raise ConflictError(
                f"گردش‌کار قبلاً پایان یافته است ({workflow.status}).",
                details={"workflow_id": workflow.id, "status": workflow.status},
            )
        updated = await self.approvals.decide(
            approval_id, decision=decision, actor=actor, note=note  # type: ignore[arg-type]
        )
        await self.runner.resume(
            workflow.id, approval_id=updated.id, actor=actor, wait=False
        )
        detail = await self._workflow_detail(workflow.id)
        blocks = ui_blocks.validate_blocks(self._blocks_for(detail))[0] if detail else []
        detail_live = await self.live(conversation_id)
        return {
            "approval": approval_dict(updated),
            "workflow_id": workflow.id,
            "blocks": blocks,
            "live": detail_live,
            "note": (
                "تصمیم در سرور ثبت شد و گردش‌کار ادامه یافت. "
                "نتیجه نهایی فقط از وضعیت واقعی گردش‌کار خوانده می‌شود."
            ),
        }

    async def cancel_workflow(
        self, conversation_id: str, workflow_id: str, *, actor: str = "chat"
    ) -> dict[str, Any]:
        conversation = await self._load(conversation_id)
        if workflow_id not in set(conversation.workflow_ids or []):
            raise NotFoundError(
                "این گردش‌کار به این گفت‌وگو تعلق ندارد.",
                details={"workflow_id": workflow_id},
            )
        result = await self.runner.cancel(workflow_id, actor=actor)
        return {
            "workflow": result,
            "note": (
                "درخواست لغو به سرور رسید. اگر گردش‌کار در مرحله غیرقابل‌لغو باشد، "
                "وضعیت واقعی همان است که در پاسخ آمده است."
            ),
        }
