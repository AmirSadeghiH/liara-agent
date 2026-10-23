import * as React from "react";
import { Boxes, Check, FolderSearch, Search } from "lucide-react";
import type { ProjectOverviewProps, ProjectPickerProps } from "@/lib/types";
import { BlockShell } from "@/components/ui/BlockShell";
import { Badge, DemoBadge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { DataGrid, MetaItem, Notice } from "./primitives";
import { cn } from "@/lib/cn";
import { statusFa } from "@/lib/format";

export function ProjectPickerBlock({
  props,
  onSelectProject,
}: {
  props: ProjectPickerProps;
  onSelectProject?: (project: string) => void | Promise<void>;
}) {
  const [query, setQuery] = React.useState("");
  const [selected, setSelected] = React.useState<string | null>(null);
  const [busy, setBusy] = React.useState<string | null>(null);
  const filtered = props.projects.filter((project) =>
    project.name.toLowerCase().includes(query.trim().toLowerCase()),
  );

  async function choose(name: string) {
    if (busy) return;
    setBusy(name);
    setSelected(name);
    try {
      await onSelectProject?.(name);
    } finally {
      setBusy(null);
    }
  }

  return (
    <BlockShell
      icon={<FolderSearch />}
      title="انتخاب پروژه"
      meta={<span>{props.reason ?? "پروژه هدف مشخص نیست."}</span>}
    >
      <div className="space-y-3">
        {props.allow_search && (
          <div className="relative">
            <label htmlFor="project-search" className="sr-only">
              جست‌وجوی پروژه
            </label>
            <Search
              className="pointer-events-none absolute top-1/2 start-3 size-3.5 -translate-y-1/2 text-muted-foreground"
              aria-hidden
            />
            <input
              id="project-search"
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              placeholder="جست‌وجوی نام پروژه…"
              className="h-9 w-full rounded-field border border-input bg-background/40 ps-9 pe-3 text-[13px] outline-none transition-colors focus:border-brand/50 focus-visible:ring-2 focus-visible:ring-ring"
            />
          </div>
        )}
        <ul className="max-h-64 space-y-1.5 overflow-y-auto pe-0.5">
          {filtered.map((project) => (
            <li key={project.name}>
              <Button
                variant={selected === project.name ? "secondary" : "outline"}
                className={cn(
                  "h-auto w-full justify-between gap-2 px-3 py-2 text-start",
                  selected === project.name && "border-brand/40",
                )}
                onClick={() => choose(project.name)}
                disabled={busy !== null}
              >
                <span className="flex min-w-0 flex-col items-start">
                  <span className="code-block text-[13px] font-medium" dir="ltr">
                    {project.name}
                  </span>
                  <span className="text-[10.5px] font-normal text-muted-foreground">
                    {project.type || "نوع نامشخص"}
                    {project.status ? ` · ${statusFa(project.status)}` : ""}
                    {project.is_deployed ? " · منتشرشده" : ""}
                  </span>
                </span>
                {busy === project.name ? (
                  <span className="size-3.5 animate-spin rounded-full border-2 border-muted-foreground/30 border-t-foreground" />
                ) : selected === project.name ? (
                  <Check className="text-success" />
                ) : null}
              </Button>
            </li>
          ))}
          {filtered.length === 0 && (
            <li className="rounded-field border border-dashed border-border px-3 py-6 text-center text-[12px] text-muted-foreground">
              پروژه‌ای با این نام پیدا نشد.
            </li>
          )}
        </ul>
        <p className="text-[11px] leading-5 text-muted-foreground">
          فقط پروژه‌های واقعی حساب قابل انتخاب‌اند؛ پس از انتخاب، درخواست قبلی دوباره پرسیده
          نمی‌شود.
        </p>
      </div>
    </BlockShell>
  );
}

export function ProjectOverviewBlock({ props }: { props: ProjectOverviewProps }) {
  return (
    <BlockShell
      icon={<Boxes />}
      title="پروژه فعال"
      tone={props.simulated ? "warning" : "default"}
      meta={
        <>
          <span className="code-block" dir="ltr">
            {props.project}
          </span>
          <DemoBadge live={!props.simulated} />
        </>
      }
    >
      <div className="space-y-3">
        <DataGrid columns={4}>
          <MetaItem label="نوع" value={props.type || "نامشخص"} />
          <MetaItem label="وضعیت" value={statusFa(props.status)} />
          <MetaItem label="انتشار" value={props.is_deployed ? "منتشرشده" : "منتشرنشده"} />
          <MetaItem label="پلن" value={props.plan_id || "—"} mono />
        </DataGrid>
        {props.notice && <Notice tone="warning">{props.notice}</Notice>}
      </div>
    </BlockShell>
  );
}

export function ModeLabel({ mode }: { mode: string }) {
  return <Badge variant={mode === "live" ? "destructive" : "warning"}>{mode === "live" ? "LIVE" : "DEMO"}</Badge>;
}
