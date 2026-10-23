import * as React from "react";
import { ClipboardList, Flag, OctagonX, ScrollText, Square } from "lucide-react";
import type { FinalReportProps, WorkflowTimelineProps } from "@/lib/types";
import { BlockShell } from "@/components/ui/BlockShell";
import { Badge, DemoBadge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { CopyButton } from "@/components/ui/CopyButton";
import {
  DataGrid,
  MetaItem,
  Notice,
  Section,
  StatusPill,
  StepList,
  statusVariant,
} from "./primitives";
import { causeFa, fa, faDateTime, statusFa } from "@/lib/format";
import { cn } from "@/lib/cn";

export function WorkflowTimelineBlock({
  props,
  onCancelWorkflow,
}: {
  props: WorkflowTimelineProps;
  onCancelWorkflow?: (workflowId: string) => void | Promise<void>;
}) {
  const [confirming, setConfirming] = React.useState(false);
  const [busy, setBusy] = React.useState(false);
  const active = ["queued", "running", "testing", "deploying", "verifying", "waiting_for_approval"].includes(
    props.status,
  );
  const cancellable = ["queued", "waiting_for_approval", "needs_human", "failed"].includes(
    props.status,
  );

  async function cancel() {
    setBusy(true);
    try {
      await onCancelWorkflow?.(props.workflow_id);
    } finally {
      setBusy(false);
      setConfirming(false);
    }
  }

  return (
    <BlockShell
      icon={<ScrollText />}
      title="وضعیت گردش‌کار"
      tone={active ? "default" : statusVariant(props.status) === "destructive" ? "danger" : "success"}
      meta={
        <>
          <StatusPill status={props.status} />
          <span>
            تلاش {fa(props.attempt)} از {fa(props.max_attempts)}
          </span>
          <span className="code-block" dir="ltr">
            {props.workflow_id}
          </span>
          <DemoBadge live={!props.simulated} />
        </>
      }
      actions={
        cancellable && onCancelWorkflow ? (
          confirming ? (
            <span className="flex items-center gap-1">
              <Button size="sm" variant="destructive" onClick={cancel} disabled={busy}>
                {busy ? "در حال ارسال…" : "بله، لغو کن"}
              </Button>
              <Button size="sm" variant="ghost" onClick={() => setConfirming(false)} disabled={busy}>
                انصراف
              </Button>
            </span>
          ) : (
            <Button size="sm" variant="ghost" onClick={() => setConfirming(true)}>
              <Square />
              توقف
            </Button>
          )
        ) : null
      }
    >
      <div className="space-y-3">
        {props.current_label && active && (
          <p className="flex items-center gap-2 text-[12.5px]">
            <span className="size-1.5 animate-pulse rounded-full bg-brand" aria-hidden />
            مرحله فعلی: <strong className="font-medium">{props.current_label}</strong>
          </p>
        )}
        {props.stop_reason && (
          <p className="text-[11.5px] text-muted-foreground">
            دلیل توقف: <span className="code-block" dir="ltr">{props.stop_reason}</span>
          </p>
        )}
        {props.error && <Notice tone="danger">{props.error}</Notice>}
        <StepList steps={props.steps} />
        {confirming && (
          <Notice tone="warning">
            لغو فقط در مراحل مجاز انجام می‌شود و نتیجه واقعی از پاسخ سرور خوانده می‌شود. اگر
            فراخوانی در حال اجرا باشد، لغو ممکن است رد شود.
          </Notice>
        )}
      </div>
    </BlockShell>
  );
}

export function FinalReportBlock({ props }: { props: FinalReportProps }) {
  const verification = props.verification_status;
  const outcomeTone =
    props.outcome === "completed"
      ? verification === "verified"
        ? "success"
        : "warning"
      : props.outcome === "cancelled"
        ? "warning"
        : "danger";
  const summaryLines = [
    `درخواست: ${props.request ?? "—"}`,
    `پروژه: ${props.project ?? "—"}`,
    `نتیجه: ${props.outcome} (${props.stop_reason ?? "—"})`,
    `علت: ${props.probable_cause ?? "—"}`,
    `تست: ${props.tests_status ?? "—"}`,
    `Release: ${props.deployment_status ?? "—"}`,
    `سلامت: ${props.verification_status ?? "—"}`,
    ...props.limitations.map((item) => `محدودیت: ${item}`),
  ];

  return (
    <BlockShell
      icon={<ClipboardList />}
      title="گزارش نهایی"
      tone={outcomeTone}
      meta={
        <>
          <Badge variant={statusVariant(props.outcome) === "success" ? "success" : statusVariant(props.outcome)}>
            {statusFa(props.outcome)}
          </Badge>
          {verification && (
            <Badge
              variant={
                verification === "verified"
                  ? "success"
                  : verification === "failed"
                    ? "destructive"
                    : "warning"
              }
              dot
            >
              سلامت: {statusFa(verification)}
            </Badge>
          )}
          <DemoBadge live={!props.simulated} />
        </>
      }
      actions={<CopyButton text={summaryLines.join("\n")} label="کپی گزارش" />}
    >
      <div className="space-y-4">
        <DataGrid columns={3}>
          <MetaItem label="پروژه" value={props.project || "—"} mono />
          <MetaItem label="علت" value={causeFa(props.cause_key)} />
          <MetaItem label="زمان" value={faDateTime(props.generated_at)} />
        </DataGrid>

        <Section title="درخواست اصلی">{props.request || "—"}</Section>
        <Section title="علت احتمالی">{props.probable_cause || "—"}</Section>

        {props.evidence_refs.length > 0 && (
          <Section title="شواهد بررسی‌شده">
            <ul className="flex flex-wrap gap-1.5">
              {props.evidence_refs.map((ref) => (
                <li
                  key={ref}
                  className="code-block rounded-control border border-border bg-muted/40 px-2 py-0.5 text-[10px] text-muted-foreground"
                  dir="ltr"
                >
                  {ref}
                </li>
              ))}
            </ul>
          </Section>
        )}

        <Section title="اقدامات انجام‌شده">
          {props.actions.length === 0 ? (
            <span className="text-muted-foreground">اقدامی ثبت نشده است.</span>
          ) : (
            <ul className="list-inside list-disc space-y-1 text-[12.5px] leading-6">
              {props.actions.map((action) => (
                <li key={action}>{action}</li>
              ))}
            </ul>
          )}
        </Section>

        <DataGrid columns={3}>
          <MetaItem label="تست‌ها" value={statusFa(props.tests_status)} />
          <MetaItem label="انتشار" value={statusFa(props.deployment_status)} />
          <MetaItem
            label="Health Check"
            value={
              verification === "unverified"
                ? "تأییدنشده (نه سالم)"
                : statusFa(verification)
            }
          />
        </DataGrid>

        {Object.keys(props.human_actions).length > 0 && (
          <Section title="تأییدهای انسانی">
            <ul className="space-y-1 text-[12px] leading-6">
              {Object.entries(props.human_actions).map(([key, value]) => (
                <li key={key} className="flex flex-wrap items-center justify-between gap-2">
                  <span className="text-muted-foreground">
                    {key === "repair_approval"
                      ? "تأیید اصلاح"
                      : key === "deployment_approval"
                        ? "تأیید انتشار"
                        : key}
                  </span>
                  <span>{value ? statusFa(value) : "—"}</span>
                </li>
              ))}
            </ul>
          </Section>
        )}

        {props.limitations.length > 0 && (
          <div className="rounded-field border border-warning/25 bg-warning/5 px-3 py-2.5">
            <div className="mb-1 flex items-center gap-1.5 text-[11px] text-warning">
              <Flag className="size-3" />
              محدودیت‌های باقی‌مانده
            </div>
            <ul className="list-inside list-disc space-y-1 text-[11.5px] leading-6 text-muted-foreground">
              {props.limitations.map((item) => (
                <li key={item}>{item}</li>
              ))}
            </ul>
          </div>
        )}

        {props.outcome === "cancelled" && (
          <Notice tone="warning">
            <span className="inline-flex items-center gap-1.5">
              <OctagonX className="size-3.5" />
              این گردش‌کار لغو یا رد شد؛ عملیات مربوطه اجرا نشد.
            </span>
          </Notice>
        )}

        <p className={cn("text-[10.5px] leading-5 text-muted-foreground")}>
          این گزارش از داده‌های ذخیره‌شده Backend ساخته شده است، نه از متن تولیدشده توسط مدل.
        </p>
      </div>
    </BlockShell>
  );
}
