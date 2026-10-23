import * as React from "react";
import {
  AlertTriangle,
  ChevronDown,
  FileSearch,
  Filter,
  ListTree,
  Search,
  ShieldAlert,
  Stethoscope,
  Terminal,
} from "lucide-react";
import type {
  DiagnosisCardProps,
  EvidenceListProps,
  LogViewerProps,
  MetricsPanelProps,
} from "@/lib/types";
import { BlockShell } from "@/components/ui/BlockShell";
import { Badge, DemoBadge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { CopyButton } from "@/components/ui/CopyButton";
import { MetricChart } from "@/components/ui/MetricChart";
import {
  DataGrid,
  MetaItem,
  Notice,
  Section,
  StatusPill,
} from "./primitives";
import { cn } from "@/lib/cn";
import {
  causeFa,
  confidenceFa,
  fa,
  faDateTime,
  faMinutes,
  faNumber,
  statusFa,
} from "@/lib/format";

const LEVEL_FA: Record<string, string> = {
  error: "خطا",
  critical: "بحرانی",
  warning: "هشدار",
  info: "اطلاع",
};

const LEVEL_TONE: Record<string, string> = {
  error: "text-destructive",
  critical: "text-destructive",
  warning: "text-warning",
  info: "text-muted-foreground",
};

export function DiagnosisCardBlock({ props }: { props: DiagnosisCardProps }) {
  const tone = props.has_incident ? "warning" : "success";
  return (
    <BlockShell
      icon={<Stethoscope />}
      title="تشخیص علت"
      tone={tone}
      meta={
        <>
          <StatusPill status={props.has_incident ? "waiting_for_approval" : "completed"} label={props.has_incident ? "حادثه شناسایی شد" : "بدون حادثه"} />
          <Badge variant={props.confidence === "high" ? "success" : props.confidence === "medium" ? "warning" : "secondary"}>
            اطمینان: {confidenceFa(props.confidence)}
          </Badge>
          <DemoBadge live={!props.simulated} />
          <span>{props.engine === "llm_refined" ? "قواعد + LLM" : "موتور قواعد"}</span>
        </>
      }
      actions={
        <CopyButton
          text={[
            props.observation,
            props.probable_cause,
            props.recommended_action,
            `evidence: ${props.evidence_refs.join(", ")}`,
          ].join("\n")}
          label="کپی تشخیص"
        />
      }
    >
      <div className="space-y-4">
        <Section title="مشاهده">{props.observation || "مشاهده‌ای ثبت نشد."}</Section>

        <div className="rounded-field border border-warning/25 bg-warning/5 px-3.5 py-3">
          <div className="mb-1 flex flex-wrap items-center gap-2">
            <span className="text-[11px] text-muted-foreground">علت محتمل</span>
            <Badge variant="warning">{causeFa(props.cause_key)}</Badge>
            <span className="code-block text-[10px] text-muted-foreground/70" dir="ltr">
              {props.cause_key}
            </span>
          </div>
          <p className="text-[13.5px] leading-7">{props.probable_cause || "علت مشخصی ثبت نشد."}</p>
        </div>

        <Section title="اقدام پیشنهادی">{props.recommended_action || "—"}</Section>

        <div className="grid gap-4 sm:grid-cols-2">
          <Section title="ریسک اقدام">
            <span className="text-[12.5px] leading-6">{props.risk || "—"}</span>
          </Section>
          <Section title="روش راستی‌آزمایی">
            <span className="text-[12.5px] leading-6">{props.verification_method || "—"}</span>
          </Section>
        </div>

        {props.alternatives.length > 0 && (
          <Section title="علت‌های جایگزین">
            <ul className="list-inside list-disc space-y-1 text-[12.5px] leading-6 text-muted-foreground">
              {props.alternatives.map((item) => (
                <li key={item}>{item}</li>
              ))}
            </ul>
          </Section>
        )}

        {props.evidence_refs.length > 0 && (
          <Section title="شواهد مرتبط">
            <ul className="flex flex-wrap gap-1.5">
              {props.evidence_refs.map((ref) => (
                <li key={ref}>
                  <span className="code-block inline-flex items-center rounded-control border border-border bg-muted/40 px-2 py-0.5 text-[10px] text-muted-foreground">
                    <span dir="ltr">{ref}</span>
                  </span>
                </li>
              ))}
            </ul>
          </Section>
        )}

        {props.unavailable_sources.length > 0 && (
          <Notice tone="warning">
            این منابع در دسترس نبودند و در نتیجه لحاظ نشده‌اند:{" "}
            {props.unavailable_sources.join("، ")}
          </Notice>
        )}
      </div>
    </BlockShell>
  );
}

export function EvidenceListBlock({ props }: { props: EvidenceListProps }) {
  const [showAll, setShowAll] = React.useState(false);
  const items = showAll ? props.items : props.items.slice(0, 6);

  return (
    <BlockShell
      icon={<ListTree />}
      title="شواهد جمع‌آوری‌شده"
      meta={
        <>
          <span>{fa(props.total)} سند</span>
          <DemoBadge live={props.items.every((item) => !item.simulated) && props.total > 0} />
        </>
      }
      actions={
        <CopyButton
          text={props.items.map((item) => `${item.id} | ${item.kind} | ${item.summary}`).join("\n")}
          label="کپی همه"
        />
      }
    >
      <div className="space-y-3">
        {items.length === 0 && (
          <p className="rounded-field border border-dashed border-border px-3 py-5 text-center text-[12px] text-muted-foreground">
            شاهدی ثبت نشد.
          </p>
        )}
        <ul className="divide-y divide-border">
          {items.map((item) => (
            <li key={item.id} className="flex items-start gap-3 py-2.5 first:pt-0 last:pb-0">
              <span className="code-block mt-0.5 shrink-0 text-[10px] text-muted-foreground/80">
                <span dir="ltr">{item.id}</span>
              </span>
              <div className="min-w-0 flex-1">
                <div className="flex flex-wrap items-center gap-2">
                  <Badge variant="brand" className="text-[10.5px]">
                    {item.kind}
                  </Badge>
                  <span className="truncate text-[11px] text-muted-foreground" dir="ltr">
                    {item.source}
                  </span>
                  <span className="text-[10px] text-muted-foreground/70">
                    {faDateTime(item.observed_at)}
                  </span>
                </div>
                <p className="mt-0.5 text-[12.5px] leading-6">{item.summary}</p>
              </div>
            </li>
          ))}
        </ul>
        {props.items.length > 6 && (
          <Button variant="ghost" size="sm" onClick={() => setShowAll((value) => !value)}>
            {showAll ? "نمایش کمتر" : `نمایش همه (${fa(props.items.length)})`}
            <ChevronDown className={cn("transition-transform", showAll && "rotate-180")} />
          </Button>
        )}
        {props.unavailable_sources.length > 0 && (
          <Notice tone="warning">منابع ناموجود: {props.unavailable_sources.join("، ")}</Notice>
        )}
      </div>
    </BlockShell>
  );
}

export function LogViewerBlock({ props }: { props: LogViewerProps }) {
  const [query, setQuery] = React.useState("");
  const [level, setLevel] = React.useState("all");
  const [expanded, setExpanded] = React.useState<Set<number>>(new Set());

  const filtered = props.lines.filter((line) => {
    if (level !== "all" && line.level !== level && !(level === "error" && line.level === "critical")) {
      return false;
    }
    if (!query.trim()) return true;
    return line.message.toLowerCase().includes(query.trim().toLowerCase());
  });
  const shown = filtered.slice(-60);

  function toggle(index: number) {
    setExpanded((previous) => {
      const next = new Set(previous);
      if (next.has(index)) next.delete(index);
      else next.add(index);
      return next;
    });
  }

  return (
    <BlockShell
      icon={<Terminal />}
      title="لاگ‌های پروژه"
      meta={
        <>
          <span>{fa(props.count)} خط</span>
          <span>{faMinutes(props.range_minutes)}</span>
          <DemoBadge live={!props.simulated} />
        </>
      }
      actions={
        <CopyButton
          text={filtered.map((line) => `${line.datetime ?? ""} [${line.level}] ${line.message}`).join("\n")}
          label="کپی لاگ‌ها"
        />
      }
    >
      <div className="space-y-3">
        <div className="flex flex-col gap-2 sm:flex-row">
          <div className="relative flex-1">
            <label htmlFor="log-search" className="sr-only">
              جست‌وجو در لاگ‌ها
            </label>
            <Search
              className="pointer-events-none absolute top-1/2 start-2.5 size-3.5 -translate-y-1/2 text-muted-foreground"
              aria-hidden
            />
            <input
              id="log-search"
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              placeholder="جست‌وجو در متن لاگ…"
              className="h-8 w-full rounded-field border border-input bg-background/40 ps-8 pe-2.5 text-[12px] outline-none transition-colors focus:border-brand/50"
            />
          </div>
          <div className="relative">
            <label htmlFor="log-level" className="sr-only">
              فیلتر سطح
            </label>
            <Filter
              className="pointer-events-none absolute top-1/2 start-2.5 size-3.5 -translate-y-1/2 text-muted-foreground"
              aria-hidden
            />
            <select
              id="log-level"
              value={level}
              onChange={(event) => setLevel(event.target.value)}
              className="h-8 w-full appearance-none rounded-field border border-input bg-background/40 ps-8 pe-8 text-[12px] outline-none sm:w-36"
            >
              <option value="all">همه سطوح</option>
              <option value="error">خطا / بحرانی</option>
              <option value="warning">هشدار</option>
              <option value="info">اطلاع</option>
            </select>
          </div>
        </div>

        {props.flagged_instruction_lines > 0 && (
          <Notice tone="warning">
            {fa(props.flagged_instruction_lines)} خط حاوی متن شبیه دستور بود؛ به‌عنوان داده
            غیرقابل‌اعتماد خنثی شد و هیچ دستوری از لاگ اجرا نمی‌شود.
          </Notice>
        )}

        <ul className="max-h-[340px] space-y-0.5 overflow-y-auto rounded-field border border-border bg-background/40 p-2">
          {shown.map((line, index) => {
            const isOpen = expanded.has(index);
            return (
              <li key={`${line.datetime}-${index}`} className="rounded-control px-1.5 py-1 hover:bg-muted/40">
                <div className="flex items-start gap-2">
                  <span className="code-block mt-1.5 w-[52px] shrink-0 text-[9.5px] text-muted-foreground/60" dir="ltr">
                    {line.datetime ? line.datetime.slice(11, 19) : "—"}
                  </span>
                  <span
                    className={cn(
                      "mt-1 w-10 shrink-0 text-[9.5px] font-medium",
                      LEVEL_TONE[line.level] ?? "text-muted-foreground",
                    )}
                  >
                    {LEVEL_FA[line.level] ?? line.level}
                  </span>
                  <button
                    type="button"
                    onClick={() => toggle(index)}
                    className={cn(
                      "code-block min-w-0 flex-1 cursor-pointer text-start text-[11.5px] leading-6 transition-colors",
                      !isOpen && "line-clamp-3",
                    )}
                    aria-expanded={isOpen}
                    title={isOpen ? "جمع کردن" : "نمایش کامل"}
                  >
                    {line.message}
                  </button>
                  {line.flagged && (
                    <ShieldAlert className="mt-1 size-3.5 shrink-0 text-warning" aria-label="متن مشکوک" />
                  )}
                </div>
              </li>
            );
          })}
          {shown.length === 0 && (
            <li className="py-8 text-center text-[12px] text-muted-foreground">
              با این فیلتر خطی پیدا نشد.
            </li>
          )}
        </ul>
        <p className="text-[10.5px] leading-5 text-muted-foreground">
          لاگ‌ها داده غیرقابل‌اعتمادند: متن آن‌ها فقط نمایش داده می‌شود و هیچ دستوری اجرا نمی‌شود.
        </p>
      </div>
    </BlockShell>
  );
}

export function MetricsPanelBlock({ props }: { props: MetricsPanelProps }) {
  return (
    <BlockShell
      icon={<FileSearch />}
      title="مصرف منابع"
      meta={
        <>
          <span className="code-block" dir="ltr">
            {props.project}
          </span>
          <span>{faMinutes(props.range_minutes)}</span>
          <span>{props.source}</span>
          <DemoBadge live={!props.simulated} />
        </>
      }
    >
      <div className="space-y-4">
        <div className="grid gap-4 lg:grid-cols-2">
          <MetricChart series={props.cpu} title="CPU" />
          <MetricChart series={props.memory} title="RAM" />
        </div>
        <DataGrid columns={3}>
          <MetaItem label="میانگین CPU" value={props.cpu.available ? `${faNumber(props.cpu.average)}٪` : "ناموجود"} />
          <MetaItem label="میانگین RAM" value={props.memory.available ? `${faNumber(props.memory.average)}٪` : "ناموجود"} />
          <MetaItem label="بیشینه CPU" value={props.cpu.available ? `${faNumber(props.cpu.maximum)}٪` : "ناموجود"} />
        </DataGrid>
        {(!props.cpu.available || !props.memory.available) && (
          <Notice tone="warning">
            داده ناموجود با عدد صفر نمایش داده نمی‌شود. {props.cpu.unavailable_reason || props.memory.unavailable_reason}
          </Notice>
        )}
      </div>
    </BlockShell>
  );
}

export function EvidenceSummary({ props }: { props: EvidenceListProps }) {
  return (
    <div className="flex flex-wrap items-center gap-2 text-[11px] text-muted-foreground">
      <AlertTriangle className="size-3.5" />
      <span>
        {fa(props.total)} سند — {statusFa("recorded")}
      </span>
    </div>
  );
}
