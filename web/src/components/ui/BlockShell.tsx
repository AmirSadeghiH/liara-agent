import * as React from "react";
import { Card } from "./Card";
import { cn } from "@/lib/cn";

export interface BlockShellProps {
  icon: React.ReactNode;
  title: string;
  meta?: React.ReactNode;
  actions?: React.ReactNode;
  footer?: React.ReactNode;
  tone?: "default" | "warning" | "danger" | "success";
  className?: string;
  children: React.ReactNode;
}

const toneLine: Record<NonNullable<BlockShellProps["tone"]>, string> = {
  default: "",
  warning: "before:bg-warning/70",
  danger: "before:bg-destructive/70",
  success: "before:bg-success/70",
};

/**
 * One consistent frame for every block: a single surface, no card-in-card
 * nesting. Tone is expressed by a hairline at the inline-start edge.
 */
export function BlockShell({
  icon,
  title,
  meta,
  actions,
  footer,
  tone = "default",
  className,
  children,
}: BlockShellProps) {
  return (
    <Card
      className={cn(
        "block-in overflow-hidden",
        tone !== "default" &&
          "before:absolute before:inset-y-0 before:start-0 before:w-0.5 before:rounded-full before:content-['']",
        toneLine[tone],
        className,
      )}
    >
      <header className="flex flex-wrap items-start justify-between gap-2 border-b border-border px-4 py-3 sm:px-5">
        <div className="flex min-w-0 items-start gap-2.5">
          <span className="mt-0.5 text-muted-foreground [&_svg]:size-4" aria-hidden>
            {icon}
          </span>
          <div className="min-w-0">
            <h3 className="text-[15px] font-semibold leading-6">{title}</h3>
            {meta && (
              <div className="mt-0.5 flex flex-wrap items-center gap-x-3 gap-y-1 text-[11px] text-muted-foreground">
                {meta}
              </div>
            )}
          </div>
        </div>
        {actions && <div className="flex shrink-0 flex-wrap items-center gap-1.5">{actions}</div>}
      </header>
      <div className="px-4 py-4 sm:px-5">{children}</div>
      {footer && (
        <footer className="border-t border-border bg-background/20 px-4 py-2.5 text-[11px] text-muted-foreground sm:px-5">
          {footer}
        </footer>
      )}
    </Card>
  );
}
