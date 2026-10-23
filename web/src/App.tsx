import * as React from "react";
import { Activity, AlertTriangle, Gauge, RefreshCw, Square, Wrench } from "lucide-react";
import { api, ApiError } from "@/lib/api";
import type {
  BlockActions,
  Conversation,
  ConversationMessage,
  Mode,
  SettingsStatus,
  WorkflowLiveState,
} from "@/lib/types";
import {
  activeWorkflowCount,
  applyLiveStates,
  latestCancellableWorkflow,
  pendingApprovalCount,
} from "@/lib/live";
import { ChatHeader } from "@/components/chat/Header";
import { EmptyState } from "@/components/chat/EmptyState";
import { HistoryDrawer } from "@/components/chat/HistoryDrawer";
import { SettingsDrawer } from "@/components/chat/SettingsDrawer";
import { MessageItem, MessageSkeleton, TypingIndicator } from "@/components/chat/MessageItem";
import { PromptInput } from "@/components/ui/PromptInput";
import { Button } from "@/components/ui/Button";
import { Card } from "@/components/ui/Card";
import { Notice } from "@/components/blocks/primitives";
import { cn } from "@/lib/cn";

type DrawerName = "history" | "settings" | null;

const QUICK_ACTIONS = [
  { label: "وضعیت", icon: Activity, text: "وضعیت پروژه را بررسی کن" },
  { label: "منابع", icon: Gauge, text: "مصرف CPU و RAM را بررسی کن" },
  { label: "لاگ‌ها", icon: AlertTriangle, text: "لاگ‌های اخیر را بررسی کن" },
  { label: "اصلاح", icon: Wrench, text: "خطای شناسایی‌شده را اصلاح کن" },
];

function newClientId(): string {
  if (typeof crypto !== "undefined" && typeof crypto.randomUUID === "function") {
    return crypto.randomUUID();
  }
  return `c-${Date.now()}-${Math.random().toString(36).slice(2, 12)}`;
}

function errorMessage(error: unknown): string {
  if (error instanceof ApiError) return error.message;
  if (error instanceof Error) return error.message;
  return "خطای نامشخصی رخ داد.";
}

function isNetworkError(error: unknown): boolean {
  return error instanceof ApiError && error.status === 0;
}

