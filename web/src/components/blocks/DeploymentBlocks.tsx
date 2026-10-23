import * as React from "react";
import { Activity, HeartPulse, Rocket, ServerCog } from "lucide-react";
import type {
  DeploymentTimelineProps,
  HealthCheckProps,
  ReleaseStatusProps,
} from "@/lib/types";
import { BlockShell } from "@/components/ui/BlockShell";
import { Badge, DemoBadge } from "@/components/ui/Badge";
import { CopyButton } from "@/components/ui/CopyButton";
import { DataGrid, MetaItem, Notice, Section, StatusPill, StepList } from "./primitives";
import { fa, faDateTime, statusFa } from "@/lib/format";

export function DeploymentTimelineBlock({ props }: { props: DeploymentTimelineProps }) {
  return (
    <BlockShell
      icon={<Rocket />}
      title="خط زمانی انتشار"
      meta={
        <>
          <StatusPill status={props.status} />
          <span className="code-block" dir="ltr">
            {props.project}
          </span>
          <DemoBadge live={!props.simulated} />
        </>
      }
      actions={props.release_id ? <CopyButton text={props.release_id} label="کپی Release" /> : null}
    >
      <div className="space-y-3">
        <StepList steps={props.steps} />
        <DataGrid columns={3}>
          <MetaItem label="شناسه سورس" value={props.source_id || "—"} mono />
          <MetaItem label="شناسه Release" value={props.release_id || "—"} mono />
          <MetaItem label="پورت" value={props.port ? fa(props.port) : "—"} />
        </DataGrid>
        <Notice tone="warning">
          موفقیت ارسال سورس، ساخت Release و تأیید سلامت سه وضعیت جدا هستند و در یک «موفق شد»
          ادغام نمی‌شوند. وضعیت سلامت پایین‌تر گزارش می‌شود.
        </Notice>
      </div>
    </BlockShell>
  );
}

export function ReleaseStatusBlock({ props }: { props: ReleaseStatusProps }) {
  return (
    <BlockShell
      icon={<ServerCog />}
      title="وضعیت Release"
      meta={
        <>
          <span className="code-block" dir="ltr">
            {props.project}
          </span>
          <DemoBadge live={!props.simulated} />
        </>
      }
    >
      <DataGrid columns={4}>
        <MetaItem label="شناسه Release" value={props.release_id || "—"} mono />
        <MetaItem label="وضعیت Release" value={statusFa(props.release_state)} />
        <MetaItem label="شناسه سورس" value={props.source_id || "—"} mono />
        <MetaItem label="پورت" value={props.port ? fa(props.port) : "—"} />
      </DataGrid>
      {props.release_state && ["failed", "error"].includes(props.release_state.toLowerCase()) && (
        <Notice tone="danger">ساخت Release ناموفق بوده است؛ انتشار کامل تلقی نمی‌شود.</Notice>
      )}
    </BlockShell>
  );
}

export function HealthCheckBlock({ props }: { props: HealthCheckProps }) {
  const tone = props.status === "verified" ? "success" : props.status === "failed" ? "danger" : "warning";
  return (
    <BlockShell
      icon={<HeartPulse />}
      title="بررسی سلامت"
      tone={tone}
      meta={
        <>
          <Badge
            variant={props.status === "verified" ? "success" : props.status === "failed" ? "destructive" : "warning"}
            dot
          >
            {props.status === "verified"
              ? "تأییدشده"
              : props.status === "failed"
                ? "ناموفق"
                : "تأییدنشده"}
          </Badge>
          <DemoBadge live={!props.simulated} />
        </>
      }
    >
      <div className="space-y-3">
        <Section title="نتیجه">
          {props.status === "verified" && (
            <p className="text-success">بررسی سلامت با پاسخ مورد انتظار انجام شد.</p>
          )}
          {props.status === "failed" && (
            <p className="text-destructive">Health Check ناموفق بود؛ انتشار سالم تلقی نمی‌شود.</p>
          )}
          {props.status === "unverified" && (
            <p className="text-warning">
              Health Check قابل اجرا نبود؛ بنابراین وضعیت «تأییدنشده» است، نه «سالم».
            </p>
          )}
        </Section>
        <DataGrid columns={4}>
          <MetaItem label="URL" value={props.url || "تنظیم نشده"} mono />
          <MetaItem label="کد پاسخ" value={props.status_code === null ? "—" : fa(props.status_code)} />
          <MetaItem label="زمان بررسی" value={faDateTime(props.checked_at)} />
          <MetaItem label="وضعیت" value={statusFa(props.status)} />
        </DataGrid>
        {props.reason && <Notice tone={tone === "success" ? "info" : tone}>{props.reason}</Notice>}
        {!props.verified && (
          <p className="text-[10.5px] leading-5 text-muted-foreground">
            برای تأیید واقعی، DEPLOY_HEALTHCHECK_URL باید تنظیم شده و پاسخ مورد انتظار برگردد.
          </p>
        )}
      </div>
    </BlockShell>
  );
}

export function ActivityLabel({ children }: { children: React.ReactNode }) {
  return (
    <span className="inline-flex items-center gap-1 text-[11px] text-muted-foreground">
      <Activity className="size-3" />
      {children}
    </span>
  );
}
