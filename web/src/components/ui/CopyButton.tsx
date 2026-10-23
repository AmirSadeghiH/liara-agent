import * as React from "react";
import { Check, Copy } from "lucide-react";
import { cn } from "@/lib/cn";

export function CopyButton({
  text,
  label = "کپی",
  className,
  onCopy,
}: {
  text: string;
  label?: string;
  className?: string;
  onCopy?: (text: string, label?: string) => void;
}) {
  const [copied, setCopied] = React.useState(false);

  async function copy() {
    try {
      await navigator.clipboard.writeText(text);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1600);
    } catch {
      setCopied(false);
    }
    onCopy?.(text, label);
  }

  return (
    <button
      type="button"
      onClick={copy}
      className={cn(
        "inline-flex h-7 cursor-pointer items-center gap-1 rounded-control px-2 text-[11px] text-muted-foreground transition-colors duration-(--motion) hover:bg-accent hover:text-foreground",
        className,
      )}
      aria-label={`${label} ${text.length > 40 ? "محتوا" : text}`}
    >
      {copied ? <Check className="size-3 text-success" /> : <Copy className="size-3" />}
      {copied ? "کپی شد" : label}
    </button>
  );
}
