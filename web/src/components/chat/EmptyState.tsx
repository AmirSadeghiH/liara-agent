import {
  Activity,
  ArrowLeft,
  Gauge,
  Rocket,
  TriangleAlert,
} from "lucide-react";
import type { Mode } from "@/lib/types";
import { Badge } from "@/components/ui/Badge";

const SUGGESTIONS = [
  {
    text: "وضعیت سایت من را بررسی کن",
    icon: Activity,
  },
  {
    text: "چرا اپلیکیشن خطای ۵۰۰ می‌دهد؟",
    icon: TriangleAlert,
  },
  {
    text: "مصرف CPU و RAM را بررسی کن",
    icon: Gauge,
  },
  {
    text: "نسخه جدید را برای دیپلوی آماده کن",
    icon: Rocket,
  },
];

export function EmptyState({
  mode,
  project,
  onSuggestion,
  disabled,
}: {
  mode: Mode;
  project: string | null;
  onSuggestion: (text: string) => void;
  disabled?: boolean;
}) {
  return (
    <div className="mx-auto flex w-full max-w-2xl flex-col items-start justify-center gap-7 py-10 sm:py-16">
      <div className="space-y-3">
        <Badge variant="brand" className="text-[10.5px]">
          {mode === "demo" ? "DEMO / SIMULATED" : "LIVE"}
          {project ? (
            <span className="ms-1 text-muted-foreground">
              · پروژه <span className="code-block" dir="ltr">{project}</span>
            </span>
          ) : null}
        </Badge>
        <h1 className="text-[26px] leading-[1.35] sm:text-[32px]">
          چه چیزی را برایت بررسی کنم؟
        </h1>
        <p className="max-w-[52ch] text-[13.5px] leading-7 text-muted-foreground">
          درخواستت را بنویس؛ شواهد واقعی را جمع می‌کنم، علت را با اطمینان مشخص می‌کنم و
          نتیجه را همان‌جا نشان می‌دهم. هیچ عملیات حساسی بدون تأیید تو اجرا نمی‌شود.
        </p>
      </div>

      <div className="grid w-full grid-cols-1 gap-2 sm:grid-cols-2">
        {SUGGESTIONS.map(({ text, icon: Icon }) => (
          <button
            key={text}
            type="button"
            disabled={disabled}
            onClick={() => onSuggestion(text)}
            className="group flex min-h-11 w-full cursor-pointer items-center justify-between gap-3 rounded-surface border border-border bg-card px-3.5 py-3 text-start text-[12.5px] shadow-surface transition-[border-color,background-color,transform] duration-(--motion) ease-motion hover:border-brand/35 hover:bg-card/80 active:[transform:var(--press)] disabled:pointer-events-none disabled:opacity-50"
          >
            <span className="flex items-center gap-2.5">
              <Icon className="size-4 text-brand" />
              {text}
            </span>
            <ArrowLeft className="size-3.5 shrink-0 text-muted-foreground/40 transition-colors group-hover:text-brand" />
          </button>
        ))}
      </div>

      <p className="text-[10.5px] leading-5 text-muted-foreground/70">
        این پیشنهادها فقط نقطه شروع‌اند؛ می‌توانی هر درخواست دیگری هم بنویسی. در حالت DEMO
        هیچ تغییری در لیارا ثبت نمی‌شود.
      </p>
    </div>
  );
}