export default function App() {
  const [connected, setConnected] = React.useState(true);
  const [bootError, setBootError] = React.useState<string | null>(null);
  const [booting, setBooting] = React.useState(true);

  const [settings, setSettings] = React.useState<SettingsStatus | null>(null);
  const [settingsLoading, setSettingsLoading] = React.useState(false);
  const [settingsError, setSettingsError] = React.useState<string | null>(null);

  const [conversations, setConversations] = React.useState<Conversation[]>([]);
  const [historyLoading, setHistoryLoading] = React.useState(false);
  const [historyError, setHistoryError] = React.useState<string | null>(null);

  const [activeId, setActiveId] = React.useState<string | null>(null);
  const [messages, setMessages] = React.useState<ConversationMessage[]>([]);
  const [liveStates, setLiveStates] = React.useState<WorkflowLiveState[]>([]);
  const [loadingConversation, setLoadingConversation] = React.useState(false);
  const [loadError, setLoadError] = React.useState<string | null>(null);

  const [mode, setMode] = React.useState<Mode>("demo");
  const [simulated, setSimulated] = React.useState(true);
  const [project, setProject] = React.useState<string | null>(null);

  const [draft, setDraft] = React.useState("");
  const [sending, setSending] = React.useState(false);
  const [sendError, setSendError] = React.useState<string | null>(null);
  const [cancelBusy, setCancelBusy] = React.useState(false);

  const [drawer, setDrawer] = React.useState<DrawerName>(null);
  const [toast, setToast] = React.useState<string | null>(null);

  const scrollRef = React.useRef<HTMLDivElement>(null);
  const stickToBottom = React.useRef(true);
  const liveInFlight = React.useRef(false);
  const lastAttempt = React.useRef<{ text: string; clientId: string } | null>(null);

  // ------------------------------------------------------------------
  // data loading
  // ------------------------------------------------------------------
  const refreshLive = React.useCallback(async (conversationId: string) => {
    if (liveInFlight.current) return;
    liveInFlight.current = true;
    try {
      const live = await api.live(conversationId);
      setLiveStates(live.states);
      setMessages((previous) => applyLiveStates(previous, live.states));
      setConnected(true);
    } catch (error) {
      if (isNetworkError(error)) setConnected(false);
    } finally {
      liveInFlight.current = false;
    }
  }, []);

  const openConversation = React.useCallback(
    async (conversationId: string) => {
      setLoadingConversation(true);
      setLoadError(null);
      stickToBottom.current = true;
      try {
        const [data, live] = await Promise.allSettled([
          api.getConversation(conversationId),
          api.live(conversationId),
        ]);
        if (data.status === "rejected") throw data.reason;
        const payload = data.value;
        const states = live.status === "fulfilled" ? live.value.states : [];
        setActiveId(conversationId);
        setMessages(applyLiveStates(payload.messages, states));
        setLiveStates(states);
        setProject(payload.conversation.project);
        setMode(payload.mode);
        setSimulated(payload.simulated);
        setConnected(true);
      } catch (error) {
        if (isNetworkError(error)) setConnected(false);
        setLoadError(errorMessage(error));
      } finally {
        setLoadingConversation(false);
      }
    },
    [],
  );

  const refreshConversation = React.useCallback(
    async (conversationId: string) => {
      try {
        const [data, live] = await Promise.allSettled([
          api.getConversation(conversationId),
          api.live(conversationId),
        ]);
        if (data.status === "fulfilled") {
          setProject(data.value.conversation.project);
          setMode(data.value.mode);
          setSimulated(data.value.simulated);
          const states = live.status === "fulfilled" ? live.value.states : liveStates;
          if (live.status === "fulfilled") setLiveStates(live.value.states);
          setMessages(applyLiveStates(data.value.messages, states));
        }
        setConnected(true);
      } catch (error) {
        if (isNetworkError(error)) setConnected(false);
      }
    },
    [liveStates],
  );

  const loadHistory = React.useCallback(async () => {
    setHistoryLoading(true);
    setHistoryError(null);
    try {
      const data = await api.listConversations();
      setConversations(data.conversations);
      setMode(data.mode);
      setSimulated(data.simulated);
      setConnected(true);
      return data.conversations;
    } catch (error) {
      if (isNetworkError(error)) setConnected(false);
      setHistoryError(errorMessage(error));
      return [];
    } finally {
      setHistoryLoading(false);
    }
  }, []);

  const loadSettings = React.useCallback(async () => {
    setSettingsLoading(true);
    setSettingsError(null);
    try {
      const data = await api.settings();
      setSettings(data);
      setMode(data.demo_mode ? "demo" : "live");
      setConnected(true);
    } catch (error) {
      if (isNetworkError(error)) setConnected(false);
      setSettingsError(errorMessage(error));
    } finally {
      setSettingsLoading(false);
    }
  }, []);

  React.useEffect(() => {
    let cancelled = false;
    (async () => {
      const [settingsResult, listResult] = await Promise.allSettled([
        api.settings(),
        api.listConversations(),
      ]);
      if (cancelled) return;
      if (settingsResult.status === "fulfilled") {
        setSettings(settingsResult.value);
        setMode(settingsResult.value.demo_mode ? "demo" : "live");
      }
      if (listResult.status === "fulfilled") {
        setConversations(listResult.value.conversations);
        setMode(listResult.value.mode);
        setSimulated(listResult.value.simulated);
        const first = listResult.value.conversations[0];
        if (first) await openConversation(first.id);
      } else {
        setBootError(errorMessage(listResult.reason));
        if (isNetworkError(listResult.reason)) setConnected(false);
      }
      setBooting(false);
    })();
    return () => {
      cancelled = true;
    };
  }, [openConversation]);

  React.useEffect(() => {
    function online() {
      setConnected(true);
    }
    function offline() {
      setConnected(false);
    }
    window.addEventListener("online", online);
    window.addEventListener("offline", offline);
    return () => {
      window.removeEventListener("online", online);
      window.removeEventListener("offline", offline);
    };
  }, []);

  // Poll only while a linked workflow is active; a completed workflow stops it.
  const activeSignature = liveStates
    .filter((state) => ["queued", "running", "testing", "deploying", "verifying", "waiting_for_approval"].includes(state.status))
    .map((state) => `${state.workflow_id}:${state.status}`)
    .join("|");

  React.useEffect(() => {
    if (!activeId || !activeSignature) return;
    let stopped = false;
    const timer = window.setInterval(() => {
      if (stopped) return;
      void refreshLive(activeId);
    }, 2600);
    return () => {
      stopped = true;
      window.clearInterval(timer);
    };
  }, [activeId, activeSignature, refreshLive]);

  // Auto-scroll only when the user is already near the bottom.
  React.useEffect(() => {
    if (!stickToBottom.current) return;
    const element = scrollRef.current;
    if (!element) return;
    element.scrollTop = element.scrollHeight;
  }, [messages, sending, loadingConversation]);

  React.useEffect(() => {
    if (!toast) return;
    const timer = window.setTimeout(() => setToast(null), 3200);
    return () => window.clearTimeout(timer);
  }, [toast]);

  React.useEffect(() => {
    if (drawer === "history") void loadHistory();
    if (drawer === "settings" && !settings) void loadSettings();
  }, [drawer, loadHistory, loadSettings, settings]);

  // ------------------------------------------------------------------
  // actions
  // ------------------------------------------------------------------
  async function send(raw: string) {
    const text = raw.trim();
    if (!text || sending) return;
    stickToBottom.current = true;
    setSending(true);
    setSendError(null);

    const optimisticId = -Date.now();
    const optimistic: ConversationMessage = {
      id: optimisticId,
      conversation_id: activeId ?? "pending",
      role: "user",
      text,
      blocks: [],
      workflow_id: null,
      data: {},
      created_at: new Date().toISOString(),
    };
    setMessages((previous) => [...previous, optimistic]);
    setDraft("");

    let conversationId = activeId;
    try {
      if (!conversationId) {
        const created = await api.createConversation();
        conversationId = created.conversation.id;
        setActiveId(conversationId);
        setConversations((previous) => [created.conversation, ...previous]);
        setMode(created.mode);
        setSimulated(created.simulated);
        setProject(created.conversation.project);
      }

      const attempt =
        lastAttempt.current && lastAttempt.current.text === text
          ? lastAttempt.current
          : { text, clientId: newClientId() };
      lastAttempt.current = attempt;
      const response = await api.sendMessage(conversationId, text, attempt.clientId);
      lastAttempt.current = null;

      if (response.deduplicated) {
        await openConversation(conversationId);
      } else {
        setMessages((previous) => {
          const withoutOptimistic = previous.filter((message) => message.id !== optimisticId);
          return [
            ...withoutOptimistic,
            response.user_message,
            ...(response.assistant_message ? [response.assistant_message] : []),
          ];
        });
        setConversations((previous) => {
          const rest = previous.filter((item) => item.id !== response.conversation.id);
          return [response.conversation, ...rest];
        });
        setProject(response.conversation.project);
        if (response.assistant_message?.data?.mode === "demo") setSimulated(true);
        if (response.assistant_message?.data?.mode === "live") setSimulated(false);
        await refreshLive(conversationId);
      }
      setConnected(true);
    } catch (error) {
      setMessages((previous) => previous.filter((message) => message.id !== optimisticId));
      setDraft(text);
      setSendError(errorMessage(error));
      if (isNetworkError(error)) setConnected(false);
    } finally {
      setSending(false);
    }
  }

  async function handleSelectProject(name: string) {
    if (!activeId) {
      setToast("برای انتخاب پروژه اول یک گفت‌وگو بسازید.");
      return;
    }
    try {
      await api.selectProject(activeId, name);
      await refreshConversation(activeId);
      setToast("پروژه فعال به‌روزرسانی شد.");
    } catch (error) {
      setToast(errorMessage(error));
      if (isNetworkError(error)) setConnected(false);
    }
  }

  async function handleApprove(approvalId: string) {
    if (!activeId) throw new Error("گفت‌وگوی فعالی وجود ندارد.");
    const result = await api.approve(activeId, approvalId);
    setToast(result.note || "تصمیم در سرور ثبت شد.");
    await refreshConversation(activeId);
  }

  async function handleReject(approvalId: string) {
    if (!activeId) throw new Error("گفت‌وگوی فعالی وجود ندارد.");
    const result = await api.reject(activeId, approvalId);
    setToast(result.note || "درخواست رد شد.");
    await refreshConversation(activeId);
  }

  async function handleStop() {
    const target = latestCancellableWorkflow(liveStates);
    if (!activeId || !target || cancelBusy) {
      setToast("در این مرحله عملیات قابل توقف نیست.");
      return;
    }
    setCancelBusy(true);
    try {
      const result = await api.cancelWorkflow(activeId, target.workflow_id);
      setToast(result.note || "درخواست لغو به سرور رسید.");
      await refreshConversation(activeId);
    } catch (error) {
      setToast(errorMessage(error));
    } finally {
      setCancelBusy(false);
    }
  }

  async function handleCancelWorkflow(workflowId: string) {
    if (!activeId) return;
    try {
      const result = await api.cancelWorkflow(activeId, workflowId);
      setToast(result.note || "درخواست لغو به سرور رسید.");
      await refreshConversation(activeId);
    } catch (error) {
      setToast(errorMessage(error));
    }
  }

  function startNewConversation() {
    setActiveId(null);
    setMessages([]);
    setLiveStates([]);
    setProject(null);
    setDraft("");
    setSendError(null);
    setLoadError(null);
    setDrawer(null);
    stickToBottom.current = true;
  }

  async function selectConversation(id: string) {
    setDrawer(null);
    await openConversation(id);
  }

  // ------------------------------------------------------------------
  // render
  // ------------------------------------------------------------------
  if (booting) {
    return (
      <div className="grid min-h-dvh place-items-center p-6">
        <div className="flex items-center gap-3 text-sm text-muted-foreground" role="status">
          <span className="size-4 animate-spin rounded-full border-2 border-muted-foreground/30 border-t-foreground" />
          در حال آماده‌سازی LiaraPilot…
        </div>
      </div>
    );
  }

  if (bootError) {
    return (
      <div className="grid min-h-dvh place-items-center p-6">
        <Card className="w-full max-w-md p-6">
          <h1 className="text-lg font-semibold">اتصال به سرور برقرار نشد</h1>
          <p className="mt-2 text-[13px] leading-7 text-muted-foreground">{bootError}</p>
          <p className="mt-2 text-[11px] leading-6 text-muted-foreground">
            FastAPI را اجرا کنید و دوباره تلاش کنید. اگر سرور در حال اجراست، دسترسی به
            <span className="code-block mx-1" dir="ltr">/api</span>
            را بررسی کنید.
          </p>
          <Button
            variant="brand"
            className="mt-4 w-full"
            onClick={() => window.location.reload()}
          >
            <RefreshCw />
            تلاش دوباره
          </Button>
        </Card>
      </div>
    );
  }

  const activeCount = activeWorkflowCount(liveStates);
  const pendingCount = pendingApprovalCount(liveStates);
  const cancellable = latestCancellableWorkflow(liveStates);
  const showEmpty = !loadingConversation && messages.length === 0;

  const actions: BlockActions = {
    onSelectProject: handleSelectProject,
    onApprove: handleApprove,
    onReject: handleReject,
    onCopy: (_, label) => setToast(`${label ?? "محتوا"} کپی شد.`),
    onCancelWorkflow: handleCancelWorkflow,
  };

  return (
    <div className="flex h-dvh flex-col overflow-hidden">
      <ChatHeader
        mode={mode}
        simulated={simulated}
        project={project}
        pendingCount={pendingCount}
        activeWorkflows={activeCount}
        connected={connected}
        onNew={startNewConversation}
        onHistory={() => setDrawer("history")}
        onSettings={() => setDrawer("settings")}
      />

      <main
        id="conversation"
        ref={scrollRef}
        onScroll={() => {
          const element = scrollRef.current;
          if (!element) return;
          stickToBottom.current = element.scrollHeight - element.scrollTop - element.clientHeight < 96;
        }}
        className="flex-1 overflow-y-auto"
      >
        <div className="mx-auto w-full max-w-3xl px-3 pb-6 pt-4 sm:px-5 sm:pt-6">
          {loadingConversation && <MessageSkeleton />}

          {loadError && !loadingConversation && (
            <Card className="p-5">
              <h2 className="text-sm font-semibold">گفت‌وگو بارگذاری نشد</h2>
              <p className="mt-1 text-[12.5px] leading-6 text-muted-foreground">{loadError}</p>
              <Button
                variant="outline"
                size="sm"
                className="mt-3"
                onClick={() => activeId && void openConversation(activeId)}
              >
                <RefreshCw />
                تلاش دوباره
              </Button>
            </Card>
          )}

          {showEmpty && (
            <EmptyState
              mode={mode}
              project={project}
              disabled={sending}
              onSuggestion={(text) => void send(text)}
            />
          )}

          <div
            className="space-y-6"
            role="log"
            aria-live="polite"
            aria-relevant="additions text"
            aria-label="پیام‌های گفت‌وگو"
          >
            {messages.map((message) => (
              <MessageItem key={message.id} message={message} actions={actions} />
            ))}
            {sending && <TypingIndicator />}
          </div>

          {sendError && (
            <div className="mt-4">
              <Notice tone="danger">
                <div className="flex flex-wrap items-center gap-2">
                  <span role="alert">{sendError}</span>
                  <button
                    type="button"
                    onClick={() => void send(draft)}
                    className="cursor-pointer text-[11px] underline underline-offset-4"
                    disabled={!draft.trim() || sending}
                  >
                    تلاش دوباره
                  </button>
                </div>
              </Notice>
            </div>
          )}
        </div>
      </main>

      <div className="sticky bottom-0 border-t border-border bg-background/95 backdrop-blur-sm">
        <div className="mx-auto w-full max-w-3xl px-3 pb-3 pt-2.5 sm:px-5">
          <div className="mb-2 flex items-center gap-1.5 overflow-x-auto pb-0.5">
            {QUICK_ACTIONS.map(({ label, icon: Icon, text }) => (
              <Button
                key={label}
                variant="ghost"
                size="sm"
                disabled={sending}
                onClick={() => void send(text)}
                className="shrink-0 text-muted-foreground"
                title={text}
              >
                <Icon className="size-3.5" />
                {label}
              </Button>
            ))}
            {cancellable && (
              <Button
                variant="outline"
                size="sm"
                onClick={() => void handleStop()}
                disabled={cancelBusy}
                className="ms-auto shrink-0"
                title="درخواست توقف عملیات جاری"
              >
                <Square className="size-3" />
                {cancelBusy ? "در حال ارسال…" : "توقف"}
              </Button>
            )}
          </div>

          <PromptInput
            value={draft}
            onChange={setDraft}
            onSubmit={(text) => void send(text)}
            loading={sending}
            disabled={loadingConversation}
            placeholder={
              project
                ? `درباره ${project} بپرس یا بگو چه کاری انجام شود…`
                : "مشکل یا درخواستت را بنویس…"
            }
            tools={
              <span className="px-1 text-[10px] text-muted-foreground/70">
                {mode === "demo" ? "DEMO — بدون تغییر در لیارا" : "LIVE — عملیات واقعی"}
              </span>
            }
          />
          <p className="mt-1.5 flex flex-wrap items-center justify-center gap-x-2 text-center text-[10px] text-muted-foreground/70">
            <span>Enter برای ارسال</span>
            <span aria-hidden>·</span>
            <span>Shift+Enter برای خط جدید</span>
            <span aria-hidden>·</span>
            <span>عملیات حساس فقط با تأیید معتبر سرور اجرا می‌شود</span>
          </p>
        </div>
      </div>

      <HistoryDrawer
        open={drawer === "history"}
        loading={historyLoading}
        error={historyError}
        conversations={conversations}
        activeId={activeId}
        onClose={() => setDrawer(null)}
        onSelect={(id) => void selectConversation(id)}
        onNew={startNewConversation}
        onRetry={() => void loadHistory()}
      />

      <SettingsDrawer
        open={drawer === "settings"}
        status={settings}
        loading={settingsLoading}
        error={settingsError}
        onClose={() => setDrawer(null)}
        onRetry={() => void loadSettings()}
      />

      <div
        className={cn(
          "pointer-events-none fixed inset-x-0 bottom-24 z-50 flex justify-center px-4 transition-opacity duration-(--motion)",
          toast ? "opacity-100" : "opacity-0",
        )}
        aria-live="polite"
      >
        {toast && (
          <span className="rounded-full border border-border bg-popover px-4 py-2 text-[11.5px] text-popover-foreground shadow-overlay">
            {toast}
          </span>
        )}
      </div>
    </div>
  );
}
