# MCP server

`app/mcp/server.py` exposes LiaraPilot to Claude Code, Codex and any MCP client over **stdio**.
The tools are LiaraPilot's own contract — they are **not** Liara API endpoints.

```bash
python -m app.mcp.server             # serve on stdio
python -m app.mcp.server --selftest  # in-process smoke test (JSON on stdout)
```

* **stdout is reserved for the protocol.** `configure_logging()` installs a stderr handler; the MCP
  `MCPServer` is created with `log_level="ERROR"`. `--selftest` prints one JSON object so CI can
  assert that stdout stays parseable.
* Built on the MCP Python SDK **2.3.0** (`mcp.server.mcpserver.MCPServer`; FastMCP was renamed to
  `MCPServer` in SDK 2.x).
* The server uses the same `AppContainer` as the web app, so allowlists, write flags and
  approval checks are identical for humans and agents.

## Transports

| Transport | Status | Notes |
|---|---|---|
| stdio | ✅ implemented (MVP default) | for local Claude Code / Codex |
| Streamable HTTP | ❌ not implemented | would need authentication; out of MVP scope |

## Tools

Legend — **kind**: `read` (no side effects) / `prepare` (analysis or local packaging) /
`sensitive` (changes state; needs a server-side approval). **risk**: `low` / `medium` / `high`.

| Tool | kind | risk | Input | Output (highlights) | Errors |
|---|---|---|---|---|---|
| `liara_list_projects` | read | low | `limit?: int` | `mode, simulated, count, projects[]` | `liara_auth_error`, `upstream_unavailable` |
| `liara_get_project_status` | read | low | `project: str` | status, type, plan, `env_keys[]` (names only) | `not_found`, `validation_error` |
| `liara_get_logs` | read | low | `project`, `minutes?`, `limit?` | sanitised lines, `flagged_instruction_lines` | `not_found` |
| `liara_get_cpu_metrics` | read | low | `project`, `minutes?` | series summary + points | `upstream_unavailable` |
| `liara_get_memory_metrics` | read | low | `project`, `minutes?` | series summary + points | `upstream_unavailable` |
| `liara_get_release_history` | read | low | `project`, `count?` | releases, `current_release`, `platform` | `not_found` |
| `liara_diagnose_project` | read | low | `project`, `request_text?` | full diagnosis report + `evidence_ids[]` | `not_found` |
| `liara_prepare_repair` | prepare | medium | `project`, `request_text?` | repair plan, probable cause, next step | `not_found` |
| `liara_prepare_deployment` | prepare | medium | `project` | `ready`, `blockers[]`, `warnings[]`, `release_params{port, port_source, project_type}` | `not_found`, `upstream_unavailable` |
| `liara_get_workflow_status` | read | low | `workflow_id` | status, steps, `pending_approval`, `final_report` | `not_found` |
| `liara_request_approval` | sensitive | high | `workflow_id`, `stage: repair\|deploy` | `approval_id`, `expires_at`, `params` | `not_found`, `validation_error` |
| `liara_deploy_approved_source` | sensitive | high | `workflow_id`, `approval_id` | `release_id`, `release_state`, `simulated` | `policy_violation`, `validation_error`, `not_found` |
| `liara_verify_deployment` | sensitive | medium | `workflow_id` | `verification{status, observed_status, …}`, `verified` | `validation_error` |

Every result is wrapped as
`{"ok": true|false, "tool": "...", "kind": "...", "risk_level": "...", "result"|"error": {...}}`
so an agent always sees whether an action succeeded and why it failed.

## Approval policy for agents

An agent **cannot approve anything**. `liara_request_approval` only *creates* a request; a human
decides in the web UI (`/approvals`). `liara_deploy_approved_source` then requires the
`approval_id`, and the server verifies, in order:

1. the approval exists and belongs to this workflow,
2. its stage matches (`deploy`),
3. status is `approved` (not `pending` / `rejected` / `expired`),
4. it has not been consumed already,
5. it has not expired (`HITL_APPROVAL_TTL_MINUTES`),
6. its SHA-256 parameter fingerprint equals the current `{project, source_id, port, project_type}`.

Only then is it consumed and the release request issued. Repeating the call returns an
idempotent replay of the stored `release_id` instead of creating a second release. A boolean
argument has no effect anywhere in this path.

Write tools additionally require, in **live** mode:
`LIARA_ALLOW_WRITES=true`, `LIARA_ENABLE_DEPLOY=true`, and the project in
`LIARA_DEPLOY_ALLOWED_PROJECTS`.

## Connecting clients

### Claude Code

```bash
claude mcp add liarapilot -- python -m app.mcp.server
claude mcp list
```

or `.mcp.json` in the project root (already included):

```json
{
  "mcpServers": {
    "liarapilot": {
      "command": "python",
      "args": ["-m", "app.mcp.server"],
      "env": { "DEMO_MODE": "true" }
    }
  }
}
```

On Windows use the venv interpreter, e.g.
`"command": ".venv\\Scripts\\python.exe"`.

### Codex

`~/.codex/config.toml`:

```toml
[mcp_servers.liarapilot]
command = "python"
args = ["-m", "app.mcp.server"]
env = { DEMO_MODE = "true" }
```

Or `codex mcp add liarapilot -- python -m app.mcp.server`. Verify flags for your CLI version with
`codex mcp add --help`; MCP configuration syntax has changed between Codex releases.

## Suggested agent loop

1. `liara_list_projects` → choose the project.
2. `liara_diagnose_project` → read the evidence-based report.
3. `liara_prepare_repair` → show the plan to the human (no production change).
4. Human approves the repair in the UI; `liara_get_workflow_status` shows tests/diff progress.
5. `liara_prepare_deployment` → blockers/warnings and exact release parameters.
6. After the human approves the deployment, `liara_deploy_approved_source`.
7. `liara_verify_deployment` → report `verified` / `failed` / `unverified` honestly.

## Testing

`tests/test_mcp.py` verifies: all 13 tools registered, descriptions + input schemas present,
read tools work in demo mode, the deploy tool refuses unknown workflows/approvals, the tool wrapper
converts policy errors into structured failures, and `--selftest` writes only JSON to stdout.
