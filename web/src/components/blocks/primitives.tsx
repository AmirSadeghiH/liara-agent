import * as React from "react";
import { AlertTriangle, Check, CircleSlash, Clock, LoaderCircle, X } from "lucide-react";
import { cn } from "@/lib/cn";
import { statusFa } from "@/lib/format";
import { Badge } from "@/components/ui/Badge";

export function MetaItem({
  label,
  value,
  mono = false,
}: {
  label: string;
  value: React.ReactNode;
  mono?: boolean;
}) {
  return (
    <div className="min-w-0">
      <dt className="text-[11px] text-muted-foreground">{label}</dt>
      <dd
        className={cn(
          "mt-0.5 break-words text-[13px] leading-6",
          mono && "code-block text-[11.5px] [overflow-wrap:anywhere]",
        )}
        {...(mono ? { dir: "ltr" } : {})}
      >
        {value}
      </dd>
    </div>
  );
}

export function DataGrid({
  children,
  columns = 3,
}: {
  children: React.ReactNode;
  columns?: 2 | 3 | 4;
}) {
  const cols =
    columns === 2
      ? "sm:grid-cols-2"
      : columns === 4
        ? "sm:grid-cols-2 lg:grid-cols-4"
        : "sm:grid-cols-3";
  return <dl className={cn("grid grid-cols-1 gap-x-5 gap-y-3", cols)}>{children}</dl>;
}

export function Notice({
  children,
  tone = "info",
}: {
  children: React.ReactNode;
  tone?: "info" | "warning" | "danger" | "success";
}) {
  const styles = {
    info: "border-border bg-muted/40 text-muted-foreground",
    warning: "border-warning/25 bg-warning/5 text-warning",
    danger: "border-destructive/25 bg-destructive/5 text-destructive",
    success: "border-success/25 bg-success/5 text-success",
  }[tone];
  return (
    <div className={cn("rounded-field border px-3 py-2 text-[12px] leading-6", styles)}>
      {children}
    </div>
  );
}

export function statusVariant(
  status: string | null | undefined,
): "success" | "warning" | "brand" | "destructive" | "secondary" {
  switch (status) {
    case "completed":
    case "passed":
    case "verified":
    case "approved":
    case "success":
    case "prepared":
      return "success";
    case "failed":
    case "rejected":
    case "expired":
    case "error":
      return "destructive";
    case "waiting_for_approval":
    case "needs_human":
    case "pending":
    case "unverified":
    case "skipped":
      return "warning";
    case "running":
    case "testing":
    case "deploying":
    case "verifying":
    case "queued":
    case "preparing":
      return "brand";
    default:
      return "secondary";
  }
}

export function StepIcon({ status }: { status: string }) {
  const variant = statusVariant(status);
  if (variant === "success") return <Check className="size-3.5 text-success" />;
  if (variant === "destructive") return <X className="size-3.5 text-destructive" />;
  if (variant === "warning") return <AlertTriangle className="size-3.5 text-warning" />;
  if (variant === "brand")
    return <LoaderCircle className="size-3.5 animate-spin text-brand" />;
  return <CircleSlash className="size-3.5 text-muted-foreground/60" />;
}

export function StatusPill({
  status,
  label,
  className,
}: {
  status: string | null | undefined;
  label?: string;
  className?: string;
}) {
  return (
    <Badge variant={statusVariant(status)} dot className={className}>
      {label ?? statusFa(status)}
    </Badge>
  );
}

export function StepList({
  steps,
  compact = false,
}: {
  steps: Array<{
    key: string;
    label: string;
    status: string;
    summary?: string | null;
    reference?: string | null;
    error?: string | null;
  }>;
  compact?: boolean;
}) {
  return (
    <ol className="relative ms-1 space-y-0">
      {steps.map((step, index) => (
        <li key={`${step.key}-${index}`} className="relative flex gap-3 pb-4 last:pb-0">
          {index < steps.length - 1 && (
            <span
              className="absolute top-5 start-[6px] h-[calc(100%-1.25rem)] w-px bg-border"
              aria-hidden
            />
          )}
          <span className="relative z-10 mt-1 flex size-[13px] shrink-0 items-center justify-center rounded-full bg-background">
            <StepIcon status={step.status} />
          </span>
          <div className="min-w-0 flex-1">
            <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
              <span className="text-[13px] font-medium">{step.label}</span>
              <Badge variant={statusVariant(step.status)} className="text-[10.5px]">
                {statusFa(step.status)}
              </Badge>
            </div>
            {!compact && step.summary && (
              <p className="mt-0.5 text-[12px] leading-6 text-muted-foreground">{step.summary}</p>
            )}
            {step.reference && (
              <p className="code-block mt-0.5 text-[10.5px] text-muted-foreground/80" dir="ltr">
                {step.reference}
              </p>
            )}
            {step.error && (
              <p className="mt-0.5 text-[11.5px] text-destructive">{step.error}</p>
            )}
          </div>
        </li>
      ))}
    </ol>
  );
}

export function Section({
  title,
  children,
  className,
}: {
  title: string;
  children: React.ReactNode;
  className?: string;
}) {
  return (
    <section className={cn("space-y-1.5", className)}>
      <h4 className="text-[11px] font-medium text-muted-foreground">{title}</h4>
      <div className="text-[13px] leading-7">{children}</div>
    </section>
  );
}

export function MonoId({ children }: { children: React.ReactNode }) {
  return (
    <span className="code-block inline-block max-w-full truncate align-bottom text-[10.5px] text-muted-foreground">
      <span dir="ltr">{children}</span>
    </span>
  );
}

export function ClockIcon() {
  return <Clock className="size-3" />;
}
