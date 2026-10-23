import * as React from "react";
import {
  Bot,
  CheckCircle2,
  ChevronDown,
  FileDiff,
  FlaskConical,
  Wrench,
} from "lucide-react";
import type {
  CodingAgentStatusProps,
  DiffReviewProps,
  RepairPlanProps,
  TestResultsProps,
} from "@/lib/types";
import { BlockShell } from "@/components/ui/BlockShell";
import { Badge, DemoBadge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { CopyButton } from "@/components/ui/CopyButton";
import { DataGrid, MetaItem, Notice, Section, StatusPill } from "./primitives";
import { cn } from "@/lib/cn";
import {
  causeFa,
  fa,
  faDuration,
  riskFa,
  statusFa,
} from "@/lib/format";

export function RepairPlanBlock({ props }: { props: RepairPlanProps }) {
  return (
    <BlockShell
      icon={<Wrench />}
      title="برنامه اصلاح"
      meta={
        <>
          <Badge variant="warning">{causeFa(props.cause_key)}</Badge>
          <span>
            تلاش {fa(props.attempt + 1)} از {fa(props.max_attempts)}
          </span>
          <DemoBadge live={!props.simulated} />
        </>
      }
      actions={
        <CopyButton
          text={[props.title, props.summary, ...props.steps.map((step, i) => `${i + 1}. ${step}`)].join("\n")}
          label="کپی برنامه"
        />
      }
    >
      <div className="space-y-4">
        <Section title="هدف">{props.title || "—"}</Section>
        <Section title="خلاصه">{props.summary || "—"}</Section>
        <Section title="کارهای پیشنهادی">
          <ol className="space-y-1.5">
            {props.steps.map((step, index) => (
              <li key={`${index}-${step}`} className="flex gap-2 text-[12.5px] leading-6">
                <span className="mt-0.5 flex size-4 shrink-0 items-center justify-center rounded-full border border-border text-[9.5px] text-muted-foreground">
                  {fa(index + 1)}
                </span>
                <span>{step}</span>
              </li>
            ))}
          </ol>
        </Section>
        <DataGrid columns={4}>
          <MetaItem label="سطح ریسک" value={riskFa(props.risk_level)} />
          <MetaItem label="محدوده فایل" value={props.files.length ? props.files.join(", ") : "نامشخص"} mono />
          <MetaItem label="شاخه" value={props.branch || "—"} mono />
          <MetaItem
            label="راستی‌آزمایی"
            value={props.requires_tests ? "اجرای تست‌های پروژه الزامی است" : "تست الزامی نیست"}
          />
        </DataGrid>
        <Notice>
          این کارت فقط برنامه است؛ نتیجه اجرا پس از اجرای واقعی ایجنت و تست‌ها نمایش داده می‌شود.
        </Notice>
      </div>
    </BlockShell>
  );
}

export function CodingAgentStatusBlock({ props }: { props: CodingAgentStatusProps }) {
  return (
    <BlockShell
      icon={<Bot />}
      title="ایجنت کدنویسی"
      tone={props.needs_human ? "warning" : "default"}
      meta={
        <>
          <StatusPill status={props.status} />
          <span className="code-block" dir="ltr">
            {props.provider}
          </span>
          <span>
            تلاش {fa(props.attempt + 1)}
          </span>
          <DemoBadge live={!props.simulated} />
        </>
      }
    >
      <div className="space-y-3">
        <p className="text-[13px] leading-7">{props.summary || "خلاصه‌ای ثبت نشده است."}</p>
        <DataGrid columns={4}>
          <MetaItem label="زمان اجرا" value={faDuration(props.duration_ms)} />
          <MetaItem label="فایل‌های تغییرکرده" value={fa(props.files_changed.length)} />
          <MetaItem label="شاخه" value={props.branch || "—"} mono />
          <MetaItem
            label="وضعیت"
            value={props.needs_human ? "نیازمند تصمیم انسان" : statusFa(props.status)}
          />
        </DataGrid>
        {props.files_changed.length > 0 && (
          <ul className="flex flex-wrap gap-1.5">
            {props.files_changed.map((file) => (
              <li
                key={file}
                className="code-block rounded-control border border-border bg-muted/40 px-2 py-0.5 text-[10.5px] text-muted-foreground"
                dir="ltr"
              >
                {file}
              </li>
            ))}
          </ul>
        )}
        {props.needs_human && (
          <Notice tone="warning">
            ایجنت بدون نتیجه قابل‌انتشار متوقف شد. خروجی خام و طولانی ترمینال در متن چت
            ریخته نمی‌شود؛ برای ادامه به تصمیم یا اجرای دستی نیاز است.
          </Notice>
        )}
      </div>
    </BlockShell>
  );
}

export function DiffReviewBlock({ props }: { props: DiffReviewProps }) {
  const [expanded, setExpanded] = React.useState(false);
  const [showAllFiles, setShowAllFiles] = React.useState(false);
  const lines = props.diff.split("\n");
  const visible = expanded ? lines : lines.slice(0, 40);
  const files = showAllFiles ? props.files : props.files.slice(0, 8);
  const blocked = props.violations.length > 0;

  return (
    <BlockShell
      icon={<FileDiff />}
      title="بررسی Diff"
      tone={blocked ? "danger" : "default"}
      meta={
        <>
          <Badge variant={blocked ? "destructive" : "success"}>
            {blocked ? "تغییرات غیرمجاز" : "بدون تخلف"}
          </Badge>
          <span>{fa(props.files.length)} فایل</span>
          {props.provider && (
            <span className="code-block" dir="ltr">
              {props.provider}
            </span>
          )}
          <DemoBadge live={!props.simulated} />
        </>
      }
      actions={<CopyButton text={props.diff} label="کپی Diff" />}
    >
      <div className="space-y-3">
        {blocked && (
          <Notice tone="danger">
            تغییرات غیرمجاز شناسایی شد و انتشار مسدود است: {props.violations.join("؛ ")}
          </Notice>
        )}
        {props.warnings.length > 0 && (
          <Notice tone="warning">{props.warnings.join("؛ ")}</Notice>
        )}
        {props.sensitive_files.length > 0 && (
          <Notice tone="danger">
            فایل حساس در تغییرات: <span dir="ltr">{props.sensitive_files.join(", ")}</span>
          </Notice>
        )}

        <Section title="فایل‌های تغییرکرده">
          <ul className="flex flex-wrap gap-1.5">
            {files.map((file) => (
              <li
                key={file}
                className="code-block rounded-control border border-border bg-muted/40 px-2 py-0.5 text-[10.5px]"
                dir="ltr"
              >
                {file}
              </li>
            ))}
            {props.files.length > 8 && (
              <li>
                <Button variant="ghost" size="sm" onClick={() => setShowAllFiles((value) => !value)}>
                  {showAllFiles ? "کمتر" : `+${fa(props.files.length - 8)} فایل`}
                </Button>
              </li>
            )}
          </ul>
        </Section>

        <div className="overflow-hidden rounded-field border border-border bg-background/60">
          <div className="flex items-center justify-between border-b border-border px-3 py-1.5">
            <span className="text-[11px] text-muted-foreground">تفاوت خطوط</span>
            <span className="code-block text-[10px] text-muted-foreground/70" dir="ltr">
              unified diff
            </span>
          </div>
          <pre className="code-block max-h-[360px] overflow-auto p-3">
            {visible.map((line, index) => (
              <span
                key={index}
                className={cn(
                  "block whitespace-pre-wrap break-words px-1",
                  line.startsWith("+") && !line.startsWith("+++") && "diff-add",
                  line.startsWith("-") && !line.startsWith("---") && "diff-del",
                  (line.startsWith("@@") || line.startsWith("---") || line.startsWith("+++")) &&
                    "diff-meta",
                )}
              >
                {line || " "}
              </span>
            ))}
            {props.diff.length === 0 && (
              <span className="text-muted-foreground">Diff خالی است.</span>
            )}
          </pre>
          {(lines.length > 40 || props.truncated) && (
            <div className="flex flex-wrap items-center justify-between gap-2 border-t border-border px-3 py-1.5">
              <span className="text-[10.5px] text-muted-foreground">
                {props.truncated ? "Diff برای نمایش بریده شده است." : `${fa(lines.length)} خط`}
              </span>
              {lines.length > 40 && (
                <Button variant="ghost" size="sm" onClick={() => setExpanded((value) => !value)}>
                  {expanded ? "جمع کردن" : "نمایش کامل"}
                  <ChevronDown className={cn("transition-transform", expanded && "rotate-180")} />
                </Button>
              )}
            </div>
          )}
        </div>
        <p className="text-[10.5px] leading-5 text-muted-foreground">
          Diff از فایل‌های واقعی Workspace ساخته شده است؛ متن تولیدشده توسط مدل به‌تنهایی مبنای
          انتشار نیست.
        </p>
      </div>
    </BlockShell>
  );
}

export function TestResultsBlock({ props }: { props: TestResultsProps }) {
  const [expanded, setExpanded] = React.useState(false);
  const passed = props.status === "passed";
  return (
    <BlockShell
      icon={passed ? <CheckCircle2 /> : <FlaskConical />}
      title="نتیجه تست‌ها"
      tone={passed ? "success" : props.status === "failed" ? "danger" : "warning"}
      meta={
        <>
          <StatusPill status={props.status} />
          <span className="code-block" dir="ltr">
            {props.runner}
          </span>
          <span>{faDuration(props.duration_ms)}</span>
          <DemoBadge live={!props.simulated} />
        </>
      }
      actions={<CopyButton text={props.output_tail} label="کپی خروجی" />}
    >
      <div className="space-y-3">
        <DataGrid columns={3}>
          <MetaItem label="کد خروج" value={props.exit_code === null ? "—" : fa(props.exit_code)} />
          <MetaItem label="دستور" value={props.command || "—"} mono />
          <MetaItem label="Timeout" value={props.timed_out ? "بله" : "خیر"} />
        </DataGrid>
        {!passed && (
          <Notice tone="danger">
            تست‌ها سبز نیستند؛ انتشار تا رفع خطا و اجرای موفق تست‌ها مجاز نیست.
          </Notice>
        )}
        <div className="overflow-hidden rounded-field border border-border bg-background/60">
          <div className="flex items-center justify-between border-b border-border px-3 py-1.5">
            <span className="text-[11px] text-muted-foreground">خروجی تست</span>
            <span className="text-[10px] text-muted-foreground/70">tail</span>
          </div>
          <pre
            className={cn(
              "code-block overflow-auto p-3 text-[11.5px]",
              expanded ? "max-h-[420px]" : "max-h-[160px]",
            )}
          >
            {props.output_tail || "خروجی‌ای ثبت نشده است."}
          </pre>
          {props.output_tail.length > 800 && (
            <div className="border-t border-border px-3 py-1.5 text-end">
              <Button variant="ghost" size="sm" onClick={() => setExpanded((value) => !value)}>
                {expanded ? "جمع کردن" : "نمایش کامل"}
                <ChevronDown className={cn("transition-transform", expanded && "rotate-180")} />
              </Button>
            </div>
          )}
        </div>
      </div>
    </BlockShell>
  );
}
