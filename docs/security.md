# Security model

## 1. Secrets

| Secret | Storage | Exposure rules |
|---|---|---|
| `LIARA_API_TOKEN` | `.env` (git-ignored) | Never in the UI, logs, audit, prompts, workspaces or coding-agent env. Registered with the redactor at client construction. |
| `APP_SECRET_KEY` | `.env` | Signs session cookies. Must be random for non-local use (`APP_ENV=production` refuses the placeholder). |
| `APP_ACCESS_TOKEN` | `.env` | UI access when `APP_AUTH_ENABLED=true`; compared with `hmac.compare_digest`. |
| `LLM_API_KEY` | `.env` | Only used by the optional advisor; never logged. |

`.gitignore` excludes `.env`, `*.pem`, `*.key`, and all runtime data. `.env.example` contains no real
value. `scripts/setup_env.py` only fills a local random `APP_SECRET_KEY` when creating `.env`.

Redaction (`app/core/logging.py`) is applied at the logging handler level, in audit records, in API
error bodies, and to log lines before they reach the database or a model prompt. It masks
`Authorization` headers, bearer tokens, `api_key`/`token`/`secret` assignments, `liara_*` and `sk-*`
shaped strings, plus every literal secret explicitly registered.

## 2. Policy gates for write operations

```python
# demo mode → simulated writes, no network
# live mode:
ensure_writes_enabled()    # LIARA_ALLOW_WRITES=true
ensure_deploys_enabled()   # + LIARA_ENABLE_DEPLOY=true
ensure_deploy_allowed()    # project ∈ LIARA_DEPLOY_ALLOWED_PROJECTS (empty list = deny all)
```

These are enforced in the **service** layer (`DeploymentService.prepare/deploy`), so they apply to
the HTTP API, MCP tools and any future transport. There is no "force" flag and no client-side
override.

## 3. Human-in-the-loop approvals

`ApprovalRequest` rows carry: workflow, stage (`repair` | `deploy`), action, project, risk level,
title/reason, JSON parameters, SHA-256 fingerprint, `requested_at`, `expires_at`, `status`
(`pending|approved|rejected|expired`), `decided_*`, `consumed_at`, `simulated`.

Consumption (`ApprovalService.validate_and_consume`) checks ownership → stage → status → not
consumed → not expired → fingerprint match, then sets `consumed_at`. Consequences:

* a client cannot approve with `{"approved": true}`; it must reference a DB row,
* approvals cannot be replayed (single use),
* changing any parameter invalidates the approval,
* TTL expiry is enforced on read and on consumption,
* the deterministic ID `apv-<workflow>-<stage>-<attempt>` makes graph re-execution idempotent
  without ever reviving a consumed/expired approval.

Risk classification (`classify_risk` and `classify` in the UI): low (read-only), medium (workspace
edits, branch creation, source packaging), high (production release, git push, env change, restart,
DNS/database changes). High-risk actions always request approval; `HITL_*` settings allow tightening
but the defaults require them.

## 4. Workspace and coding-agent isolation

* Workspaces are created under `CODING_AGENT_WORKSPACE_ROOT`; every path goes through
  `assert_within()` (resolves symlinks and rejects escapes).
* `.env*` files are deleted before any agent runs; `.git` internals, `node_modules`, virtualenvs,
  caches and credential files are excluded from packaging (`app/liara/source_packager.py`).
* The subprocess environment is filtered (`sanitized_env`): `LIARA_*`, `APP_*`, `LLM_*`,
  `DATABASE_URL`, `LANGGRAPH_*`, `AUDIT_*`, and anything matching `*_TOKEN|*_SECRET|*_PASSWORD|*_API_KEY`
  are removed. The Liara token never reaches Claude Code or Codex.
* Commands are fixed argv arrays (`start_new_session=True`), never shell strings, with a hard
  timeout that kills the whole process group. Test commands come from an allowlist:
  `python -m pytest`, `npm test`, or `python -m compileall`.
* CLI permissions are not bypassed: no `--dangerously-skip-permissions`, no `--yolo`, no
  `--dangerously-bypass-approvals-and-sandbox`, no `danger-full-access`. Claude Code uses
  `--permission-mode acceptEdits` with `--allowedTools Read,Edit,Write,Glob,Grep`; Codex uses
  `--sandbox workspace-write`.
* Diff review blocks changes to `.env*`, keys/certificates, `.git/`, absolute paths, and more than
  25 changed files. Tests must pass afterwards, or deployment does not happen.
* Git: only a local branch `ai-fix/<workflow-id>` is created. `CODING_AGENT_ALLOW_GIT_PUSH=false`
  by default; when enabled it still requires an explicit approval.

## 5. Input validation and SSRF

* Project names: `^[a-zA-Z0-9][a-zA-Z0-9._-]{0,62}$` plus explicit `..`, `/`, `\` rejection before
  any URL or path construction; the project must also exist in the adapter's real project list.
* Request text: 3–4000 characters; API payloads use Pydantic schemas with limits.
* Health-check URLs: http(s) only; blocked hostnames; resolved addresses must not be private,
  loopback, link-local or reserved.
* Response size: source archives are capped by `LIARA_SOURCE_UPLOAD_MAX_MB`; log messages are
  truncated; API error bodies are truncated to 400 chars.

## 6. Untrusted content (logs, prompts)

Log content is treated as data:

1. ANSI escapes and control characters stripped,
2. secrets redacted,
3. instruction-like patterns (`ignore previous instructions`, `deploy without approval`,
   `reveal the token`, …) replaced with `[filtered-untrusted-instruction]` and counted in
   `sanitization.instruction_like_lines`,
4. the LLM prompt labels the block as untrusted and forbids following it,
5. no log content is ever executed, used to build a URL, or used to authorise an action.

## 7. Application authentication

Loopback development runs with `APP_AUTH_ENABLED=false`. Any non-local `APP_HOST` without auth makes
startup fail (configuration validation). When enabled:

* API clients use `X-App-Token` (or `Authorization: Bearer <APP_ACCESS_TOKEN>`),
* the UI uses an HMAC-signed session cookie (HttpOnly, SameSite=Lax, 12 h) issued by `/login`,
* `/api/health` stays public for probes; all other `/api/*` routes require the token,
* failed logins return 401 without revealing whether the token length was close.

## 8. Audit

Every meaningful transition writes an `AuditEvent` (SQL) and a JSONL line: workflow lifecycle,
approval request/decision/consumption/expiry, Liara HTTP calls (method, path, status, duration,
attempt — never headers), coding-agent runs, test execution, deployments, verification, MCP tool
calls. Details are redacted before persistence.

## 9. Known residual risks

* The health check can be pointed at an external URL by the operator; the SSRF guard reduces but
  cannot eliminate that trust decision.
* A malicious repository fixture could still influence the coding agent within the workspace
  (network access is a CLI sandbox concern). Deployments remain gated by approvals and tests.
* SQLite is not encrypted at rest; the MVP assumes a developer workstation. Use full-disk
  encryption and PostgreSQL for production.
* MCP stdio trusts the local client by design; do not expose the MCP server to untrusted processes.
