# Status, mock vs. real, and known limitations

_Last updated: 2026-10-22. This file reflects what was actually executed, not what was designed._

## 1. Implemented and verified by execution

| Capability | Evidence |
|---|---|
| Demo mode with no token, LLM, Docker or network | `pytest` (137 offline tests), manual run on the sandbox host |
| Full incident flow: 500 → evidence → diagnosis → approval → repair → tests → approval → release → health → report | `tests/test_workflow_e2e.py::test_full_incident_flow_completes_with_verification` |
| Evidence structure (observation, evidence + IDs, cause, alternatives, confidence, action, risk, verification) | `tests/test_diagnosis.py` |
| Resource-vs-logs discrimination (CPU/RAM not blamed without evidence) | same |
| Prompt-injection neutralisation in logs | same + `tests/test_mcp.py` |
| Persistent checkpoint + resume after restart | `test_workflow_is_resumable_after_restart` (second app instance, same DB/checkpoints) |
| Approval TTL, single use, parameter fingerprint, stage/owner checks | `tests/test_security.py` |
| Rejection paths (repair / deploy) stop the workflow correctly | `tests/test_workflow_e2e.py` |
| Idempotency: repeated approve → 409; no second release | same |
| Liara client: URLs, headers, retries, 401/403/404/409/422/429/5xx, timeout, rate limit, redaction, response validation | `tests/test_liara_client.py` |
| Mock/Live adapter contract equality | `tests/test_adapter_contract.py` |
| Source packaging excludes `.env*`, `.git`, `node_modules`, caches, keys; symlink/escape protection; size limit | `tests/test_security.py` |
| Workspace confinement and environment filtering for coding agents | `app/services/coding_agent_service.py`, `app/coding_agents/base.py`; asserted by review tests |
| MCP: 13 tools, schemas, read tools, gated deploy, stdout cleanliness | `tests/test_mcp.py`, `python -m app.mcp.server --selftest` |
| Persian RTL UI: dashboard, projects, diagnose, workflows, approvals, settings, MCP page | `tests/test_api.py` (rendered with `dir="rtl"`, `lang="fa"`) |
| Audit trail (SQL + JSONL, redacted) | `tests/test_workflow_e2e.py::test_audit_trail_is_recorded` |
| Config validation, unknown-key rejection, non-local-bind guard, readiness report | `tests/test_config.py`, `scripts/validate_config.py` |
| Launcher scripts (`scripts/run.ps1`, `scripts/run.sh`) | `run.sh` executed in this environment; `run.ps1` reviewed but not executed (no PowerShell here) |

## 2. Simulated in Demo Mode (clearly labelled in the UI and the report)

* All Liara data: projects, logs, metrics, releases.
* The coding agent's patch: it edits real files in a real isolated workspace and real `pytest` runs,
  but the agent decision is deterministic (`MockCodingAgent`).
* Source upload, release creation, health check: simulated by `MockLiaraAdapter`
  (`simulated: true`, `DEMO / SIMULATED` badges everywhere).

## 3. Implemented but not executed here (needs external access)

| Item | Why not executed | How to verify |
|---|---|---|
| Real Liara API calls (`GET /v1/...`, `POST /v2/...`) | no Liara account/token in the sandbox | `LIARAPILOT_RUN_LIVE=1 LIARA_API_TOKEN=... pytest -m live` |
| Real deployment (source upload + release + state polling) | same; also writes must be enabled | live mode + `LIARA_ALLOW_WRITES=true`, `LIARA_ENABLE_DEPLOY=true`, project allowlisted |
| `ClaudeCodeAdapter` real runs | `claude` CLI not installed here | install Claude Code, set `CODING_AGENT_PROVIDER=claude_code`, `CODING_AGENT_AUTO_EXECUTE=true` |
| `CodexAdapter` real runs | `codex` CLI not installed here | install Codex CLI, set `CODING_AGENT_PROVIDER=codex`, `CODING_AGENT_AUTO_EXECUTE=true` |
| Optional LLM refinement | `LLM_PROVIDER=disabled`, no API key | set `LLM_PROVIDER=openai_compatible` + `LLM_BASE_URL`/`LLM_MODEL`/`LLM_API_KEY` |
| MCP connection from Claude Code / Codex clients | clients not installed here | `claude mcp add liarapilot -- python -m app.mcp.server` (see docs/mcp.md) |
| Health check against a real URL | no public app URL | set `DEPLOY_HEALTHCHECK_URL` |
| `scripts/run.ps1` end-to-end | Linux sandbox | run on Windows 11 |

## 4. API / platform limitations (from the official docs)

* **Log `since` format is undocumented** (typed as string). The client tries ISO-8601 then epoch
  seconds; this is recorded in `docs/liara-api.md`.
* **No documented release-by-id endpoint**: release state is polled from the releases list and may
  remain `unknown`.
* **No documented public health endpoint**: verification is `unverified` without
  `DEPLOY_HEALTHCHECK_URL`; this is never reported as success.
* **No documented automatic rollback**: LiaraPilot proposes a recovery path instead of acting.
* **Release `type`/`port` have no documented enums**: `type` is taken from `project.type` (and the
  deployment is refused if unknown); `port` is taken from the previous release or
  `LIARA_DEFAULT_PORT`.
* Auth scheme ambiguity (apiKey vs bearer) is handled explicitly via `LIARA_AUTH_SCHEME`.

## 5. Deliberately out of scope (MVP)

* Streamable HTTP / remote MCP transport (no auth story yet).
* PostgreSQL (schema and repository are migration-ready; only SQLite is wired).
* Multi-user accounts, RBAC, per-user audit attribution (single local operator).
* Real-time streaming (SSE/WebSocket) — the UI polls the workflow endpoint.
* Automatic rollback, restart, plan change, env-var change, DNS operations (high-risk actions that
  are intentionally not automated; they appear only as risk categories).
* Native (non-mock) LLM-driven tool selection loops inside the workflow graph: the graph is
  deterministic by design, the LLM is an advisory writer only.
* i18n beyond fa-IR (UI) and English (code/docs).

## 6. Operational notes

* SQLite + WAL: fine for one operator; use PostgreSQL for concurrent users.
* SQLite files are not encrypted; protect the workstation (`data/` is git-ignored).
* The demo fixtures (`app/demo_fixtures/`) are sample data and are packaged with the app on purpose.
* `DEMO_STEP_DELAY_SECONDS` (default 0.35 s) only paces the demo UI; tests set it to 0.
