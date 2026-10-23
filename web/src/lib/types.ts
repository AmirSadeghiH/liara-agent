export type Mode = "demo" | "live";
export type Confidence = "low" | "medium" | "high";

export interface ProjectOption {
  name: string;
  type: string | null;
  status: string | null;
  is_deployed: boolean | null;
}

export interface ProjectPickerProps {
  projects: ProjectOption[];
  reason: string | null;
  allow_search: boolean;
}

export interface ProjectOverviewProps {
  project: string;
  type: string | null;
  status: string | null;
  is_deployed: boolean | null;
  plan_id: string | null;
  mode: Mode;
  simulated: boolean;
  notice: string | null;
}

export interface DiagnosisCardProps {
  project: string;
  has_incident: boolean;
  observation: string;
  probable_cause: string;
  cause_key: string;
  confidence: Confidence;
  evidence_refs: string[];
  alternatives: string[];
  recommended_action: string;
  risk: string;
  verification_method: string;
  engine: string;
  simulated: boolean;
  unavailable_sources: string[];
}

export interface EvidenceItem {
  id: string;
  kind: string;
  source: string;
  summary: string;
  observed_at: string | null;
  simulated: boolean;
}

export interface EvidenceListProps {
  items: EvidenceItem[];
  total: number;
  unavailable_sources: string[];
}

export interface MetricPoint {
  t: number;
  v: number;
}

export interface MetricSeries {
  available: boolean;
  unit: string;
  average: number | null;
  maximum: number | null;
  last: number | null;
  points: MetricPoint[];
  unavailable_reason: string | null;
}

export interface MetricsPanelProps {
  project: string;
  range_minutes: number;
  cpu: MetricSeries;
  memory: MetricSeries;
  simulated: boolean;
  source: string;
}

export interface LogLine {
  datetime: string | null;
  level: string;
  message: string;
  flagged: boolean;
}

export interface LogViewerProps {
  project: string;
  range_minutes: number;
  count: number;
  flagged_instruction_lines: number;
  lines: LogLine[];
  simulated: boolean;
}

export interface RepairPlanProps {
  cause_key: string;
  title: string;
  summary: string;
  steps: string[];
  files: string[];
  risk_level: string | null;
  attempt: number;
  max_attempts: number;
  branch: string | null;
  requires_tests: boolean;
  simulated: boolean;
}

export interface CodingAgentStatusProps {
  provider: string;
  status: string;
  attempt: number;
  summary: string;
  duration_ms: number | null;
  files_changed: string[];
  needs_human: boolean;
  branch: string | null;
  simulated: boolean;
}

export interface DiffReviewProps {
  files: string[];
  diff: string;
  truncated: boolean;
  violations: string[];
  warnings: string[];
  sensitive_files: string[];
  provider: string | null;
  simulated: boolean;
}

export interface TestResultsProps {
  status: string;
  runner: string;
  command: string | null;
  exit_code: number | null;
  duration_ms: number | null;
  output_tail: string;
  timed_out: boolean;
  simulated: boolean;
}

export interface ApprovalCardProps {
  approval_id: string;
  workflow_id: string;
  stage: "repair" | "deploy";
  action: string;
  project: string | null;
  title: string;
  reason: string;
  risk_level: string;
  params: Record<string, unknown>;
  expires_at: string;
  status: string;
  simulated: boolean;
  decision_note: string | null;
}

export interface TimelineStep {
  key: string;
  label: string;
  status: string;
  summary: string | null;
  reference: string | null;
  error: string | null;
}

export interface DeploymentTimelineProps {
  project: string;
  steps: TimelineStep[];
  release_id: string | null;
  source_id: string | null;
  port: number | null;
  status: string;
  simulated: boolean;
}

export interface ReleaseStatusProps {
  project: string;
  release_id: string | null;
  release_state: string | null;
  source_id: string | null;
  port: number | null;
  simulated: boolean;
}

export interface HealthCheckProps {
  status: "verified" | "failed" | "unverified";
  verified: boolean;
  url: string | null;
  status_code: number | null;
  checked_at: string | null;
  reason: string | null;
  simulated: boolean;
}

