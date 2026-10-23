const FA_DIGITS = ["۰", "۱", "۲", "۳", "۴", "۵", "۶", "۷", "۸", "۹"];

/** Convert every Latin digit in a display string to Persian digits. */
export function fa(value: string | number): string {
  return String(value).replace(/\d/g, (digit) => FA_DIGITS[Number(digit)]);
}

export function faNumber(value: number | null | undefined, digits = 1): string {
  if (value === null || value === undefined || Number.isNaN(value)) return "—";
  const rounded = Math.round(value * 10 ** digits) / 10 ** digits;
  const [whole, fraction] = String(rounded).split(".");
  const grouped = whole.replace(/\B(?=(\d{3})+(?!\d))/g, "٬");
  return fa(fraction ? `${grouped}٫${fraction}` : grouped);
}

export function faPercent(value: number | null | undefined): string {
  return value === null || value === undefined ? "—" : `${faNumber(value)}٪`;
}

export function faDateTime(iso: string | null | undefined): string {
  if (!iso) return "—";
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return fa(iso);
  try {
    return new Intl.DateTimeFormat("fa-IR", {
      dateStyle: "short",
      timeStyle: "short",
    }).format(date);
  } catch {
    return fa(iso);
  }
}

export function faTimeAgo(iso: string | null | undefined): string {
  if (!iso) return "—";
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return "—";
  const seconds = Math.round((Date.now() - date.getTime()) / 1000);
  if (seconds < 60) return "همین حالا";
  const minutes = Math.round(seconds / 60);
  if (minutes < 60) return `${fa(minutes)} دقیقه پیش`;
  const hours = Math.round(minutes / 60);
  if (hours < 24) return `${fa(hours)} ساعت پیش`;
  const days = Math.round(hours / 24);
  return `${fa(days)} روز پیش`;
}

export function faDuration(ms: number | null | undefined): string {
  if (ms === null || ms === undefined) return "—";
  if (ms < 1000) return `${fa(Math.max(0, Math.round(ms)))} میلی‌ثانیه`;
  const seconds = ms / 1000;
  if (seconds < 60) return `${faNumber(seconds, 1)} ثانیه`;
  return `${faNumber(seconds / 60, 1)} دقیقه`;
}

export function faMinutes(minutes: number): string {
  if (minutes < 60) return `${fa(minutes)} دقیقه`;
  if (minutes % 60 === 0) return `${fa(minutes / 60)} ساعت`;
  return `${fa(Math.floor(minutes / 60))} ساعت و ${fa(minutes % 60)} دقیقه`;
}

/** Technical identifiers stay Latin but display inside an LTR island. */
export function shortId(value: string | null | undefined, length = 14): string {
  if (!value) return "—";
  return value.length <= length ? value : `…${value.slice(-length)}`;
}

const STATUS_FA: Record<string, string> = {
  queued: "در صف",
  running: "در حال اجرا",
  waiting_for_approval: "منتظر تأیید",
  testing: "در حال تست",
  deploying: "در حال انتشار",
  verifying: "در حال بررسی سلامت",
  completed: "کامل‌شده",
  failed: "ناموفق",
  cancelled: "لغوشده",
  needs_human: "نیازمند انسان",
  pending: "در انتظار",
  approved: "تأییدشده",
  rejected: "ردشده",
  expired: "منقضی",
  passed: "موفق",
  skipped: "اجرا نشد",
  success: "موفق",
  prepared: "آماده",
  ready: "آماده",
  released: "منتشرشده",
  unverified: "تأییدنشده",
  verified: "تأییدشده",
  no_incident: "بدون حادثه",
};

export function statusFa(status: string | null | undefined): string {
  if (!status) return "نامشخص";
  return STATUS_FA[status] ?? fa(status);
}

const CONFIDENCE_FA: Record<string, string> = {
  low: "کم",
  medium: "متوسط",
  high: "زیاد",
};

export function confidenceFa(value: string | null | undefined): string {
  return value ? CONFIDENCE_FA[value] ?? fa(value) : "نامشخص";
}

const RISK_FA: Record<string, string> = {
  low: "کم",
  medium: "متوسط",
  high: "زیاد",
};

export function riskFa(value: string | null | undefined): string {
  return value ? RISK_FA[value] ?? fa(value) : "نامشخص";
}

const CAUSE_FA: Record<string, string> = {
  missing_dependency: "وابستگی ناقص",
  memory_exhaustion: "اتمام حافظه",
  connection_failure: "اختلال اتصال",
  missing_config: "پیکربندی ناقص",
  port_conflict: "تعارض پورت",
  permission_error: "خطای دسترسی",
  timeout: "Timeout",
  no_incident: "بدون حادثه",
  unknown: "نامشخص",
};

export function causeFa(value: string | null | undefined): string {
  return value ? CAUSE_FA[value] ?? value : "نامشخص";
}
