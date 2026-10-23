import * as React from "react";
import { MessageSquarePlus, Search } from "lucide-react";
import type { Conversation } from "@/lib/types";
import { Drawer } from "@/components/ui/Drawer";
import { Button } from "@/components/ui/Button";
import { Badge } from "@/components/ui/Badge";
import { fa, faTimeAgo } from "@/lib/format";
import { cn } from "@/lib/cn";

export function HistoryDrawer({
  open,
  loading,
  error,
  conversations,
  activeId,
  onClose,
  onSelect,
  onNew,
  onRetry,
}: {
  open: boolean;
  loading: boolean;
  error: string | null;
  conversations: Conversation[];
  activeId: string | null;
  onClose: () => void;
  onSelect: (id: string) => void;
  onNew: () => void;
  onRetry: () => void;
}) {
  const [query, setQuery] = React.useState("");

  React.useEffect(() => {
    if (!open) setQuery("");
  }, [open]);

  const filtered = conversations.filter((conversation) => {
    if (!query.trim()) return true;
    const needle = query.trim().toLowerCase();
    return (
      conversation.title.toLowerCase().includes(needle) ||
      (conversation.project ?? "").toLowerCase().includes(needle)
    );
  });

  return (
    <Drawer
      open={open}
      title="تاریخچه گفت‌وگوها"
      description="گفت‌وگوها و UI Blockهایشان در سرور ذخیره می‌شوند."
      onClose={onClose}
      footer={
        <Button variant="brand" className="w-full" onClick={onNew}>
          <MessageSquarePlus />
          گفت‌وگوی جدید
        </Button>
      }
    >
      <div className="space-y-3">
        <div className="relative">
          <label htmlFor="history-search" className="sr-only">
            جست‌وجوی گفت‌وگو
          </label>
          <Search
            className="pointer-events-none absolute top-1/2 start-2.5 size-3.5 -translate-y-1/2 text-muted-foreground"
            aria-hidden
          />
          <input
            id="history-search"
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder="جست‌وجو…"
            className="h-9 w-full rounded-field border border-input bg-background/40 ps-8 pe-3 text-[12.5px] outline-none"
          />
        </div>

        {loading && (
          <div className="space-y-2" aria-hidden>
            {[0, 1, 2].map((index) => (
              <div key={index} className="h-14 animate-pulse rounded-surface bg-card" />
            ))}
          </div>
        )}
        {error && (
          <div className="rounded-field border border-destructive/30 bg-destructive/5 px-3 py-2 text-[11.5px] text-destructive">
            {error}
            <button
              type="button"
              onClick={onRetry}
              className="ms-2 cursor-pointer underline underline-offset-4"
            >
              تلاش دوباره
            </button>
          </div>
        )}

        {!loading && !error && filtered.length === 0 && (
          <div className="rounded-field border border-dashed border-border px-4 py-8 text-center">
            <p className="text-[12.5px] text-muted-foreground">
              {conversations.length === 0 ? "هنوز گفت‌وگویی ساخته نشده است." : "چیزی پیدا نشد."}
            </p>
            <Button variant="outline" size="sm" className="mt-3" onClick={onNew}>
              شروع گفت‌وگو
            </Button>
          </div>
        )}

        <ul className="space-y-1.5">
          {filtered.map((conversation) => (
            <li key={conversation.id}>
              <button
                type="button"
                onClick={() => onSelect(conversation.id)}
                className={cn(
                  "w-full cursor-pointer rounded-surface border border-border bg-card px-3 py-2.5 text-start transition-colors duration-200 hover:border-brand/30 hover:bg-card/80",
                  conversation.id === activeId && "border-brand/40 bg-brand/5",
                )}
                aria-current={conversation.id === activeId ? "true" : undefined}
              >
                <div className="flex items-start justify-between gap-2">
                  <span className="line-clamp-1 text-[12.5px] font-medium">{conversation.title}</span>
                  {typeof conversation.message_count === "number" && (
                    <Badge className="shrink-0 text-[10px] text-muted-foreground">
                      {fa(conversation.message_count)} پیام
                    </Badge>
                  )}
                </div>
                <div className="mt-0.5 flex flex-wrap items-center gap-2 text-[10px] text-muted-foreground">
                  {conversation.project && (
                    <span className="code-block" dir="ltr">
                      {conversation.project}
                    </span>
                  )}
                  <span>{faTimeAgo(conversation.updated_at)}</span>
                  {conversation.simulated && <span className="text-warning">DEMO</span>}
                </div>
              </button>
            </li>
          ))}
        </ul>
      </div>
    </Drawer>
  );
}
