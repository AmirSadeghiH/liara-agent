import * as React from "react";
import {
  AlertOctagon,
  Check,
  KeyRound,
  ShieldCheck,
  Timer,
  X,
} from "lucide-react";
import type { ApprovalCardProps } from "@/lib/types";
import { BlockShell } from "@/components/ui/BlockShell";
import { Badge, DemoBadge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { CopyButton } from "@/components/ui/CopyButton";
import { DataGrid, MetaItem, Notice, Section, StatusPill } from "./primitives";
import { faDateTime, fa, riskFa, statusFa } from "@/lib/format";

const PARAM_LABELS: Record<string, string> = {
  stage: "مرحله",
  project: "پروژه",
  cause_key: "علت",
  branch: "شاخه",
  files: "فایل‌ها",
  attempt: "تلاش",
  max_attempts: "حداکثر تلاش",
  simulated: "شبیه‌سازی",
  source_id: "شناسه سورس",
  port: "پورت",
  project_type: "نوع پروژه",
};

const CONSEQUENCES: Record<ApprovalCardProps["stage"], string> = {
  repair:
    "اجرای ایجنت کدنویسی در Workspace ایزوله، اجرای تست‌ها و آماده‌سازی سورس. تا انتقال به Production فاصله دارد و انتشار همچنان تأیید جداگانه می‌خواهد.",
  deploy:
    "ساخت Release در پروژه Production و جایگزینی نسخه در حال اجرا. این اقدام برگشت‌پذیر نیست مگر با انتشار نسخه قبلی.",
};

function paramsEntries(params: Record<string, unknown>): Array<[string, string]> {
  return Object.entries(params)
    .filter(([, value]) => value !== null && value !== undefined)
    .slice(0, 12)
    .map(([key, value]) => {
      const label = PARAM_LABELS[key] ?? key;
      if (Array.isArray(value)) return [label, value.map(String).join("، ")];
      if (typeof value === "object") return [label, JSON.stringify(value)];
      if (typeof value === "boolean") return [label, value ? "بله" : "خیر"];
      return [label, String(value)];
    });
}

export function ApprovalCardBlock({
  props,
  onApprove,
  onReject,
}: {
  props: ApprovalCardProps;
  onApprove?: (approvalId: string) => Promise<void> | void;
  onReject?: (approvalId: string) => Promise<void> | void;
}) {
  const [confirming, setConfirming] = React.useState(false);
  const [busy, setBusy] = React.useState<"approve" | "reject" | null>(null);
  const [decided, setDecided] = React.useState<string | null>(null);
  const [error, setError] = React.useState<string | null>(null);

  const expiresAt = props.expires_at ? new Date(props.expires_at) : null;
  const expired = expiresAt ? expiresAt.getTime() < Date.now() : false;
  const pending =
    props.status === "pending" && !expired && !decided && Boolean(onApprove) && Boolean(onReject);
  const effectiveStatus = decided ?? (expired && props.status === "pending" ? "expired" : props.status);
  const entries = paramsEntries(props.params);

  async function approve() {
    if (!pending || busy) return;
    setBusy("approve");
    setError(null);
    try {
      await onApprove?.(props.approval_id);
      setDecided("approved");
      setConfirming(false);
    } catch (err) {
      setError(err instanceof Error ? err.message : "ثبت تأیید در سرور ناموفق بود.");
    } finally {
      setBusy(null);
    }
  }

  async function reject() {
    if (!pending || busy) return;
    setBusy("reject");
    setError(null);
    try {
      await onReject?.(props.approval_id);
      setDecided("rejected");
    } catch (err) {
      setError(err instanceof Error ? err.message : "ثبت رد درخواست ناموفق بود.");
    } finally {
      setBusy(null);
    }
  }

  return (
    <BlockShell
      icon={<ShieldCheck />}
      title={props.stage === "deploy" ? "تأیید انتشار Production" : "تأیید عملیات اصلاح"}
      tone={props.risk_level === "high" ? "danger" : "warning"}
      meta={
        <>
          <StatusPill status={effectiveStatus} />
          <Badge variant={props.risk_level === "high" ? "destructive" : "warning"}>
            ریسک: {riskFa(props.risk_level)}
          </Badge>
          <DemoBadge live={!props.simulated} />
        </>
      }
      actions={
        <CopyButton text={props.approval_id} label="کپی شناسه" />
      }
    >
      <div className="space-y-4">
        <p className="text-[13.5px] leading-7 font-medium">{props.title}</p>
        <Section title="دلیل انجام عملیات">{props.reason || "—"}</Section>

        <DataGrid columns={2}>
          <MetaItem label="پروژه هدف" value={props.project || "—"} mono />
          <MetaItem label="اقدام" value={props.action} mono />
          <MetaItem
            label="انقضا"
            value={
              expired
                ? "منقضی شده"
                : expiresAt
                  ? `${faDateTime(props.expires_at)} (${fa(Math.max(0, Math.round((expiresAt.getTime() - Date.now()) / 60000)))} دقیقه)`
                  : "—"
            }
          />
        </DataGrid>

        {entries.length > 0 && (
          <div className="rounded-field border border-border bg-background/30 px-3 py-2.5">
            <div className="mb-1.5 flex items-center gap-1.5 text-[11px] text-muted-foreground">
              <KeyRound className="size-3" />
              پارامترهای نهایی
            </div>
            <dl className="grid grid-cols-1 gap-x-5 gap-y-1.5 sm:grid-cols-2">
              {entries.map(([label, value]) => (
                <div key={label} className="flex min-w-0 justify-between gap-3 border-b border-border/60 py-0.5 last:border-0">
                  <dt className="shrink-0 text-[11px] text-muted-foreground">{label}</dt>
                  <dd className="code-block min-w-0 truncate text-[10.5px]" dir="ltr" title={value}>
                    {value}
                  </dd>
                </div>
              ))}
            </dl>
          </div>
        )}

        <Section title="پیامد احتمالی">
          <p className="text-[12.5px] leading-6 text-muted-foreground">
            {CONSEQUENCES[props.stage]}
          </p>
        </Section>

        <div className="rounded-field border border-border bg-muted/30 px-3 py-2 text-[10.5px] leading-5 text-muted-foreground">
          شناسه درخواست:{" "}
          <span className="code-block" dir="ltr">
            {props.approval_id}
          </span>
          <br />
          این دکمه فقط زمانی عملیات را اجرا می‌کند که درخواست تأیید در سرور معتبر، تأییدنشده و
          منقضی‌نشده باشد. تغییر وضعیت در مرورگر یا متن مدل، مجوز ایجاد نمی‌کند.
        </div>

        {effectiveStatus !== "pending" && (
          <Notice
            tone={
              effectiveStatus === "approved"
                ? "success"
                : effectiveStatus === "rejected"
                  ? "danger"
                  : "warning"
            }
          >
            وضعیت تصمیم: {statusFa(effectiveStatus)}
            {effectiveStatus === "approved"
              ? " — تصمیم در سرور ثبت شد و گردش‌کار ادامه یافت."
              : effectiveStatus === "rejected"
                ? " — عملیات مربوطه اجرا نشد."
                : effectiveStatus === "expired"
                  ? " — این تأیید منقضی شده؛ برای ادامه یک درخواست جدید لازم است."
                  : "."}
          </Notice>
        )}

        {props.decision_note && (
          <p className="text-[11px] text-muted-foreground">یادداشت: {props.decision_note}</p>
        )}

        {error && (
          <Notice tone="danger">
            <span role="alert">{error}</span>
          </Notice>
        )}

        {pending && !confirming && (
          <div className="flex flex-wrap gap-2">
            <Button variant="brand" onClick={() => setConfirming(true)} disabled={busy !== null}>
              <Check />
              تأیید و ادامه
            </Button>
            <Button variant="outline" onClick={reject} disabled={busy !== null}>
              {busy === "reject" ? (
                <span className="size-3.5 animate-spin rounded-full border-2 border-muted-foreground/30 border-t-foreground" />
              ) : (
                <X />
              )}
              رد عملیات
            </Button>
            <span className="flex items-center gap-1 text-[10.5px] text-muted-foreground">
              <Timer className="size-3" />
              پس از تأیید، نتیجه از وضعیت واقعی سرور خوانده می‌شود.
            </span>
          </div>
        )}

        {pending && confirming && (
          <div className="rounded-field border border-warning/30 bg-warning/5 px-3 py-3">
            <div className="mb-2 flex items-center gap-1.5 text-[12px] text-warning">
              <AlertOctagon className="size-3.5" />
              اقدام دقیق را یک‌بار دیگر بررسی کنید؛ این تصمیم در سرور ثبت می‌شود.
            </div>
            <div className="flex flex-wrap gap-2">
              <Button variant="brand" onClick={approve} disabled={busy !== null}>
                {busy === "approve" ? (
                  <span className="size-3.5 animate-spin rounded-full border-2 border-brand-foreground/30 border-t-brand-foreground" />
                ) : (
                  <Check />
                )}
                بله، ثبت و ادامه
              </Button>
              <Button variant="ghost" onClick={() => setConfirming(false)} disabled={busy !== null}>
                انصراف
              </Button>
            </div>
          </div>
        )}

        {busy === "approve" && <p className="text-[11px] text-muted-foreground">در حال ثبت تصمیم…</p>}
      </div>
    </BlockShell>
  );
}
