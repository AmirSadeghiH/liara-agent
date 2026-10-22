# Liara API integration

Source of truth: <https://developers.liara.ir/> (checked **2026-10-22**, OpenAPI spec
`/spec/paas.yaml`). Only endpoints listed below are called. Paths are asserted in
`LiaraClient._request()` — anything outside `/v1/...` or `/v2/...` raises immediately.

## Implemented endpoints

| Method | Path | Purpose | Required parameters | Response model |
|---|---|---|---|---|
| `GET` | `/v1/projects` | list projects | — | `{"projects": [{_id, project_id, type, status, scale, planID, created_at, isDeployed}]}` |
| `GET` | `/v1/projects/{name}` | project details | path `name` | `{"project": {..., envs[]}}` |
| `GET` | `/v1/projects/{name}/logs` | logs | path `name`, query **`since`** (string, required) | `[{type, datetime, message}]` |
| `GET` | `/v1/projects/{name}/metrics/cpu` | CPU report | path `name`, query **`since`** (number, epoch) | `{end, result:[{applet, values:[[ts, value]]}]}` |
| `GET` | `/v1/projects/{name}/metrics/memory` | memory report | same as CPU | same |
| `GET` | `/v1/projects/{name}/metrics/summary` | summary report | path `name` | `{cpuUsage, memoryUsage, disksUsage}` |
| `GET` | `/v1/projects/{name}/releases` | release history | path `name`, query **`page`**, **`count`** | `{total, currentRelease, readyReleasesCount, releases[], platform}` |
| `POST` | `/v2/projects/{name}/sources` | upload source archive | path `name`, multipart field **`file`** (`.gz`) | `{"sourceID": "..."}` |
| `POST` | `/v2/projects/{name}/releases` | create release | path `name`, JSON `{sourceID, port, type}` | `{"releaseID": "..."}` |

Documented error responses (400/401/404; plus 403/409/422/429/5xx seen in practice) are mapped to
typed errors in `app/liara/errors.py`.

## Authentication

The spec declares **two** security schemes for every operation:

```yaml
securitySchemes:
  jwt:        { type: apiKey, in: header, name: Authorization }
  bearerAuth: { type: http, scheme: bearer, bearerFormat: JWT }
```

Every documented request example, however, sends the raw token:

```bash
curl --request GET --url https://api.liara.ir/v1/projects \
  --header 'Authorization: <api-key>'
```

**Decision:** the documented request examples are authoritative, so the default is
`LIARA_AUTH_SCHEME=token` → `Authorization: <token>`. Accounts that require the HTTP scheme can set
`LIARA_AUTH_SCHEME=Bearer` → `Authorization: Bearer <token>`. This discrepancy is called out here
and in `.env.example` instead of being silently guessed.

## Known documentation gaps and how they are handled

1. **`since` format for logs.** The spec types it as `string` without a format. The client first
   sends ISO-8601 (`2026-10-22T20:00:00.000+00:00`); if Liara answers `400`/`422`, it retries
   **once** with epoch seconds. Both attempts are audited; the fallback is visible in the audit log.
2. **`since` unit for metrics.** Typed as `number`; treated as epoch **seconds**
   (`now - 3600` by default). Client-side timestamp filtering is deliberately **not** applied, so
   values are not dropped when the server clock differs.
3. **Release `type`.** `Deploy-releases.type` is a free-form string ("The platform of your app").
   No allowed-values enum is documented. LiaraPilot reads `project.type` from
   `GET /v1/projects/{name}` and **refuses to deploy** if it is unavailable rather than guessing.
4. **Release `port`.** Free-form number. The port of the most recent release
   (`GET /v1/projects/{name}/releases`) is reused; if none exists, `LIARA_DEFAULT_PORT` is used and
   recorded as `port_source=LIARA_DEFAULT_PORT` in the deployment record and in the approval
   parameters.
5. **Release status polling.** There is no documented "get release by id" endpoint. LiaraPilot
   polls `GET /v1/projects/{name}/releases?page=1&count=20` (6 attempts, 5 s apart) and records
   `release_state`; if the release never appears, the state is `unknown` and verification relies on
   the health check. `releaseID` is never assumed to mean "deployed".
6. **Health endpoint.** No documented public health/HTTP probe exists. `DEPLOY_HEALTHCHECK_URL`
   must be provided by the operator; when absent the verification status is **`unverified`**.
7. **Events endpoint** (`GET /v1/projects/{name}/events`) exists and is documented, but its
   `metaData`/`values` shape is untyped in the spec, so the MVP does not consume it.
8. **No documented rollback endpoint.** The MVP therefore offers no automatic rollback; the final
   report suggests a recovery path instead.

## Client behaviour

* **Base URL** — `LIARA_BASE_URL` (default `https://api.liara.ir`); URLs are built as
  `base + documented path` only.
* **Timeouts** — `LIARA_REQUEST_TIMEOUT_SECONDS` (default 30) applied via `httpx.Timeout`.
* **Retries** — `LIARA_MAX_RETRIES` (default 2) for **idempotent GETs only**, on `429`, `500`,
  `502`, `503`, `504`, timeouts and connection errors. Delay honours `Retry-After` and is capped at
  5 s with exponential backoff (0.5 s, 1 s, 2 s…). `POST` requests are **never** retried.
* **Rate limit** — `429` is treated as retryable with a bounded attempt count; exhaustion raises
  `LiaraRateLimitError`.
* **Error separation** — auth (`401`/`403`) vs. network (`LiaraNetworkError`/`LiaraTimeoutError`) vs.
  service (`5xx`) vs. contract (`LiaraResponseError`) are distinct classes.
* **Validation** — every response is parsed with Pydantic models in `app/liara/schemas.py`;
  unknown vendor fields are tolerated, missing required fields raise `LiaraResponseError`.
* **Redaction** — the token is registered with the redactor at client construction. `Authorization`
  headers are never logged; audit records contain only method, path, status, duration, attempt.
* **Env values** — `ProjectDetails` keeps only environment variable *names*; values are discarded
  during parsing so they cannot reach the UI, the database, or a prompt.

## Testing without a real account

`tests/test_liara_client.py` uses `httpx.MockTransport` and asserts URL, headers, params, retry
counts, error classes, redaction and payload shapes. `tests/test_live_gated.py` holds the opt-in
live tests (`-m live`, requires `LIARAPILOT_RUN_LIVE=1` and a real token).
