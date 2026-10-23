import type {
  ApprovalResponse,
  ConversationDetail,
  ConversationList,
  Conversation,
  LiveResponse,
  MessageResponse,
  SettingsStatus,
} from "./types";

export class ApiError extends Error {
  status: number;
  code: string;

  constructor(message: string, status: number, code = "request_failed") {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.code = code;
  }
}

const NETWORK_MESSAGE =
  "ارتباط با سرور برقرار نشد. اتصال شبکه یا اجرای FastAPI را بررسی کنید.";

async function request<T>(
  path: string,
  init: RequestInit = {},
  timeoutMs = 30_000,
): Promise<T> {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  try {
    const response = await fetch(path, {
      ...init,
      headers: {
        Accept: "application/json",
        ...(init.body ? { "Content-Type": "application/json" } : {}),
        ...(init.headers ?? {}),
      },
      credentials: "same-origin",
      signal: controller.signal,
    });
    const text = await response.text();
    let body: unknown = null;
    if (text) {
      try {
        body = JSON.parse(text);
      } catch {
        body = null;
      }
    }
    if (!response.ok) {
      const error = (body as { error?: { code?: string; message?: string } } | null)?.error;
      throw new ApiError(
        error?.message ?? `درخواست با خطای ${response.status} شکست خورد.`,
        response.status,
        error?.code ?? "request_failed",
      );
    }
    return body as T;
  } catch (error) {
    if (error instanceof ApiError) throw error;
    if (error instanceof DOMException && error.name === "AbortError") {
      throw new ApiError("پاسخ سرور بیش از حد طول کشید.", 0, "timeout");
    }
    throw new ApiError(NETWORK_MESSAGE, 0, "network_error");
  } finally {
    clearTimeout(timer);
  }
}

function json(body: unknown): RequestInit {
  return { method: "POST", body: JSON.stringify(body) };
}

export const api = {
  health: () => request<{ status: string; mode: string }>("/api/health", {}, 8_000),

  settings: () => request<SettingsStatus>("/api/settings/status"),

  listConversations: () => request<ConversationList>("/api/conversations"),

  createConversation: (title?: string) =>
    request<{ conversation: Conversation; mode: "demo" | "live"; simulated: boolean }>(
      "/api/conversations",
      json({ title: title ?? null }),
    ),

  getConversation: (id: string) =>
    request<ConversationDetail>(`/api/conversations/${encodeURIComponent(id)}`),

  sendMessage: (id: string, text: string, clientMessageId: string) =>
    request<MessageResponse>(
      `/api/conversations/${encodeURIComponent(id)}/messages`,
      json({ text, client_message_id: clientMessageId }),
      180_000,
    ),

  live: (id: string) =>
    request<LiveResponse>(`/api/conversations/${encodeURIComponent(id)}/live`, {}, 20_000),

  selectProject: (id: string, project: string) =>
    request<{ conversation: Conversation; assistant_message: MessageResponse["assistant_message"] }>(
      `/api/conversations/${encodeURIComponent(id)}/select-project`,
      json({ project }),
    ),

  approve: (id: string, approvalId: string) =>
    request<ApprovalResponse>(
      `/api/conversations/${encodeURIComponent(id)}/approvals/${encodeURIComponent(approvalId)}/approve`,
      json({ actor: "chat" }),
    ),

  reject: (id: string, approvalId: string) =>
    request<ApprovalResponse>(
      `/api/conversations/${encodeURIComponent(id)}/approvals/${encodeURIComponent(approvalId)}/reject`,
      json({ actor: "chat" }),
    ),

  cancelWorkflow: (id: string, workflowId: string) =>
    request<{ note: string }>(
      `/api/conversations/${encodeURIComponent(id)}/workflows/${encodeURIComponent(workflowId)}/cancel`,
      { method: "POST" },
    ),
};
