# Demo script (5 minutes)

**Before you start**

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\run.ps1 -SkipTests
```

Open <http://127.0.0.1:8000/> and keep a second terminal ready for the MCP part.
Everything below runs with `DEMO_MODE=true`, no token, no LLM.

The demo project is `demo-django-store`: after a release, the storefront returns HTTP 500 because
`django_filters` is imported at boot while the dependency is missing. CPU peaks at 9.8 % and memory
at 38.2 %, so resources are **not** the cause. One log line contains a prompt-injection attempt on purpose.

---

## 0:00 – 0:30 · Introduction

- Show the **Overview** page. Point at the persistent **DEMO / SIMULATED** badge.
- One sentence: «LiaraPilot یک مهندس زیرساخت است: شواهد را از لیارا می‌خواند، علت را توضیح
  می‌دهد، قبل از هر تغییر حساس از من تأیید می‌گیرد و بعد از انتشار سلامت را بررسی می‌کند.»
- Say clearly: *this run is simulated — no request goes to api.liara.ir.*

## 0:30 – 1:30 · Diagnosis

- Press **اجرای سناریوی دمو** (scenario `django_500`).
- Narrate the live timeline: `دریافت درخواست → تشخیص پروژه → جمع‌آوری شواهد`.
- Open the evidence panel: 19 log lines, **10 error-level lines**, 6 responses with status 5xx, the
  CPU (avg 8.25 %, peak 9.8 %) and memory (avg 37.24 %, peak 38.2 %) series, and release history
  (`rel-demo-1042`, `v1.4.2`).

## 1:30 – 2:30 · Analysis

- Read the four key blocks:
  * **مشاهده** — `ModuleNotFoundError: No module named 'django_filters'` at boot.
  * **شواهد** — log lines + evidence IDs, `CPU/RAM در محدوده نرمال`.
  * **علت محتمل** — missing dependency (confidence: high) with alternatives listed.
  * **ریسک / روش بررسی** — release risk, and "after deploy /healthz must be 200, no new 500s".
- Point out the sanitisation note: the injection line inside an access log was neutralised.

## 2:30 – 3:30 · Approval + repair

- The graph is paused at **درخواست تأیید** — note the approval ID, TTL, and exact parameters.
- Press **تأیید و ادامه**.
- Watch: isolated workspace created, branch `ai-fix/<id>`, coding agent applies the two-file patch
  (`requirements.txt`, `store/settings.py`), then **real** `pytest` runs inside the workspace:
  4 tests pass. Show the diff and the "SIMULATED PATCH" label.

## 3:30 – 4:30 · Deployment + health

- Second approval appears (high risk, release parameters visible).
- Press **تأیید و ادامه**.
- Source archive is built (exclusions listed), `sourceID` returned, then `releaseID` +
  `SIMULATED RELEASE`.
- Health check: **verified**, observed 200, marked simulated. Final report appears with
  outcome `completed`, stop reason `deployed_and_verified`, limitations listed.

## 4:30 – 5:00 · Real capabilities

- **تنظیمات**: live prerequisites (token, writes, deploy flag, allowlist, health URL) — show
  exactly what is blocking live mode today.
- **اتصال MCP**: show `claude mcp add liarapilot -- python -m app.mcp.server` and the tool table.
- Optionally in a terminal:

  ```bash
  python -m app.mcp.server --selftest
  ```

  → JSON with 13 tools, `sample_call_ok: true`, `mode: demo`.

---

## Expected numbers (verified by the test suite)

| Item | Expected |
|---|---|
| Log lines analysed | 19 (10 error/critical, 6 with 5xx) |
| CPU / memory | avg 8.25 % / 37.24 %, peak 9.8 % / 38.2 % (both normal) |
| Prompt-injection lines neutralised | ≥ 1 |
| Diagnosis | `missing_dependency`, confidence `high`, engine `rule_engine` |
| Files changed by the mock agent | `requirements.txt`, `store/settings.py` |
| Tests | `pytest`, exit code 0, 4 passed |
| Release | `rel-demo-…`, `simulated: true`, state `ready` |
| Verification | `verified`, observed 200, `simulated: true` |
| Approvals | 2, both `approved` and `consumed_at` set |
| Final outcome | `completed` / `deployed_and_verified` |

## Optional alternate scenarios

* `memory_pressure` — `demo-node-api`: `FATAL ERROR: Reached heap limit`, memory ≈ 96 %;
  the agent diagnoses OOM and argues with numbers instead of blaming CPU.
* `healthy_site` — `demo-blog`: no incident; the workflow **stops** without proposing a repair
  (proof that the assistant does not "fix" healthy systems).

## If something goes wrong during the demo

| Symptom | Fix |
|---|---|
| Port 8000 busy | `.\scripts\run.ps1 -PortNumber 8080` |
| Stale demo state | press **لغو گردش‌کار** and rerun, or delete `data/*.db`, `data/langgraph-checkpoints.sqlite` |
| Tests fail on start | `.\scripts\run.ps1 -SkipTests` (the demo does not depend on the test suite) |
| `.env` rejected | `python scripts/validate_config.py` prints the exact key |
