"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { chartAlt, chartCaption, chartTitle, layoutChart } from "@/lib/chart";
import { compact, fmtNumber, timeOf, toMs } from "@/lib/format";
import type { KpiSeries } from "@/lib/types";

const HEIGHT = 176;
const MARGINS = { left: 40, right: 16, top: 32, bottom: 36 };
const CHAR_PX = 5.8;

/**
 * One KPI series against its baseline: the measured line, the usual level as a dashed line, and the
 * deviation shaded and labelled where it starts and ends. Not animated: it is data to read.
 */
export function KpiChart({ series, deviationPct }: { series: KpiSeries; deviationPct?: number }) {
  const box = useRef<HTMLDivElement>(null);
  const [width, setWidth] = useState(320);
  const [hover, setHover] = useState<number | null>(null);

  useEffect(() => {
    const el = box.current;
    if (!el) return;
    const observer = new ResizeObserver(([entry]) => setWidth(Math.max(200, Math.round(entry.contentRect.width))));
    observer.observe(el);
    return () => observer.disconnect();
  }, []);

  const layout = useMemo(() => layoutChart(series, width, HEIGHT, MARGINS), [series, width]);
  const { plot, deviation } = layout;
  const n = series.values.length;
  const stepMs = series.step_minutes * 60_000;
  const startMs = toMs(series.start);

  const onsetW = deviation ? deviation.onsetLabel.length * CHAR_PX : 0;
  const recW = deviation ? deviation.recoveryLabel.length * CHAR_PX : 0;
  const stacked =
    !!deviation && deviation.onsetX !== null && deviation.recoveryX !== null &&
    deviation.onsetX + 5 + onsetW > deviation.recoveryX - 5 - recW;

  function indexAt(clientX: number): number {
    const rect = box.current?.getBoundingClientRect();
    if (!rect) return 0;
    const ratio = (clientX - rect.left - plot.x) / plot.w;
    return Math.min(n - 1, Math.max(0, Math.round(ratio * (n - 1))));
  }

  const value = hover !== null ? series.values[hover] : null;
  const base = hover !== null ? series.baseline[hover] : null;
  const hoverX = hover !== null ? plot.x + (hover / (n - 1)) * plot.w : 0;

  return (
    <figure className="m-0 rounded-xl border border-line bg-surface p-3">
      <figcaption className="mb-1.5">
        <div className="flex items-baseline justify-between gap-2">
          <span className="min-w-0 truncate text-sm font-medium">
            <span className="font-mono text-[13px]">{series.entity_id}</span>
            <span className="text-muted"> · {chartTitle(series)}</span>
          </span>
        </div>
        <p className="mt-0.5 text-xs text-muted">{chartCaption(series, deviationPct)}</p>
      </figcaption>
      <div ref={box} className="relative w-full">
        <svg
          role="img"
          aria-label={chartAlt(series, deviationPct)}
          width={width}
          height={HEIGHT}
          viewBox={`0 0 ${width} ${HEIGHT}`}
          className="block max-w-full touch-pan-y"
          onPointerMove={(e) => setHover(indexAt(e.clientX))}
          onPointerLeave={() => setHover(null)}
        >
          {deviation ? (
            <rect
              x={deviation.x1}
              y={plot.y}
              width={Math.max(1, deviation.x2 - deviation.x1)}
              height={plot.h}
              fill="var(--warn)"
              opacity={0.13}
            />
          ) : null}

          {layout.yTicks.map((t) => (
            <text key={t.label + t.y} x={plot.x - 6} y={t.y + 3.5} textAnchor="end" fontSize={10.5} fill="var(--muted)" className="font-mono">
              {t.label}
            </text>
          ))}
          <line x1={plot.x} x2={plot.x + plot.w} y1={plot.y + plot.h} y2={plot.y + plot.h} stroke="var(--line-strong)" />
          {layout.xTicks.map((t) => (
            <g key={t.x}>
              <line x1={t.x} x2={t.x} y1={plot.y + plot.h} y2={plot.y + plot.h + 4} stroke="var(--line-strong)" />
              <text x={t.x} y={plot.y + plot.h + 16} textAnchor="middle" fontSize={10.5} fill="var(--muted)" className="font-mono">
                {t.label}
              </text>
            </g>
          ))}
          <text x={plot.x + plot.w} y={HEIGHT - 3} textAnchor="end" fontSize={10} fill="var(--muted)">
            Time of day, Africa/Tunis
          </text>

          {layout.baselinePath ? (
            <path d={layout.baselinePath} fill="none" stroke="var(--muted)" strokeWidth={1.5} strokeDasharray="4 3" opacity={0.85} />
          ) : null}
          <path d={layout.actualPath} fill="none" stroke="var(--accent)" strokeWidth={2} strokeLinejoin="round" strokeLinecap="round" />

          {deviation?.onsetX != null ? (
            <g>
              <line x1={deviation.onsetX} x2={deviation.onsetX} y1={plot.y - 6} y2={plot.y + plot.h} stroke="var(--warn)" strokeWidth={1.25} strokeDasharray="2 2" />
              <text x={deviation.onsetX + 4} y={plot.y - 12 + 1} fontSize={10.5} fill="var(--warn)" fontWeight={500}>
                {deviation.onsetLabel}
              </text>
            </g>
          ) : deviation ? (
            <text x={plot.x + 4} y={plot.y - 11} fontSize={10.5} fill="var(--warn)" fontWeight={500}>
              {deviation.onsetLabel}
            </text>
          ) : null}
          {deviation?.recoveryX != null ? (
            <g>
              <line x1={deviation.recoveryX} x2={deviation.recoveryX} y1={plot.y - (stacked ? 18 : 6)} y2={plot.y + plot.h} stroke="var(--warn)" strokeWidth={1.25} strokeDasharray="2 2" />
              <text
                x={deviation.recoveryX - 4}
                y={plot.y - (stacked ? 24 : 12) + 1}
                textAnchor="end"
                fontSize={10.5}
                fill="var(--warn)"
                fontWeight={500}
              >
                {deviation.recoveryLabel}
              </text>
            </g>
          ) : null}

          {hover !== null ? (
            <g pointerEvents="none">
              <line x1={hoverX} x2={hoverX} y1={plot.y} y2={plot.y + plot.h} stroke="var(--fg)" opacity={0.35} />
            </g>
          ) : null}
        </svg>
      </div>
      <div className="mt-1 flex min-h-5 flex-wrap items-center justify-between gap-x-4 text-[11px] text-muted" aria-hidden>
        <span className="flex items-center gap-3">
          <span className="flex items-center gap-1.5">
            <svg width="18" height="6"><line x1="0" x2="18" y1="3" y2="3" stroke="var(--accent)" strokeWidth="2" /></svg>
            measured
          </span>
          {series.baseline_available ? (
            <span className="flex items-center gap-1.5">
              <svg width="18" height="6"><line x1="0" x2="18" y1="3" y2="3" stroke="var(--muted)" strokeWidth="1.5" strokeDasharray="4 3" /></svg>
              usual level
            </span>
          ) : null}
        </span>
        <span className="font-mono">
          {hover !== null
            ? `${timeOf(startMs + hover * stepMs)} · ${value === null ? "no data" : `${value >= 1000 ? fmtNumber(value) : compact(value)}`}${base !== null && base !== undefined ? ` (usual ${base >= 1000 ? fmtNumber(base) : compact(base)})` : ""}`
            : ""}
        </span>
      </div>
    </figure>
  );
}
