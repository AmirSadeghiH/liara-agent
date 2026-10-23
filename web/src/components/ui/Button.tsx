import * as React from "react";
import { cn } from "@/lib/cn";

type Variant = "default" | "secondary" | "outline" | "ghost" | "brand" | "destructive";
type Size = "sm" | "md" | "lg" | "icon";

const variants: Record<Variant, string> = {
  default:
    "bg-primary text-primary-foreground hover:bg-primary/90 shadow-control active:shadow-press",
  secondary:
    "bg-secondary text-secondary-foreground hover:bg-secondary/80 border border-border shadow-control active:shadow-press",
  outline:
    "border border-input bg-transparent hover:bg-accent hover:text-accent-foreground active:shadow-press",
  ghost: "hover:bg-accent hover:text-accent-foreground",
  brand:
    "bg-brand text-brand-foreground hover:bg-brand/90 shadow-control active:shadow-press font-semibold",
  destructive:
    "bg-destructive text-white hover:bg-destructive/90 shadow-control active:shadow-press",
};

const sizes: Record<Size, string> = {
  sm: "h-8 px-3 text-[13px] gap-1.5 rounded-control",
  md: "h-10 px-4 text-sm gap-2 rounded-control",
  lg: "h-12 px-6 text-base gap-2.5 rounded-control",
  icon: "size-10 rounded-control",
};

export interface ButtonProps extends React.ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: Variant;
  size?: Size;
}

export function Button({
  className,
  variant = "secondary",
  size = "md",
  type = "button",
  ...props
}: ButtonProps) {
  return (
    <button
      type={type}
      className={cn(
        "inline-flex shrink-0 cursor-pointer items-center justify-center whitespace-nowrap font-medium",
        "transition-[color,background-color,border-color,transform,opacity] duration-(--motion) ease-motion",
        "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background",
        "disabled:pointer-events-none disabled:opacity-45 active:[transform:var(--press)]",
        "[&_svg]:pointer-events-none [&_svg]:size-4 [&_svg]:shrink-0",
        variants[variant],
        sizes[size],
        className,
      )}
      {...props}
    />
  );
}
