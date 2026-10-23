import type {
  ConversationMessage,
  UIBlock,
  WorkflowLiveState,
} from "./types";

export const ACTIVE_STATUSES = new Set([
  "queued",
  "running",
  "testing",
  "deploying",
  "verifying",
  "waiting_for_approval",
]);

export const CANCELLABLE_STATUSES = new Set([
  "queued",
  "waiting_for_approval",
  "needs_human",
  "failed",
]);

/**
 * Replace the blocks of the *existing* assistant message that owns a workflow.
 * It never appends a new message or a new card, so polling cannot duplicate
 * approvals, timelines or reports.
 */
export function applyLiveStates(
  messages: ConversationMessage[],
  states: WorkflowLiveState[],
): ConversationMessage[] {
  if (!states.length) return messages;
  const byWorkflow = new Map(states.map((state) => [state.workflow_id, state]));
  let changed = false;
  const next = messages.map((message) => {
    if (message.role !== "assistant" || !message.workflow_id) return message;
    if (message.data?.live !== true) return message;
    const state = byWorkflow.get(message.workflow_id);
    if (!state) return message;
    const sameBlocks =
      JSON.stringify(message.blocks) === JSON.stringify(state.blocks);
    if (sameBlocks) return message;
    changed = true;
    return {
      ...message,
      blocks: state.blocks as UIBlock[],
      data: { ...message.data, live_status: state.status },
    };
  });
  return changed ? next : messages;
}

export function activeWorkflowCount(states: WorkflowLiveState[]): number {
  return states.filter((state) => ACTIVE_STATUSES.has(state.status)).length;
}

export function pendingApprovalCount(states: WorkflowLiveState[]): number {
  return states.filter((state) => Boolean(state.pending_approval_id)).length;
}

export function latestActiveWorkflow(
  states: WorkflowLiveState[],
): WorkflowLiveState | null {
  return [...states].reverse().find((state) => ACTIVE_STATUSES.has(state.status)) ?? null;
}

export function latestCancellableWorkflow(
  states: WorkflowLiveState[],
): WorkflowLiveState | null {
  return [...states].reverse().find((state) => CANCELLABLE_STATUSES.has(state.status)) ?? null;
}

export function mergeConversation(
  list: Array<{ id: string; updated_at: string }>,
  conversation: { id: string; updated_at: string },
): Array<{ id: string; updated_at: string }> {
  const rest = list.filter((item) => item.id !== conversation.id);
  return [conversation, ...rest].sort((a, b) =>
    a.updated_at < b.updated_at ? 1 : -1,
  );
}
