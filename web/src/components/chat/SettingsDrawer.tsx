import { ExternalLink, RefreshCw } from "lucide-react";
import type { SettingsStatus } from "@/lib/types";
import { Drawer } from "@/components/ui/Drawer";
import { Button } from "@/components/ui/Button";
import { Badge, DemoBadge } from "@/components/ui/Badge";
import { Notice, Section } from "@/components/blocks/primitives";
import { fa } from "@/lib/format";

const LINKS = [
  { href: "/dashboard", label: "نمای کلی (پنل قدیمی)" },
  { href: "/settings", label: "تنظیمات کامل اتصال" },
  { href: "/mcp", label: "اتصال MCP" },
  { href: "/docs", label: "مستندات API" },
];

function Capability({
  label,
  ok,
  detail,
}: {
  label: string;
  ok: boolean;
  detail: string;
}) {
  return (
    <div className="flex items-start justify-between gap-3 border-b border-border/60 py-2 last:border-0">
      <div className="min-w-0">
        <p className="text-[12.5px] font-medium">{label}</p>
        <p className="text-[10.5px] leading-5 text-muted-foreground">{detail}</p>
      </div>
      <Badge variant={ok ? "success" : "warning"} dot className="shrink-0">
        {ok ? "فعال" : "غیرفعال"}
      </Badge>
    </div>
  );
}

export function SettingsDrawer({
  open,
  status,
  loading,
  error,
  onClose,
  onRetry,
}: {
  open: boolean;
  status: SettingsStatus | null;
  loading: boolean;
  error: string | null;
  onClose: () => void;
  onRetry: () => void;
}) {
  return (
    <Drawer
      open={open}
      title="تنظیمات اتصال"
      description="وضعیت بدون نمایش راز؛ توکن لیارا هرگز به مرورگر فرستاده نمی‌شود."
      onClose={onClose}
      footer={
        <Button variant="outline" className="w-full" onClick={onRetry} disabled={loading}>
          <RefreshCw className={loading ? "animate-spin" : undefined} />
          به‌روزرسانی وضعیت
        </Button>
      }
    >
      {loading && !status && (
        <div className="space-y-2" aria-hidden>
          {[0, 1, 2, 3].map((index) => (
            <div key={index} className="h-12 animate-pulse rounded-surface bg-card" />
          ))}
        </div>
      )}

      {error && (
        <Notice tone="danger">
          {error}
          <button type="button" onClick={onRetry} className="ms-2 underline underline-offset-4">
            تلاش دوباره
          </button>
        </Notice>
      )}

      {status && (
        <div className="space-y-5">
          <div className="flex flex-wrap items-center gap-2">
            <DemoBadge live={!status.demo_mode} />
            <Badge variant="secondary">{status.app_env}</Badge>
            {status.auth_enabled && <Badge variant="brand">احراز هویت فعال</Badge>}
          </div>

          {status.readiness.blockers.length > 0 && (
            <Notice tone="warning">
              <span className="font-medium">موانع اجرای Live:</span>
              <ul className="mt-1 list-inside list-disc space-y-0.5">
                {status.readiness.blockers.map((item) => (
                  <li key={item}>{item}</li>
                ))}
              </ul>
            </Notice>
          )}

          <section className="space-y-1">
            <h3 className="mb-1 text-[11px] font-medium text-muted-foreground">قابلیت‌ها</h3>
            <Capability
              label="اتصال لیارا"
              ok={!status.demo_mode && status.liara.token_configured}
              detail={
                status.demo_mode
                  ? "حالت DEMO: داده‌ها شبیه‌سازی می‌شوند."
                  : status.liara.token_configured
                    ? `توکن تنظیم شده — ${status.liara.base_url}`
                    : "توکن تنظیم نشده است."
              }
            />
            <Capability
              label="مدل زبانی (اختیاری)"
              ok={status.llm.configured}
              detail={
                status.llm.configured
                  ? `${status.llm.provider} · ${status.llm.model ?? ""}`
                  : "غیرفعال — تشخیص با موتور قواعد قطعی کار می‌کند."
              }
            />
            <Capability
              label="ایجنت کدنویسی"
              ok={status.coding_agent.provider !== "none"}
              detail={
                status.coding_agent.provider === "none"
                  ? "تحویل دستی؛ اصلاح خودکار اجرا نمی‌شود."
                  : `${status.coding_agent.provider} · اجرای خودکار: ${status.coding_agent.auto_execute ? "بله" : "خیر"}`
              }
            />
            <Capability
              label="Health Check"
              ok={status.verification.healthcheck_url_configured}
              detail={
                status.verification.healthcheck_url_configured
                  ? `انتظار کد ${fa(status.verification.expect_status)}`
                  : "URL تنظیم نشده؛ نتیجه انتشار «تأییدنشده» خواهد بود."
              }
            />
            <Capability
              label="Push به Git"
              ok={status.coding_agent.git_push}
              detail="پیش‌فرض غیرفعال؛ تغییرات در Workspace محلی می‌ماند."
            />
          </section>

          <Section title="سقف تلاش اصلاح">
            <span>{fa(status.coding_agent.max_repair_attempts)} تلاش در هر گردش‌کار.</span>
          </Section>

          <section className="space-y-1.5">
            <h3 className="text-[11px] font-medium text-muted-foreground">صفحه‌های مدیریتی</h3>
            <ul className="space-y-1">
              {LINKS.map((link) => (
                <li key={link.href}>
                  <a
                    href={link.href}
                    className="flex items-center justify-between gap-2 rounded-field border border-border bg-card px-3 py-2 text-[12px] transition-colors hover:border-brand/30 hover:text-brand"
                  >
                    {link.label}
                    <ExternalLink className="size-3.5" />
                  </a>
                </li>
              ))}
            </ul>
          </section>

          <p className="text-[10.5px] leading-5 text-muted-foreground">
            پیکربندی حساس فقط از طریق فایل <span className="code-block" dir="ltr">.env</span> و
            سرویس‌های Backend مدیریت می‌شود. این پنل هیچ مقدار رازی را نمی‌خواند یا نمایش
            نمی‌دهد.
          </p>
        </div>
      )}
    </Drawer>
  );
}
