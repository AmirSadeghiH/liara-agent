"""Workflow graph definition.

``START → intake → resolve → evidence → normalize → diagnose → risk → plan →
approval* → workspace → agent → tests → review → prepare deploy →
deploy approval* → release → verify → evaluate → finish``

``*`` marks persistent LangGraph interrupts.  Error/needs-human paths always
route to ``finish_or_stop`` so the workflow ends in a terminal, inspectable state
rather than hanging.
"""

from __future__ import annotations

from typing import Any, Literal

from langgraph.graph import END, START, StateGraph

from app.agent.nodes import WorkflowDeps, WorkflowNodes
from app.agent.state import WorkflowState

Route = Literal["next", "finish"]


def _guard(nxt: str) -> dict[str, str]:
    return {"next": nxt, "finish": "finish_or_stop"}


def build_graph(deps: WorkflowDeps, checkpointer: Any):
    nodes = WorkflowNodes(deps)
    graph: StateGraph = StateGraph(WorkflowState)

    graph.add_node("intake_request", nodes.intake_request)
    graph.add_node("resolve_project", nodes.resolve_project)
    graph.add_node("collect_evidence", nodes.collect_evidence)
    graph.add_node("normalize_evidence", nodes.normalize_evidence)
    graph.add_node("diagnose_issue", nodes.diagnose_issue)
    graph.add_node("classify_risk", nodes.classify_risk)
    graph.add_node("prepare_repair_plan", nodes.prepare_repair_plan)
    graph.add_node("request_human_approval", nodes.request_human_approval)
    graph.add_node("prepare_workspace", nodes.prepare_workspace)
    graph.add_node("run_coding_agent", nodes.run_coding_agent)
    graph.add_node("run_tests", nodes.run_tests)
    graph.add_node("review_diff", nodes.review_diff)
    graph.add_node("prepare_deployment", nodes.prepare_deployment)
    graph.add_node("request_deployment_approval", nodes.request_deployment_approval)
    graph.add_node("deploy_release", nodes.deploy_release)
    graph.add_node("verify_deployment", nodes.verify_deployment)
    graph.add_node("evaluate_result", nodes.evaluate_result)
    graph.add_node("finish_or_stop", nodes.finish_or_stop)

    graph.add_edge(START, "intake_request")
    graph.add_conditional_edges(
        "intake_request", lambda s: "finish" if s.get("error") else "next",
        _guard("resolve_project"),
    )
    graph.add_conditional_edges(
        "resolve_project", lambda s: "finish" if s.get("error") else "next",
        _guard("collect_evidence"),
    )
    graph.add_conditional_edges(
        "collect_evidence", lambda s: "finish" if s.get("error") else "next",
        _guard("normalize_evidence"),
    )
    graph.add_conditional_edges(
        "normalize_evidence", lambda s: "finish" if s.get("error") else "next",
        _guard("diagnose_issue"),
    )
    graph.add_conditional_edges("diagnose_issue", _after_diagnosis, {
        "finish": "finish_or_stop", "next": "classify_risk",
    })
    graph.add_conditional_edges(
        "classify_risk", lambda s: "finish" if s.get("error") else "next",
        _guard("prepare_repair_plan"),
    )
    graph.add_conditional_edges(
        "prepare_repair_plan", lambda s: "finish" if s.get("error") else "next",
        _guard("request_human_approval"),
    )
    graph.add_conditional_edges("request_human_approval", _after_repair_approval, {
        "finish": "finish_or_stop", "next": "prepare_workspace",
    })
    graph.add_conditional_edges("prepare_workspace", _after_workspace, {
        "finish": "finish_or_stop", "next": "run_coding_agent",
    })
    graph.add_conditional_edges("run_coding_agent", _after_agent, {
        "finish": "finish_or_stop", "next": "run_tests",
    })
    graph.add_conditional_edges("run_tests", _after_tests, {
        "finish": "finish_or_stop", "next": "review_diff", "retry": "prepare_repair_plan",
    })
    graph.add_conditional_edges("review_diff", _after_review, {
        "finish": "finish_or_stop", "next": "prepare_deployment",
    })
    graph.add_conditional_edges(
        "prepare_deployment", lambda s: "finish" if s.get("error") else "next",
        _guard("request_deployment_approval"),
    )
    graph.add_conditional_edges("request_deployment_approval", _after_deploy_approval, {
        "finish": "finish_or_stop", "next": "deploy_release",
    })
    graph.add_conditional_edges(
        "deploy_release", lambda s: "finish" if s.get("error") else "next",
        _guard("verify_deployment"),
    )
    graph.add_conditional_edges(
        "verify_deployment", lambda s: "finish" if s.get("error") else "next",
        _guard("evaluate_result"),
    )
    graph.add_edge("evaluate_result", "finish_or_stop")
    graph.add_edge("finish_or_stop", END)

    return graph.compile(checkpointer=checkpointer)


# ---------------------------------------------------------------------------
# routers
# ---------------------------------------------------------------------------
def _after_diagnosis(state: WorkflowState) -> str:
    if state.get("error") or state.get("outcome_status") == "completed":
        return "finish"
    diagnosis = state.get("diagnosis") or {}
    if not diagnosis.get("has_incident"):
        return "finish"
    return "next"


def _after_repair_approval(state: WorkflowState) -> str:
    if state.get("error"):
        return "finish"
    return "next" if state.get("approval_decision") == "approved" else "finish"


def _after_workspace(state: WorkflowState) -> str:
    if state.get("error") or state.get("outcome_status") in {"needs_human", "failed"}:
        return "finish"
    return "next"


def _after_agent(state: WorkflowState) -> str:
    if state.get("error"):
        return "finish"
    if state.get("outcome_status") in {"needs_human", "failed", "cancelled"}:
        return "finish"
    repair = state.get("repair") or {}
    if repair.get("status") != "success":
        return "finish"
    return "next"


def _after_tests(state: WorkflowState) -> str:
    if state.get("error"):
        return "finish"
    tests = state.get("tests") or {}
    if tests.get("status") == "passed":
        return "next"
    attempt = int(state.get("attempt") or 0)
    max_attempts = int(state.get("max_attempts") or 3)
    # ``run_tests`` increments ``attempt`` on failure, so the cap is enforced
    # even if the same error keeps repeating (no infinite repair loop).
    return "retry" if attempt < max_attempts else "finish"


def _after_review(state: WorkflowState) -> str:
    if state.get("error"):
        return "finish"
    review = state.get("review") or {}
    return "next" if review.get("ok") else "finish"


def _after_deploy_approval(state: WorkflowState) -> str:
    if state.get("error"):
        return "finish"
    decision = state.get("deployment_approval_decision")
    if decision == "rejected":
        return "finish"
    if decision in {"approved", "skipped"}:
        return "next"
    return "finish"
