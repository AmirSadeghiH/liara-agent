import * as React from "react";
import { Sparkles } from "lucide-react";
import type { BlockActions, ConversationMessage } from "@/lib/types";
import { BlockRenderer } from "@/components/blocks/registry";
import { CopyButton } from "@/components/ui/CopyButton";
import { DemoBadge } from "@/components/ui/Badge";
import { faTimeAgo } from "@/lib/format";
import { cn } from "@/lib/cn";

export function MessageItem({
  message,
  actions,
}: {
  message: ConversationMessage;
  actions: BlockActions;
}) {
  const [copied, setCopied] = React.useState(false);

  async function copyText() {
    try {
      await navigator.clipboard.writeText(message.text);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1500);
      actions.onCopy?.(message.text, "متن پیام");
    } catch {
      setCopied(false);
    }
  }

  if (message.role === "user") {
    return (
      <article className="flex justify-start" aria-label="پیام شما">
        <div className="max-w-[88%] rounded-surface rounded-ss-sm bg-secondary px-4 py-2.5 text-[14px] leading-8 text-secondary-foreground">
          <p className="whitespace-pre-wrap break-words">{message.text}</p>
          <div className="mt-1 flex justify-end">
            <span className="text-[10px] text-muted-foreground/70">{faTimeAgo(message.created_at)}</span>
          </div>
        </div>
      </article>
    );
  }

  const simulated =
    (message.blocks as Array<{ props?: { simulated?: boolean } }>).some(
      (block) => block?.props?.simulated === true,
    );

  return (
    <article className="flex gap-2.5 sm:gap-3" aria-label="پاسخ LiaraPilot">
      <span
        className="mt-0.5 flex size-7 shrink-0 items-center justify-center rounded-full border border-border bg-card text-brand"
        aria-hidden
      >
        <Sparkles className="size-3.5" />
      </span>
      <div className="min-w-0 flex-1 space-y-3">
        <div className="group relative">
          <p className="whitespace-pre-wrap break-words text-[14px] leading-8">{message.text}</p>
          <div className="mt-1 flex flex-wrap items-center gap-2 text-[10px] text-muted-foreground/70">
            <span>{faTimeAgo(message.created_at)}</span>
            {message.data?.mode === "demo" && simulated && <DemoBadge />}
            <button
              type="button"
              onClick={copyText}
              className="cursor-pointer rounded px-1 text-[10px] text-muted-foreground/70 transition-colors hover:bg-accent hover:text-foreground"
            >
              {copied ? "کپی شد" : "کپی متن"}
            </button>
            {typeof message.workflow_id === "string" && (
              <>
                <span className="text-muted-foreground/40">·</span>
                <span className="code-block text-[9.5px] opacity-80" dir="ltr" title="شناسه گردش‌کار">
                  {message.workflow_id}
                </span>
                <CopyButton
                  text={message.workflow_id}
                  label="کپی شناسه"
                  className="h-5 px-1 text-[9.5px] opacity-80"
                />
              </>
            )}
          </div>
        </div>
        <BlockRenderer blocks={message.blocks} actions={actions} />
      </div>
    </article>
  );
}

export function TypingIndicator({ label = "LiaraPilot در حال بررسی است…" }: { label?: string }) {
  return (
    <div className="flex items-center gap-2.5" role="status" aria-live="polite">
      <span className="flex size-7 items-center justify-center rounded-full border border-border bg-card text-brand">
        <Sparkles className="size-3.5" />
      </span>
      <span className="flex items-center gap-2 text-[12px] text-muted-foreground">
        <span className="flex gap-1" aria-hidden>
          <span className="size-1.5 animate-pulse rounded-full bg-brand [animation-delay:0ms]" />
          <span className="size-1.5 animate-pulse rounded-full bg-brand [animation-delay:150ms]" />
          <span className="size-1.5 animate-pulse rounded-full bg-brand [animation-delay:300ms]" />
        </span>
        {label}
      </span>
    </div>
  );
}

export function MessageSkeleton() {
  return (
    <div className="space-y-3" aria-hidden>
      {[0, 1, 2].map((index) => (
        <div
          key={index}
          className={cn(
            "h-20 animate-pulse rounded-surface border border-border bg-card/60",
            index === 1 && "ms-auto w-3/4",
          )}
        />
      ))}
    </div>
  );
}
