import { History, Plus, Settings2, Waypoints, WifiOff } from "lucide-react";
import { Badge, DemoBadge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import type { Mode } from "@/lib/types";

export function ChatHeader({
  mode,
  simulated,
  project,
  pendingCount,
  connected,
  activeWorkflows,
  onNew,
  onHistory,
  onSettings,
}: {
  mode: Mode;
  simulated: boolean;
  project: string | null;
  pendingCount: number;
  connected: boolean;
  activeWorkflows: number;
  onNew: () => void;
  onHistory: () => void;
  onSettings: () => void;
}) {
  return (
    <header className="sticky top-0 z-30 border-b border-border bg-background/95 backdrop-blur-sm">
      <div className="mx-auto flex h-14 w-full max-w-4xl items-center justify-between gap-3 px-3 sm:px-5">
        <div className="flex min-w-0 items-center gap-2.5">
          <span
            className="flex size-8 shrink-0 items-center justify-center rounded-control border border-brand/35 bg-brand/10 text-brand"
            aria-hidden
          >
            <Waypoints className="size-4" />
          </span>
          <div className="min-w-0 leading-tight">
            <div className="flex items-center gap-2">
              <span className="text-[14px] font-semibold">LiaraPilot</span>
              <Badge
                variant={mode === "demo" ? "warning" : "destructive"}
                className="text-[9.5px] tracking-normal"
              >
                {mode === "demo" ? "DEMO" : "LIVE"}
              </Badge>
            </div>
            <p className="hidden text-[10px] text-muted-foreground sm:block">
              دستیار زیرساخت لیارا — گفت‌وگو، شواهد، تأیید، انتشار
            </p>
          </div>
        </div>

        <div className="flex items-center gap-1.5">
          {!connected && (
            <span
              className="inline-flex items-center gap-1 rounded-full border border-destructive/30 px-2 py-0.5 text-[10px] text-destructive"
              role="status"
            >
              <WifiOff className="size-3" />
              قطع ارتباط
            </span>
          )}
          {project && (
            <span
              className="hidden max-w-[150px] truncate rounded-full border border-border px-2.5 py-0.5 text-[10.5px] text-muted-foreground md:inline-block"
              title={`پروژه فعال: ${project}`}
            >
              <span className="code-block" dir="ltr">
                {project}
              </span>
            </span>
          )}
          {activeWorkflows > 0 && (
            <Badge variant="brand" dot className="hidden sm:inline-flex">
              {activeWorkflows} در حال اجرا
            </Badge>
          )}
          {pendingCount > 0 && (
            <Badge variant="warning" dot className="hidden sm:inline-flex">
              {pendingCount} در انتظار تأیید
            </Badge>
          )}
          {simulated && <span className="hidden lg:inline-flex"><DemoBadge /></span>}
          <Button size="icon" variant="ghost" aria-label="گفت‌وگوی جدید" title="گفت‌وگوی جدید" onClick={onNew}>
            <Plus />
          </Button>
          <Button size="icon" variant="ghost" aria-label="تاریخچه گفت‌وگوها" title="تاریخچه" onClick={onHistory}>
            <History />
          </Button>
          <Button size="icon" variant="ghost" aria-label="تنظیمات اتصال" title="تنظیمات" onClick={onSettings}>
            <Settings2 />
          </Button>
        </div>
      </div>
    </header>
  );
}
