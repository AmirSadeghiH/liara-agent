import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type {
  ApprovalCardProps,
  DiagnosisCardProps,
  HealthCheckProps,
  MetricsPanelProps,
  TestResultsProps,
  UIBlock,
} from "@/lib/types";
import { BLOCK_COMPONENTS, BlockRenderer } from "@/components/blocks/registry";
import { ApprovalCardBlock } from "@/components/blocks/ApprovalBlock";
import { MetricsPanelBlock } from "@/components/blocks/DiagnosisBlocks";
import { TestResultsBlock } from "@/components/blocks/RepairBlocks";
import { HealthCheckBlock } from "@/components/blocks/DeploymentBlocks";

const REGISTERED = [
  "project_picker",
  "project_overview",
  "diagnosis_card",
  "evidence_list",
  "metrics_panel",
  "log_viewer",
  "repair_plan_card",
  "coding_agent_status",
  "diff_review",
  "test_results",
  "approval_card",
  "deployment_timeline",
  "release_status",
  "health_check_card",
  "final_report",
  "workflow_timeline",
];

const diagnosis: DiagnosisCardProps = {
  project: "demo-django-store",
  has_incident: true,
  observation: "۱۰ خط خطا در لاگ‌ها",
  probable_cause: "وابستگی ناموجود در محیط اجرا",
  cause_key: "missing_dependency",
  confidence: "high",
  evidence_refs: ["ev-1"],
  alternatives: [],
  recommended_action: "افزودن وابستگی به requirements.txt",
  risk: "کم",
  verification_method: "پاسخ 200 از /healthz",
  engine: "rule_engine",
  simulated: true,
  unavailable_sources: [],
};

function metrics(cpuAvailable: boolean): MetricsPanelProps {
  return {
    project: "demo-django-store",
    range_minutes: 60,
    cpu: {
      available: cpuAvailable,
      unit: "%",
      average: cpuAvailable ? 8.2 : null,
      maximum: cpuAvailable ? 9.8 : null,
      last: cpuAvailable ? 9.1 : null,
      points: cpuAvailable ? [{ t: 1, v: 8 }, { t: 2, v: 9 }] : [],
      unavailable_reason: cpuAvailable ? null : "API متریک پاسخ نداد",
    },
    memory: {
      available: false,
      unit: "%",
      average: null,
      maximum: null,
      last: null,
      points: [],
      unavailable_reason: "داده‌ای برای این بازه برنگشت",
    },
    simulated: true,
    source: "Liara Metrics API",
  };
}

const approval: ApprovalCardProps = {
  approval_id: "apv-wf-1-deploy-0",
  workflow_id: "wf-1",
  stage: "deploy",
  action: "create_release",
  project: "demo-django-store",
  title: "ساخت Release در لیارا",
  reason: "انتشار نسخه اصلاح‌شده",
  risk_level: "high",
  params: { project: "demo-django-store", port: 8000 },
  expires_at: new Date(Date.now() + 10 * 60_000).toISOString(),
  status: "pending",
  simulated: true,
  decision_note: null,
};

const failedTests: TestResultsProps = {
  status: "failed",
  runner: "pytest",
  command: "pytest -q",
  exit_code: 1,
  duration_ms: 120,
  output_tail: "E   AssertionError: expected 2",
  timed_out: false,
  simulated: true,
};

const unverifiedHealth: HealthCheckProps = {
  status: "unverified",
  verified: false,
  url: null,
  status_code: null,
  checked_at: null,
  reason: "DEPLOY_HEALTHCHECK_URL تنظیم نشده است",
  simulated: true,
};

describe("generative UI registry", () => {
  it("registers exactly the server-side block contract", () => {
    expect(Object.keys(BLOCK_COMPONENTS).sort()).toEqual([...REGISTERED].sort());
  });

  it("renders an allowed block and falls back safely for unknown types", () => {
    const blocks = [
      { type: "diagnosis_card", props: diagnosis },
      { type: "not_a_real_block", props: {} },
      { type: "<script>alert(1)</script>", props: {} },
    ] as unknown as UIBlock[];

    const { container } = render(<BlockRenderer blocks={blocks} actions={{}} />);

    expect(screen.getByText("تشخیص علت")).toBeInTheDocument();
    expect(screen.getAllByText(/پشتیبانی نمی‌شود/)).toHaveLength(2);
    expect(container.querySelector("script")).toBeNull();
    expect(screen.queryByText("alert(1)")).not.toBeInTheDocument();
  });

  it("renders an empty block list without crashing", () => {
    const { container } = render(<BlockRenderer blocks={[]} actions={{}} />);
    expect(container).toBeEmptyDOMElement();
  });
});

describe("metric availability", () => {
  it("shows unavailable series as «ناموجود» instead of a fake zero", () => {
    render(<MetricsPanelBlock props={metrics(false)} />);
    expect(screen.getAllByText("ناموجود").length).toBeGreaterThanOrEqual(2);
    expect(screen.queryByText(/۰٪/)).not.toBeInTheDocument();
  });
});

describe("approval card", () => {
  it("requires an explicit second confirmation before calling the server", async () => {
    const user = userEvent.setup();
    const onApprove = vi.fn().mockResolvedValue(undefined);
    const onReject = vi.fn().mockResolvedValue(undefined);

    render(
      <ApprovalCardBlock props={approval} onApprove={onApprove} onReject={onReject} />,
    );

    expect(screen.getByText("DEMO / SIMULATED")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: /تأیید و ادامه/ }));
    expect(onApprove).not.toHaveBeenCalled();

    await user.click(screen.getByRole("button", { name: /بله، ثبت و ادامه/ }));
    expect(onApprove).toHaveBeenCalledWith("apv-wf-1-deploy-0");
  });

  it("hides approve/reject controls once the request is no longer pending", () => {
    render(
      <ApprovalCardBlock
        props={{ ...approval, status: "rejected" }}
        onApprove={vi.fn()}
        onReject={vi.fn()}
      />,
    );
    expect(screen.queryByRole("button", { name: /تأیید و ادامه/ })).not.toBeInTheDocument();
    expect(screen.getByText(/عملیات مربوطه اجرا نشد/)).toBeInTheDocument();
  });

  it("marks a non-simulated approval as LIVE and isolates technical ids for RTL", () => {
    const { container } =    render(<ApprovalCardBlock props={{ ...approval, simulated: false }} />);
    expect(screen.getByText("LIVE")).toBeInTheDocument();
    const id = screen.getByText("apv-wf-1-deploy-0");
    expect(id.closest('[dir="ltr"]')).not.toBeNull();
    expect(container.querySelector('article, div')).toBeTruthy();
  });
});

describe("failure and uncertainty states", () => {
  it("does not present failing tests as deployable success", () => {
    render(<TestResultsBlock props={failedTests} />);
    expect(screen.getByText(/انتشار تا رفع خطا/)).toBeInTheDocument();
    expect(screen.getByText(/AssertionError: expected 2/)).toBeInTheDocument();
  });

  it("reports an unavailable health check as unverified, never healthy", () => {
    render(<HealthCheckBlock props={unverifiedHealth} />);
    expect(screen.getAllByText("تأییدنشده").length).toBeGreaterThanOrEqual(1);
    expect(screen.getByText(/نه «سالم»/)).toBeInTheDocument();
    expect(screen.queryByText(/بررسی سلامت با پاسخ مورد انتظار انجام شد/)).not.toBeInTheDocument();
  });
});
