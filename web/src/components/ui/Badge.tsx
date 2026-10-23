import * as React from "react";
import { cn } from "@/lib/cn";

type Variant =
  | "default"
  | "secondary"
  | "outline"
  | "success"
  | "warning"
  | "brand"
  | "destructive";

const variants: Record<Variant, string> = {
  default: "text-foreground",
  secondary: "text-muted-foreground",
  outline: "text-foreground/60",
  success: "text-success",
  warning: "text-warning",
  brand: "text-brand",
  destructive: "text-destructive",
};

const dots: Record<Variant, string> = {
  default: "bg-foreground",
  secondary: "bg-muted-foreground",
  outline: "bg-foreground/40",
  success: "bg-success",
  warning: "bg-warning",
  brand: "bg-brand",
  destructive: "bg-destructive",
};

export function Badge({
  className,
  variant = "secondary",
  dot = false,
  ...props
}: React.HTMLAttributes<HTMLSpanElement> & { variant?: Variant; dot?: boolean }) {
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1.5 whitespace-nowrap text-xs font-medium leading-6",
        variants[variant],
        className,
      )}
      {...props}
    >
      {dot && <span className={cn("size-1.5 rounded-full", dots[variant])} aria-hidden />}
      {props.children}
    </span>
  );
}

/** Demo / simulated marker shown wherever simulated data is rendered. */
export function DemoBadge({ live = false }: { live?: boolean }) {
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1.5 rounded-full border px-2 py-0.5 text-[11px] font-medium leading-5",
        live
          ? "border-destructive/40 text-destructive"
          : "border-warning/40 text-warning",
      )}
      title={live ? "داده از API واقعی لیارا" : "داده شبیه‌سازی‌شده؛ هیچ تغییری در لیارا ثبت نمی‌شود"}
    >
      <span
        className={cn("size-1.5 rounded-full", live ? "bg-destructive" : "bg-warning")}
        aria-hidden
      />
      {live ? "LIVE" : "DEMO / SIMULATED"}
    </span>
  );
}
