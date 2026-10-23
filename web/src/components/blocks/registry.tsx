import * as React from "react";
import { CircleSlash, TriangleAlert } from "lucide-react";
import type {
  BlockActions,
  BlockPropsMap,
  BlockType,
  UIBlock,
} from "@/lib/types";
import { ProjectOverviewBlock, ProjectPickerBlock } from "./ProjectBlocks";
import {
  DiagnosisCardBlock,
  EvidenceListBlock,
  LogViewerBlock,
  MetricsPanelBlock,
} from "./DiagnosisBlocks";
import {
  CodingAgentStatusBlock,
  DiffReviewBlock,
  RepairPlanBlock,
  TestResultsBlock,
} from "./RepairBlocks";
import { ApprovalCardBlock } from "./ApprovalBlock";
import {
  DeploymentTimelineBlock,
  HealthCheckBlock,
  ReleaseStatusBlock,
} from "./DeploymentBlocks";
import { FinalReportBlock, WorkflowTimelineBlock } from "./ReportBlocks";

type RendererMap = {
  [K in BlockType]: React.ComponentType<{
    props: BlockPropsMap[K];
    actions: BlockActions;
  }>;
};
type LooseRenderer = React.ComponentType<{ props: unknown; actions: BlockActions }>;

/**
 * The only names the renderer accepts. A server-validated block is always one of
 * these; anything else falls back to a safe "unsupported" notice instead of
 * crashing the conversation or executing arbitrary markup.
 */
const registry: RendererMap = {
  project_picker: ({ props, actions }) => (
    <ProjectPickerBlock props={props} onSelectProject={actions.onSelectProject} />
  ),
  project_overview: ({ props }) => <ProjectOverviewBlock props={props} />,
  diagnosis_card: ({ props }) => <DiagnosisCardBlock props={props} />,
  evidence_list: ({ props }) => <EvidenceListBlock props={props} />,
  metrics_panel: ({ props }) => <MetricsPanelBlock props={props} />,
  log_viewer: ({ props }) => <LogViewerBlock props={props} />,
  repair_plan_card: ({ props }) => <RepairPlanBlock props={props} />,
  coding_agent_status: ({ props }) => <CodingAgentStatusBlock props={props} />,
  diff_review: ({ props }) => <DiffReviewBlock props={props} />,
  test_results: ({ props }) => <TestResultsBlock props={props} />,
  approval_card: ({ props, actions }) => (
    <ApprovalCardBlock props={props} onApprove={actions.onApprove} onReject={actions.onReject} />
  ),
  deployment_timeline: ({ props }) => <DeploymentTimelineBlock props={props} />,
  release_status: ({ props }) => <ReleaseStatusBlock props={props} />,
  health_check_card: ({ props }) => <HealthCheckBlock props={props} />,
  final_report: ({ props }) => <FinalReportBlock props={props} />,
  workflow_timeline: ({ props, actions }) => (
    <WorkflowTimelineBlock props={props} onCancelWorkflow={actions.onCancelWorkflow} />
  ),
};

export const BLOCK_COMPONENTS = registry;

class BlockErrorBoundary extends React.Component<
  { children: React.ReactNode },
  { failed: boolean }
> {
  state = { failed: false };

  static getDerivedStateFromError() {
    return { failed: true };
  }

  componentDidCatch(error: unknown) {
    console.warn("ui-block render failed", error);
  }

  render() {
    if (this.state.failed) {
      return (
        <div className="rounded-surface border border-destructive/30 bg-card px-4 py-3 text-[12px] text-muted-foreground">
          <span className="inline-flex items-center gap-2 text-destructive">
            <TriangleAlert className="size-4" />
            نمایش این بخش ممکن نشد
          </span>
          <p className="mt-1">متن پاسخ در پیام بالا کامل است؛ این کارت به‌تنهایی رد شد.</p>
        </div>
      );
    }
    return this.props.children;
  }
}

function UnsupportedBlock({ type }: { type: string }) {
  return (
    <div className="rounded-surface border border-border bg-card px-4 py-3 text-[12px] text-muted-foreground">
      <span className="inline-flex items-center gap-2">
        <CircleSlash className="size-4" />
        این نوع نمایش در نسخه فعلی پشتیبانی نمی‌شود.
      </span>
      <span className="code-block ms-2 text-[10px]" dir="ltr">
        {type}
      </span>
    </div>
  );
}

export function BlockRenderer({
  blocks,
  actions,
}: {
  blocks: UIBlock[];
  actions: BlockActions;
}) {
  if (!Array.isArray(blocks) || blocks.length === 0) return null;
  return (
    <div className="space-y-3">
      {blocks.map((block, index) => {
        const type = (block as { type?: unknown } | null)?.type;
        const Component =
          typeof type === "string"
            ? (registry as Record<string, LooseRenderer>)[type]
            : undefined;
        if (!Component) {
          return <UnsupportedBlock key={`unsupported-${index}`} type={String(type ?? "unknown")} />;
        }
        return (
          <BlockErrorBoundary key={`${type}-${index}`}>
            <Component
              props={(block as { props?: unknown }).props}
              actions={actions}
            />
          </BlockErrorBoundary>
        );
      })}
    </div>
  );
}
