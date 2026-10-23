# Architecture

## 1. Goals and constraints

| Goal | How it is met |
|---|---|
| Demo must run with no token, no LLM, no network | `MockLiaraAdapter` behind the same contract as the live adapter; rule-based diagnosis |
| Evidence over assertions | Every diagnosis cites persisted `EvidenceRecord` IDs; deployment success requires a health check |
| Human control over risky actions | LangGraph `interrupt` + server-side approval objects (TTL, parameter fingerprint, single use) |
| Restart-safe | LangGraph `AsyncSqliteSaver` checkpointer + SQL records for workflow state |
| One logic path for UI and agents | `AppContainer` wires services once; FastAPI routes and MCP tools both call them |
| No shell-injection surface | Subprocesses are fixed argv arrays from an allowlist; never a shell string |

## 2. Component map

```
                    ┌──────────────────────────────┐
  Browser (fa/RTL)  │ Jinja2 templates + app.js    │
                    └──────────────┬───────────────┘
                                   │ fetch /api/*
┌──────────────────────────────────▼───────────────────────────────────┐
│ FastAPI (app/main.py)                                                │
│  • auth middleware (only when APP_AUTH_ENABLED)                      │
│  • AppError → JSON/HTML error mapping                                │
│  routes: dashboard · projects · diagnosis · workflows · approvals     │
│          settings · demo · health                                    │
└───────────────┬──────────────────────────────────────┬───────────────┘
                │                                      │
┌───────────────▼──────────────┐        ┌──────────────▼───────────────┐
│ MCP server (stdio)           │        │ WorkflowRunner               │
│  13 tools → ToolHandlers     │        │  start / resume / cancel     │
└───────────────┬──────────────┘        └──────────────┬───────────────┘
                │                                      │
                └──────────────┬───────────────────────┘
                               ▼
                  ┌────────────────────────────┐
                  │ Services (single source)   │
                  │ diagnosis · approval       │
                  │ coding_agent · deployment  │
                  │ verification · audit       │
                  └──────┬───────────┬─────────┘
                         │           │
             ┌───────────▼──┐   ┌────▼──────────────────┐
             │ LiaraAdapter │   │ Repository (SQLAlchemy)│
             │ mock │ live  │   │ SQLite (Postgres-ready)│
             └───────────┬──┘   └───────────────────────┘
                         ▼
              https://api.liara.ir (httpx)
```

## 3. Request lifecycle (incident)

1. `POST /api/workflows` (or the demo button) creates a `WorkflowRun`, an initial
   `WorkflowEvent`, and starts `WorkflowRunner.start()` as a background task.
2. LangGraph runs nodes from `app/agent/nodes.py`. Each node:
   - opens `_step()` (writes a `running` event, sets `current_step/status`),
   - performs one unit of work through a service,
   - writes a `completed`/`failed` event with `step_key` (`{workflow}:{attempt}:{step}:{phase}`)
     so re-execution after an interrupt resume cannot duplicate bookkeeping.
3. At `request_human_approval` the node creates an `ApprovalRequest` and calls
   `interrupt(payload)`. LangGraph persists the checkpoint and the runner marks the run
   `waiting_for_approval`.
4. The UI calls `POST /api/approvals/{id}/approve|reject`. The decision is recorded, then
   `POST /api/workflows/{id}/resume` (implicitly triggered by the same route) resumes the graph
   with `Command(resume={approval_id, decision})`.
5. The node re-executes from the interrupt point, validates the approval again
   (status/expiry/owner/stage), consumes it, and continues.
6. Stage 2 repeats the pattern for the deployment approval before `POST /v2/.../releases`.

## 4. Why two interrupts instead of one

The repair approval and the deployment approval protect different risks:

* repair approval → creating files in a workspace + uploading a source archive;
* deployment approval → creating a release that replaces running production traffic.

Deployment parameters (sourceID, port, type) only exist after packaging, so the approval must be
requested after `prepare_deployment`. The fingerprint binds the approval to those exact values.

## 5. Persistence

| Data | Store | Notes |
|---|---|---|
| Workflow rows, events, evidence, approvals, deployments, agent runs, audit | SQLite via SQLAlchemy (`app/db/`) | no SQLite-specific column types; `DATABASE_URL` switch is enough for Postgres |
| LangGraph state / interrupts | `langgraph-checkpoints.sqlite` (`AsyncSqliteSaver`) | survives process restarts |
| Audit mirror | `data/audit.jsonl` | append-only, same redaction as SQL |
| Source archives | `data/artifacts/<workflow>/source-<attempt>.tar.gz` | SHA-256 recorded |
| Workspaces | `data/workspaces/<workflow>/` | created per attempt, confined to root |
| Demo repository | `app/demo_fixtures/django_store/` | sample data, not runtime state |

Checkpoint and SQL are written in the same node execution; the `step_key` uniqueness makes the
two stores converge to the same story after a crash (the SQL event is skipped if it already
exists, while the graph simply re-runs the node).

## 6. Model boundary

```
Evidence (structured, sanitized)  ──►  rule engine  ──►  DiagnosisReport (baseline)
                                             │
                            (optional, if LLM enabled)
                                             ▼
                               LLMAdvisor.refine()  ──► prose only
                                             │
                              evidence_refs must already exist;
                              malformed output → baseline kept
```

The model never:

* receives the Liara token or any secret,
* selects an API endpoint or builds URLs,
* executes a tool directly (MCP callers are separate clients),
* authorises an action (approvals are server-side rows),
* decides whether verification passed (that is the HTTP health check).

## 7. Coding-agent boundary

`CodingAgentService` enforces: workspace under `CODING_AGENT_WORKSPACE_ROOT`, `.env*` removed before
the agent starts, environment filtered (`LIARA_*`, `APP_*`, `LLM_*`, `*_TOKEN`, `*_SECRET`), fixed
CLI argv (no shell), hard timeout with process-group kill, and an allowlisted test command
(`pytest`, `npm test`, or `compileall`). The agent's diff is snapshotted before/after, reviewed, and
blocked if it touches sensitive paths or exceeds 25 files. Nothing is pushed to a remote.

## 8. Failure and stop semantics

| Situation | Result |
|---|---|
| No incident in evidence | `completed` / `no_incident_detected` (no repair proposed) |
| Repair rejected | `cancelled` / `repair_rejected_by_user` |
| Deploy rejected | `cancelled` / `deployment_rejected_by_user` (source already uploaded, no release) |
| Tests fail | attempt++, retry repair until `max_attempts` (≤ 3), then `failed`/`needs_human` |
| Diff touches sensitive files | `failed`, deployment blocked |
| Release state `failed` | `failed` / `release_failed` |
| Health check fails | `failed` / `health_check_failed` |
| Health check unavailable | `completed` / `deployed_unverified` (explicitly not success) |
| Coding CLI missing | `needs_human` with a manual handoff file |
| Policy violation (allowlist, flags) | `needs_human` with the exact reason |

## 9. Extension points

* **PostgreSQL**: change `DATABASE_URL`, add `asyncpg`, keep the repository API.
* **New diagnosis rule**: append a `CauseRule` to `RULES` in `app/services/diagnosis_service.py`.
* **New MCP tool**: add a `ToolSpec`, a handler in `ToolHandlers`, and register it in `app/mcp/server.py`.
* **New coding CLI**: implement `BaseCodingAgent` and add it to `CodingAgentService.agents`.
