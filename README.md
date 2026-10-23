# LiaraPilot — AI Infrastructure Engineer for Liara

> یک دستیار مهندسی زیرساخت که لاگ‌ها و متریک‌های واقعی/شبیه‌سازی‌شده لیارا را بررسی می‌کند،
> علت خطا را **با شواهد** توضیح می‌دهد، در مراحل حساس **منتظر تأیید انسان** می‌ماند و بعد از
> انتشار، سلامت سرویس را **راستی‌آزمایی** می‌کند.

[English technical overview](#english-technical-overview) · [مستندات](docs/) · [سناریوی دمو](docs/demo-script.md)

---

## ۱. این محصول چه می‌کند؟

پرسش‌هایی مثل «چرا سایتم ۵۰۰ می‌دهد؟»، «مشکل از CPU است یا RAM؟» یا «این باگ را درست کن و
منتشر کن» به یک گردش‌کار مشخص تبدیل می‌شوند:

```
دریافت درخواست → تشخیص پروژه → جمع‌آوری شواهد (لاگ، CPU، RAM، انتشارها)
   → نرمال‌سازی و پاک‌سازی شواهد → تحلیل علت (قاعده‌محور، اختیاری + LLM)
   → تعیین ریسک → برنامه اصلاح → ⏸ تأیید انسان
   → Workspace ایزوله + شاخه ai-fix/<id> → ایجنت کدنویسی → اجرای تست → بررسی Diff
   → بسته‌بندی و ارسال سورس → ⏸ تأیید انتشار → ساخت Release
   → Health Check → گزارش نهایی
```

وضعیت گردش‌کار در LangGraph با Checkpointer پایدار SQLite ذخیره می‌شود؛ اگر سرور ری‌استارت شود،
گردش‌کارِ منتظرِ تأیید از همان نقطه ادامه پیدا می‌کند.

**نکته کلیدی:** هیچ قابلیتی «فقط چون مدل گفته» کامل تلقی نمی‌شود. هر نتیجه از اجرای واقعی کد
(تست، Diff، پاسخ API، Health Check) می‌آید و در حالت دمو همه‌چیز با برچسب `SIMULATED` مشخص می‌شود.

## ۲. قابلیت‌ها

| قابلیت | وضعیت |
|---|---|
| Demo Mode کامل بدون توکن، بدون LLM، بدون اینترنت | ✅ پیاده‌سازی و تست‌شده |
| سناریوی خطای ۵۰۰ (وابستگی ناقص) از تشخیص تا Health Check | ✅ اجرا و تست‌شده |
| دو سناریوی دیگر (کمبود حافظه، سایت سالم) | ✅ |
| تحلیل شواهد با ساختار ۸ بخشی (مشاهده، شواهد، علت، جایگزین‌ها، اطمینان، اقدام، ریسک، راستی‌آزمایی) | ✅ |
| تفکیک صریح «منابع علت نیستند» بر پایه متریک‌ها | ✅ |
| خنثی‌سازی Prompt Injection موجود در لاگ‌ها | ✅ |
| Human-in-the-Loop با interrupt پایدار + TTL + اثر انگشت پارامترها + مصرف یک‌باره | ✅ |
| LangGraph Checkpointer پایدار و بازیابی پس از Restart | ✅ تست‌شده |
| MCP Server روی stdio با ۱۳ ابزار و کنترل مجوز سروری | ✅ تست‌شده |
| کلاینت Liara با Retry محدود، ماسک راز و Audit | ✅ تست‌شده (بدون شبکه) |
| اتصال واقعی به Liara (Live) | ✅ کد کامل؛ نیازمند توکن واقعی (تست Live جدا) |
| Adapterهای Claude Code / Codex / Mock / Manual Handoff | ✅ کد کامل؛ CLI در این محیط نصب نبود |
| بسته‌بندی امن سورس (بدون `.env`، `.git`، `node_modules`، symlink escape) | ✅ تست‌شده |
| رابط مکالمه‌ای فارسی (React + Vite) با Generative UI مبتنی بر Registry | ✅ تست‌شده |
| رابط فارسی RTL، واکنش‌گرا، بدون CDN و فونت خارجی | ✅ |
| Audit Log (SQLite + JSONL) با ماسک راز | ✅ |

### ۲.۱ رابط مکالمه‌ای (صفحه اصلی)

- **همه‌چیز در یک گفت‌وگو**: صفحه `/` یک چت کامل است — پروژه، تشخیص، منابع، لاگ، برنامه اصلاح،
  Diff، تأییدها، انتشار و گزارش نهایی همه به‌صورت پیام و کارت در همان Thread نمایش داده می‌شوند.
- **Generative UI محدود به Registry**: بک‌اند فهرست `ui_blocks` را با Schema معتبر برمی‌گرداند؛
  فرانت‌اند فقط نام‌های ثبت‌شده در `web/src/components/blocks/registry.tsx` را رندر می‌کند.
  نام ناشناخته، props نامعتبر یا HTML تولیدشده توسط مدل نه اجرا می‌شود و نه صفحه را از کار می‌اندازد.
- **کارت‌های تعاملی**: Project Picker به Context گفت‌وگو وصل است، Approval Card فقط با درخواست
  معتبر سرور عملیات را اجرا می‌کند، Workflow Timeline از رویدادهای ذخیره‌شده ساخته می‌شود و
  Metrics/Log/Diff/Health از داده واقعی یا Fixture مشخص می‌آیند.
- **بازیابی وضعیت**: پیام‌ها، UI Blocks، پروژه فعال و شناسه گردش‌کار در SQLite ذخیره می‌شوند؛
  پس از Refresh یا Restart، گفت‌وگو و کارت تأیید در انتظار دوباره از سرور خوانده می‌شوند.
- **بدون وابستگی خارجی**: Tailwind v4 و فونت **Vazirmatn** (SIL OFL) به‌صورت self-hosted در
  `app/static/chat/fonts/`؛ هیچ CDN، فونت یا اسکریپت خارجی در زمان اجرا لازم نیست.
- **تم**: زبان طراحی Graphite (طبق قواعد VibeFarsi) با رنگ تأکیدی برند لیارا؛ توکن‌ها در
  `web/src/index.css` تعریف شده‌اند. اعداد کارت‌ها با ارقام فارسی و شناسه‌های فنی با `dir="ltr"`
  نمایش داده می‌شوند.
- **دسترس‌پذیری**: skip-link، focus visible، `aria-live` برای پیام‌ها و وضعیت، برچسب‌های ARIA برای
  ورودی‌ها و دکمه‌ها و احترام به `prefers-reduced-motion`.
- **شفافیت دمو**: نشان `DEMO / SIMULATED` در هدر، Composer و روی کارت‌های داده‌محور تکرار می‌شود.
- **پنل قدیمی**: مسیر `/dashboard` برای مقایسه و سازگاری باقی مانده است، اما مسیر اصلی محصول چت است.

## ۳. پیش‌نیازها

- **Python 3.11+** (توسعه و تست روی 3.11 انجام شده؛ پروژه برای **3.12** هدف‌گذاری شده و روی آن هم اجرا می‌شود)
- **Node.js 20+ و npm** — فقط برای توسعه یا Build مجدد رابط React لازم است؛ نسخه Build‌شده در مخزن سرو می‌شود
- **uv** (اختیاری، پیشنهادی) — اگر نصب نباشد اسکریپت به `pip` برمی‌گردد
- **git** (برای ساخت شاخه اصلاح؛ در حالت دمو اختیاری است)
- Docker لازم **نیست**. توکن لیارا و LLM برای دمو لازم **نیست**.

## ۴. اجرای سریع (Windows 11)

```powershell
git clone <repo-url> liarapilot
cd liarapilot

# اجرا با یک فرمان: ساخت .env، نصب وابستگی‌ها، اعتبارسنجی، تست، اجرای سرور
powershell -ExecutionPolicy Bypass -File .\scripts\run.ps1
```

سپس <http://127.0.0.1:8000/> را باز کنید.

اگر PowerShell اجرای اسکریپت را مسدود کرد:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
```

### اجرای دستی در PowerShell

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev]"

python scripts/setup_env.py            # .env را از .env.example می‌سازد (بدون بازنویسی فایل موجود)
python scripts/validate_config.py      # اعتبارسنجی تنظیمات، بدون افشای راز
python -m pytest -q                    # تست‌های آفلاین بک‌اند
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

### توسعه یا Build رابط مکالمه‌ای

خروجی Build در `app/static/chat/` قرار می‌گیرد و FastAPI همان را روی `/` سرو می‌کند.
برای کار روی UI، در یک ترمینال FastAPI را روی پورت 8000 اجرا کنید و در ترمینال دیگر:

```bash
cd web
npm install
npm run dev        # http://127.0.0.1:5173 با proxy به /api روی 8000
npm test           # Vitest (Registry، تأییدیه، حالت‌های خطا و DEMO/LIVE)
npm run build      # ساخت مجدد app/static/chat/index.html و assets
```

پس از هر تغییر UI، `npm run build` را اجرا کنید تا نسخه‌ای که FastAPI سرو می‌کند به‌روز شود.

### لینوکس / مک‌اواس

```bash
bash scripts/run.sh                    # یا: bash scripts/run.sh --skip-tests
```

معادل دستی:

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
python scripts/setup_env.py && python scripts/validate_config.py
python -m uvicorn app.main:app --port 8000
```

### با uv

```bash
uv sync --extra dev
uv run python scripts/setup_env.py
uv run uvicorn app.main:app --port 8000
```

## ۵. تنظیم `.env`

فایل `.env.example` مرجع کامل و قابل انتشار است. اسکریپت `scripts/setup_env.py` آن را به `.env`
کپی می‌کند و **فایل موجود را هرگز بازنویسی نمی‌کند**.

ترکیب پیش‌فرض دمو (باید بدون هیچ تغییری کار کند):

```dotenv
DEMO_MODE=true
LLM_PROVIDER=disabled
CODING_AGENT_PROVIDER=none
LIARA_API_TOKEN=
```

مهم‌ترین کلیدها:

| کلید | معنا |
|---|---|
| `DEMO_MODE` | `true` = همه فراخوانی‌های لیارا شبیه‌سازی می‌شوند. |
| `LIARA_API_TOKEN` | توکن لیارا (فقط برای Live). هرگز به UI، لاگ یا مدل فرستاده نمی‌شود. |
| `LIARA_AUTH_SCHEME` | `token` (مطابق نمونه‌های مستندات) یا `Bearer`. |
| `LIARA_ALLOW_WRITES` | اجازه ارسال سورس در Live. پیش‌فرض `false`. |
| `LIARA_ENABLE_DEPLOY` | اجازه ساخت Release در Live. پیش‌فرض `false`. |
| `LIARA_DEPLOY_ALLOWED_PROJECTS` | allowlist پروژه‌ها؛ **خالی = همه عملیات تغییردهنده ممنوع**. |
| `LIARA_DEFAULT_PORT` | فقط وقتی هیچ Release قبلی پورتی برنگرداند. |
| `CODING_AGENT_PROVIDER` | `none` / `claude_code` / `codex`. |
| `CODING_AGENT_AUTO_EXECUTE` | اجرای واقعی CLI؛ پیش‌فرض `false` (تحویل دستی). |
| `CODING_AGENT_REPO_PATH` | کلون محلی مخزن برای تعمیر واقعی. |
| `DEPLOY_HEALTHCHECK_URL` | اگر خالی باشد نتیجه انتشار «تأییدنشده» ثبت می‌شود. |
| `APP_AUTH_ENABLED` + `APP_ACCESS_TOKEN` | الزامی برای Bind روی Host غیرمحلی. |

> ⚠️ اگر `APP_HOST` را از `127.0.0.1` تغییر دهید و `APP_AUTH_ENABLED=false` باشد، برنامه
> **بالا نمی‌آید** (fail-fast امنیتی).

## ۶. اتصال به API واقعی لیارا (Live Mode)

1. توکن API را از کنسول لیارا بسازید.
2. در `.env`:

   ```dotenv
   DEMO_MODE=false
   LIARA_API_TOKEN=<your-token>
   LIARA_AUTH_SCHEME=token        # اگر حساب شما Bearer می‌خواهد: Bearer
   LIARA_ALLOW_WRITES=false        # تا آماده نیستید false بماند
   LIARA_ENABLE_DEPLOY=false
   LIARA_DEPLOY_ALLOWED_PROJECTS=my-app
   DEPLOY_HEALTHCHECK_URL=https://my-app.liara.run/healthz
   ```

3. سرور را ری‌استارت کنید و در صفحه **تنظیمات** روی «اجرای تست اتصال» بزنید
   (یا `POST /api/settings/test-liara-connection`).
4. صفحه **تنظیمات → پیش‌نیازهای Live** دقیقاً نشان می‌دهد چه چیزی مانع اجرای واقعی است.
5. برای نوشتن، آگاهانه `LIARA_ALLOW_WRITES=true` و سپس `LIARA_ENABLE_DEPLOY=true` را فعال کنید.
   هر دو تنها پیش‌شرط‌اند؛ **تأیید انسانی در هر اجرا همچنان الزامی است**.

تست‌های Live جداگانه‌اند و به‌صورت پیش‌فرض اجرا نمی‌شوند:

```bash
LIARAPILOT_RUN_LIVE=1 LIARA_API_TOKEN=... DEMO_MODE=false pytest -m live
```

## ۷. اتصال MCP به Claude Code و Codex

سرور MCP روی **stdio** اجرا می‌شود (stdout مخصوص پروتکل است؛ همه لاگ‌ها روی stderr می‌روند):

```bash
python -m app.mcp.server            # اجرای سرور
python -m app.mcp.server --selftest  # تست سریع درون‌فرآیندی (JSON روی stdout)
```

Claude Code:

```bash
claude mcp add liarapilot -- python -m app.mcp.server
claude mcp list
```

Codex (`~/.codex/config.toml`):

```toml
[mcp_servers.liarapilot]
command = "python"
args = ["-m", "app.mcp.server"]
env = { DEMO_MODE = "true" }
```

فایل آماده `.mcp.json` در ریشه پروژه هم قرار دارد. جزئیات کامل: [docs/mcp.md](docs/mcp.md).

## ۸. اجرای سناریوی دمو

1. `http://127.0.0.1:8000/` را باز کنید.
2. روی **اجرای سناریوی دمو** بزنید (سناریوی پیش‌فرض: خطای ۵۰۰ جنگو).
3. صفحات بعدی را دنبال کنید: شواهد → تحلیل → **تأیید اصلاح** → تست و Diff → **تأیید انتشار** →
   Health Check → گزارش نهایی.

سناریوی کامل پنج‌دقیقه‌ای برای ارائه: [docs/demo-script.md](docs/demo-script.md).

## ۹. تست‌ها

```bash
python -m pytest -q            # همه تست‌های آفلاین
python -m pytest -q -m live    # تست‌های Live (نیازمند توکن واقعی)
ruff check .                   # لینت
```

پوشش تست‌ها: کلاینت لیارا (خطاها، Retry، Rate Limit، ماسک راز، قرارداد پاسخ)، آداپتور Mock/Live،
تحلیل مبتنی بر شواهد، امنیت (allowlist، انقضای تأیید، مصرف یک‌باره، اثر انگشت پارامتر، Workspace
escape، بسته‌بندی بدون `.env`/`.git`)، MCP (ثبت ابزار، Schema، اجرای ابزار خواندنی، مسدود بودن
انتشار بدون تأیید، پاک بودن stdout)، و E2E کامل شامل ردی و بازیابی پس از Restart.

## ۱۰. ساختار پروژه

```text
app/
├── main.py               # FastAPI app + middleware + error mapping
├── core/                 # config، logging با ماسک راز، security، errors، utils
├── api/routes/           # conversations(چت)، dashboard(قدیمی)، projects، diagnosis، workflows، approvals، settings، demo، health
├── liara/                # client، schemas، adapter، mock_adapter، source_packager، errors
├── agent/                # graph، nodes، state، prompts، checkpointer، llm(اختیاری)
├── mcp/                  # server(stdio) و tool_registry
├── coding_agents/        # base، claude_code، codex، mock_agent، manual
├── services/             # conversation، ui_blocks، audit، approval، diagnosis، coding_agent، deployment، verification، workflow، demo، container
├── db/                   # models، repository، conversation_store، database
├── templates/ static/    # پنل قدیمی + خروجی Build چت در static/chat
└── demo_fixtures/        # مخزن نمونه برای دمو (خطای واقعی وابستگی ناقص)
web/                      # React + Vite + TypeScript + Tailwind v4 (منبع رابط چت)
scripts/                  # run.ps1، run.sh، setup_env.py، validate_config.py
tests/                    # تست‌های آفلاین بک‌اند (Unit/API/E2E/MCP)
docs/                     # architecture، liara-api، mcp، security، demo-script، limitations
```

## ۱۱. محدودیت‌های شناخته‌شده

فهرست کامل و به‌روز: [docs/limitations.md](docs/limitations.md). خلاصه:

- قالب دقیق پارامتر `since` در endpoint لاگ در مستندات مشخص نشده؛ کد ابتدا ISO-8601 و سپس epoch
  را امتحان می‌کند. این رفتار در [docs/liara-api.md](docs/liara-api.md) ثبت شده است.
- Health Check لیارا endpoint مستند و عمومی ندارد؛ بدون `DEPLOY_HEALTHCHECK_URL` نتیجه
  «تأییدنشده» است، نه موفق.
- Rollback خودکار پیاده‌سازی نشده (در مستندات جاری پشتیبانی مستند ندارد)؛ به‌جای آن مسیر
  بازیابی پیشنهاد می‌شود.
- اجرای واقعی Claude Code / Codex در این محیط آزمایش نشد (CLI نصب نبود)؛ آداپتورها، پرچم‌ها و
  مسیرهای خطا پیاده‌سازی شده‌اند و Mock/manual راستی‌آزمایی شده‌اند.
- Streamable HTTP برای MCP پیاده‌سازی نشده است (خارج از دامنه MVP)؛ فقط stdio.

---

## English technical overview

**LiaraPilot** is an evidence-driven infrastructure assistant for apps hosted on
[Liara](https://liara.ir). It turns a natural-language incident request into a
deterministic LangGraph workflow:

`intake → resolve project → collect evidence → normalize → diagnose → classify risk →
repair plan → **interrupt: repair approval** → workspace → coding agent → tests →
diff review → package & upload source → **interrupt: deploy approval** → create release →
verify → evaluate → finish`

Key properties:

- **Two adapters, one contract.** `MockLiaraAdapter` (demo) and `LiveLiaraAdapter`
  implement the same interface; every record carries `simulated: true|false`.
- **No false success.** A deployment is only `verified` when a configured health-check URL
  returns the expected status; otherwise it is `unverified`. Tests must pass before deploy.
- **Server-side approvals.** Approvals are database rows bound to
  `(workflow, stage, attempt)` plus a SHA-256 fingerprint of the action parameters, with a TTL
  and single-use consumption. A client (or an LLM) cannot authorise an action with a boolean.
- **Deterministic diagnosis.** A rule engine (dependency, OOM, connection, config, port,
  permissions, timeout) always produces the baseline report with evidence IDs; an optional
  OpenAI-compatible LLM may only rewrite the prose and cannot invent evidence.
- **Untrusted logs.** Log lines are sanitised: ANSI/control characters removed, secrets masked,
  instruction-like content (`ignore previous instructions…`) neutralised and counted.
- **Secrets never leak.** The Liara token is never logged, never sent to the UI, never passed to
  a coding-agent subprocess (the environment is filtered), and never included in prompts.
- **Offline first.** The MVP runs with `DEMO_MODE=true`, no token, no LLM, no Docker.

Documentation: [architecture](docs/architecture.md) ·
[Liara API integration](docs/liara-api.md) · [MCP](docs/mcp.md) ·
[security](docs/security.md) · [demo script](docs/demo-script.md) ·
[limitations](docs/limitations.md)

## License

MIT
