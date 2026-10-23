import * as React from "react";
import type { MetricSeries } from "@/lib/types";
import { fa, faNumber, faPercent } from "@/lib/format";
import { cn } from "@/lib/cn";

function niceTop(max: number): number {
  const safe = Math.max(max, 1);
  const step = 10 ** Math.floor(Math.log10(safe));
  const nice = [1, 2, 2.5, 5, 10].map((m) => m * step).find((s) => safe / s <= 4) ?? step;
  return Math.ceil(safe / nice) * nice;
}

function tickLabel(value: number, unit: string): string {
  if (unit === "%") return fa(Math.round(value));
  return faNumber(value, 0);
}

/**
 * Pure-SVG line chart. In RTL the newest point is on the left (the natural end
 * of the reading direction) and the value axis stays on the right edge.
 */
export function MetricChart({
  series,
  title,
  className,
}: {
  series: MetricSeries;
  title: string;
  className?: string;
}) {
  const [hover, setHover] = React.useState<number | null>(null);
  const points = series.points.slice(-90);
  const W = 600;
  const H = 168;
  const padR = 42;
  const padL = 6;
  const padT = 12;
  const padB = 24;
  const unit = series.unit || "%";

  if (!series.available || points.length === 0) {
    return (
      <div
        className={cn(
          "flex min-h-[168px] flex-col items-center justify-center gap-1 rounded-field border border-dashed border-border px-4 py-6 text-center",
          className,
        )}
      >
        <span className="text-sm font-medium text-muted-foreground">ناموجود</span>
        <span className="max-w-[34ch] text-[11px] leading-5 text-muted-foreground/70">
          {series.unavailable_reason || "برای این بازه داده‌ای از لیارا برنگشت؛ عدد صفر جای آن نمایش داده نمی‌شود."}
        </span>
      </div>
    );
  }

  const top = niceTop(Math.max(...points.map((p) => p.v), 1));
  const ticks = [0, 0.25, 0.5, 0.75, 1].map((ratio) => ratio * top);
  const plotW = W - padL - padR;
  const plotH = H - padT - padB;
  const slot = plotW / Math.max(1, points.length - 1);
  const x = (index: number) => W - padR - index * slot;
  const y = (value: number) => padT + plotH - (value / top) * plotH;

  const coords = points.map((point, index) => [x(index), y(point.v)] as const);
  const path = coords
    .map(([px, py], index) => {
      if (index === 0) return `M ${px} ${py}`;
      const [qx, qy] = coords[index - 1];
      const cx = (qx + px) / 2;
      return `C ${cx} ${qy}, ${cx} ${py}, ${px} ${py}`;
    })
    .join(" ");
  const area = `${path} L ${x(0)} ${padT + plotH} L ${x(points.length - 1)} ${padT + plotH} Z`;
  const gradientId = React.useId();
  const active = hover === null ? null : points[hover];

  const timeLabel = (timestamp: number) => {
    try {
      return new Intl.DateTimeFormat("fa-IR", {
        hour: "2-digit",
        minute: "2-digit",
      }).format(new Date(timestamp * 1000));
    } catch {
      return "—";
    }
  };

  return (
    <figure className={cn("min-w-0", className)}>
      <figcaption className="mb-1 flex flex-wrap items-baseline justify-between gap-2">
        <span className="text-[13px] font-medium">{title}</span>
        <span className="text-[11px] text-muted-foreground">
          {active
            ? `${faPercent(active.v)} — ${timeLabel(active.t)}`
            : `آخرین ${faPercent(series.last)} · بیشینه ${faPercent(series.maximum)}`}
        </span>
      </figcaption>
      <svg
        viewBox={`0 0 ${W} ${H}`}
        className="w-full"
        role="img"
        aria-label={`${title}: آخرین ${faPercent(series.last)}، میانگین ${faPercent(series.average)}، بیشینه ${faPercent(series.maximum)}`}
      >
        <defs>
          <linearGradient id={gradientId} x1="0" y1="0" x2="0" y2="1">
            <stop offset="0" stopColor="var(--brand)" stopOpacity="0.32" />
            <stop offset="1" stopColor="var(--brand)" stopOpacity="0" />
          </linearGradient>
        </defs>
        {ticks.map((tick) => (
          <g key={tick}>
            <line
              x1={padL}
              x2={W - padR}
              y1={y(tick)}
              y2={y(tick)}
              stroke="var(--border)"
              strokeDasharray={tick === 0 ? undefined : "2 4"}
            />
            <text
              x={W - padR + 6}
              y={y(tick) + 3}
              fontSize="10"
              fill="var(--muted-foreground)"
              textAnchor="start"
            >
              {tickLabel(tick, unit)}
            </text>
          </g>
        ))}
        <path d={area} fill={`url(#${gradientId})`} />
        <path d={path} fill="none" stroke="var(--brand)" strokeWidth="1.8" strokeLinecap="round" />
        <circle cx={x(0)} cy={y(points[0].v)} r="3" fill="var(--brand)" stroke="var(--background)" strokeWidth="2" />
        {coords.map(([px, py], index) => (
          <g key={index}>
            <rect
              x={px - slot / 2}
              y={padT}
              width={Math.max(slot, 2)}
              height={plotH}
              fill="transparent"
              onMouseEnter={() => setHover(index)}
              onMouseLeave={() => setHover(null)}
            />
            {hover === index && (
              <g pointerEvents="none">
                <line x1={px} x2={px} y1={padT} y2={padT + plotH} stroke="var(--foreground)" strokeOpacity="0.18" />
                <circle cx={px} cy={py} r="4" fill="var(--background)" stroke="var(--brand)" strokeWidth="2" />
              </g>
            )}
          </g>
        ))}
        <text x={x(0)} y={H - 6} fontSize="10" fill="var(--muted-foreground)" textAnchor="start">
          {timeLabel(points[0].t)}
        </text>
        <text
          x={x(points.length - 1)}
          y={H - 6}
          fontSize="10"
          fill="var(--muted-foreground)"
          textAnchor="end"
        >
          {timeLabel(points[points.length - 1].t)}
        </text>
      </svg>
    </figure>
  );
}
