import * as React from "react";
import { ArrowUp, Square } from "lucide-react";
import { cn } from "@/lib/cn";
import { fa } from "@/lib/format";

export interface PromptInputProps {
  value: string;
  onChange: (value: string) => void;
  onSubmit: (value: string) => void;
  onStop?: () => void;
  loading?: boolean;
  canStop?: boolean;
  disabled?: boolean;
  placeholder?: string;
  tools?: React.ReactNode;
  className?: string;
  maxLength?: number;
}

/**
 * Composer: auto-growing textarea, Enter sends, Shift+Enter inserts a newline,
 * IME composition never submits. The send control sits at the inline-end.
 */
export function PromptInput({
  value,
  onChange,
  onSubmit,
  onStop,
  loading = false,
  canStop = false,
  disabled = false,
  placeholder = "مشکل یا درخواستت را بنویس…",
  tools,
  className,
  maxLength = 4000,
}: PromptInputProps) {
  const ref = React.useRef<HTMLTextAreaElement>(null);

  React.useEffect(() => {
    const el = ref.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = `${Math.min(el.scrollHeight, 200)}px`;
  }, [value]);

  function submit() {
    const clean = value.trim();
    if (!clean || loading || disabled) return;
    onSubmit(clean);
  }

  return (
    <div
      className={cn(
        "rounded-surface border border-border bg-card p-2.5 shadow-surface transition-colors duration-(--motion) focus-within:border-brand/45",
        className,
      )}
    >
      <label htmlFor="composer" className="sr-only">
        پیام به LiaraPilot
      </label>
      <textarea
        id="composer"
        ref={ref}
        rows={1}
        value={value}
        maxLength={maxLength}
        disabled={disabled}
        placeholder={placeholder}
        aria-describedby="composer-hint"
        onChange={(event) => onChange(event.target.value)}
        onKeyDown={(event) => {
          if (
            event.key === "Enter" &&
            !event.shiftKey &&
            !event.nativeEvent.isComposing
          ) {
            event.preventDefault();
            submit();
          }
        }}
        className="block max-h-[200px] w-full resize-none bg-transparent px-1 text-[15px] leading-8 outline-none placeholder:text-muted-foreground/65 disabled:opacity-60"
      />
      <div className="mt-1 flex items-end justify-between gap-2">
        <div className="flex min-w-0 items-center gap-1.5">{tools}</div>
        <div className="flex items-center gap-2">
          <span className="hidden text-[10px] text-muted-foreground/70 sm:inline" aria-hidden>
            {fa(value.length)}/{fa(maxLength)}
          </span>
          {loading && canStop && onStop ? (
            <button
              type="button"
              onClick={onStop}
              aria-label="توقف عملیات"
              className="flex size-9 cursor-pointer items-center justify-center rounded-control bg-foreground text-background transition-opacity hover:opacity-90"
            >
              <Square className="size-3.5 fill-current" />
            </button>
          ) : loading ? (
            <span
              className="flex size-9 items-center justify-center rounded-control border border-border text-muted-foreground"
              aria-label="در حال پردازش"
            >
              <span className="size-3.5 animate-spin rounded-full border-2 border-muted-foreground/30 border-t-foreground" />
            </span>
          ) : (
            <button
              type="button"
              onClick={submit}
              disabled={!value.trim() || disabled}
              aria-label="ارسال پیام"
              className="flex size-9 cursor-pointer items-center justify-center rounded-control bg-primary text-primary-foreground transition-opacity hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-35"
            >
              <ArrowUp className="size-4" />
            </button>
          )}
        </div>
      </div>
    </div>
  );
}