export interface FinalReportProps {
  workflow_id: string | null;
  project: string | null;
  request: string | null;
  outcome: string;
  stop_reason: string | null;
  cause_key: string | null;
  probable_cause: string | null;
  evidence_refs: string[];
  actions: string[];
  tests_status: string | null;
  deployment_status: string | null;
  verification_status: string | null;
  human_actions: Record<string, string | null>;
  limitations: string[];
  simulated: boolean;
  generated_at: string | null;
}

export interface WorkflowTimelineProps {
  workflow_id: string;
  project: string | null;
  status: string;
  current_step: string | null;
  current_label: string | null;
  attempt: number;
  max_attempts: number;
  stop_reason: string | null;
  error: string | null;
  steps: TimelineStep[];
  simulated: boolean;
}

export interface BlockPropsMap {
  project_picker: ProjectPickerProps;
  project_overview: ProjectOverviewProps;
  diagnosis_card: DiagnosisCardProps;
  evidence_list: EvidenceListProps;
  metrics_panel: MetricsPanelProps;
  log_viewer: LogViewerProps;
  repair_plan_card: RepairPlanProps;
  coding_agent_status: CodingAgentStatusProps;
  diff_review: DiffReviewProps;
  test_results: TestResultsProps;
  approval_card: ApprovalCardProps;
  deployment_timeline: DeploymentTimelineProps;
  release_status: ReleaseStatusProps;
  health_check_card: HealthCheckProps;
  final_report: FinalReportProps;
  workflow_timeline: WorkflowTimelineProps;
}

export type BlockType = keyof BlockPropsMap;

export type UIBlock = {
  [K in BlockType]: { type: K; props: BlockPropsMap[K] };
}[BlockType];

export interface BlockActions {
  onSelectProject?: (project: string) => void | Promise<void>;
  onApprove?: (approvalId: string) => Promise<void> | void;
  onReject?: (approvalId: string) => Promise<void> | void;
  onCopy?: (text: string, label?: string) => void;
  onCancelWorkflow?: (workflowId: string) => void | Promise<void>;
}

export interface ConversationMessage {
  id: number;
  conversation_id: string;
  role: "user" | "assistant";
  text: string;
  blocks: UIBlock[];
  workflow_id: string | null;
  data: Record<string, unknown>;
  created_at: string;
}

export interface Conversation {
  id: string;
  title: string;
  project: string | null;
  last_intent: string | null;
  workflow_ids: string[];
  demo_mode: boolean;
  simulated: boolean;
  created_at: string;
  updated_at: string;
  message_count?: number;
}

export interface ConversationDetail {
  conversation: Conversation;
  messages: ConversationMessage[];
  mode: Mode;
  simulated: boolean;
  server_time: string;
}

export interface ConversationList {
  count: number;
  conversations: Conversation[];
  mode: Mode;
  simulated: boolean;
}

export interface WorkflowLiveState {
  workflow_id: string;
  status: string;
  current_step: string | null;
  pending_approval_id: string | null;
  simulated: boolean;
  blocks: UIBlock[];
  server_time: string;
}

export interface LiveResponse {
  conversation_id: string;
  project: string | null;
  states: WorkflowLiveState[];
  server_time: string;
}

export interface MessageResponse {
  conversation: Conversation;
  user_message: ConversationMessage;
  assistant_message: ConversationMessage | null;
  workflow_id?: string | null;
  deduplicated?: boolean;
}

export interface ApprovalResponse {
  approval: {
    id: string;
    status: string;
    stage: string;
    workflow_id: string;
  };
  workflow_id: string;
  blocks: UIBlock[];
  note: string;
}

export interface SettingsStatus {
  app_name: string;
  app_env: string;
  demo_mode: boolean;
  llm: { provider: string; model: string | null; configured: boolean };
  liara: { base_url: string; token_configured: boolean; auth_scheme: string };
  coding_agent: {
    provider: string;
    auto_execute: boolean;
    git_push: boolean;
    max_repair_attempts: number;
  };
  verification: { healthcheck_url_configured: boolean; expect_status: number };
  auth_enabled: boolean;
  readiness: {
    demo_mode: boolean;
    live_ready: boolean;
    blockers: string[];
    warnings: string[];
  };
  adapter?: { mode: string; simulated: boolean; base_url: string | null };
}
