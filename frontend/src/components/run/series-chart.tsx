"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { chartAlt, chartCaption, layoutChart } from "@/lib/chart";
import type { KpiSeries } from "@/lib/types";

const HEIGHT = 208;
const MARGINS = { left: 40, right: 14, top: 38, bottom: 34 };
const CHAR_PX = 6;

/**
 * One KPI series on its own: the measured line, the usual level dashed, the stretch where they
 * disagree shaded, and the onset and the recovery marked with their times.
 */
export function SeriesChart({ series, deviationPct }: { series: KpiSeries; deviationPct?: number }) {
  const box = useRef<HTMLDivElement | null>(null);
  const [width, setWidth] = useState(320);

  useEffect(() => {
    const el = box.current;
    if (!el) return;
    const measure = () => setWidth(Math.max(220, Math.round(el.getBoundingClientRect().width)));
    measure();
    const observer = new ResizeObserver(measure);
    observer.observe(el);
    return () => observer.disconnect();
  }, []);

  const layout = useMemo(() => layoutChart(series, width, HEIGHT, MARGINS), [series, width]);
  const { plot, deviation } = layout;

  const onsetW = deviation ? deviation.onsetLabel.length * CHAR_PX : 0;
  const recoveryW = deviation ? deviation.recoveryLabel.length * CHAR_PX : 0;
  const stacked =
    !!deviation && deviation.onsetX !== null && deviation.recoveryX !== null && deviation.onsetX + 5 + onsetW > deviation.recoveryX - 5 - recoveryW;
  // A label that would leave the chart on the right is drawn to the left of its line instead.
  const onsetLeft = !!deviation && deviation.onsetX !== null && deviation.onsetX + 5 + onsetW > width - 4;

  return (
    <figure className="sc">
      <figcaption>{chartCaption(series, deviationPct)}</figcaption>
      <div ref={box} className="sc-box">
        <svg role="img" aria-label={chartAlt(series, deviationPct)} width={width} height={HEIGHT} viewBox={`0 0 ${width} ${HEIGHT}`}>
          {deviation ? <rect className="sc-dev" x={deviation.x1} y={plot.y} width={Math.max(1, deviation.x2 - deviation.x1)} height={plot.h} /> : null}

          {layout.yTicks.map((t) => (
            <text key={`${t.label}-${t.y}`} className="sc-tick" x={plot.x - 6} y={t.y + 3.5} textAnchor="end">
              {t.label}
            </text>
          ))}
          <line className="sc-axis" x1={plot.x} x2={plot.x + plot.w} y1={plot.y + plot.h} y2={plot.y + plot.h} />
          {layout.xTicks.map((t) => (
            <g key={t.x}>
              <line className="sc-axis" x1={t.x} x2={t.x} y1={plot.y + plot.h} y2={plot.y + plot.h + 4} />
              <text className="sc-tick" x={t.x} y={plot.y + plot.h + 16} textAnchor="middle">
                {t.label}
              </text>
            </g>
          ))}

          {layout.baselinePath ? <path className="sc-base" d={layout.baselinePath} /> : null}
          <path className="sc-line" d={layout.actualPath} />

          {deviation?.onsetX != null ? (
            <g>
              <line className="sc-mark" x1={deviation.onsetX} x2={deviation.onsetX} y1={plot.y - 8} y2={plot.y + plot.h} />
              <text
                className="sc-label"
                x={onsetLeft ? deviation.onsetX - 4 : deviation.onsetX + 4}
                y={plot.y - 12}
                textAnchor={onsetLeft ? "end" : "start"}
              >
                {deviation.onsetLabel}
              </text>
            </g>
          ) : deviation ? (
            <text className="sc-label" x={plot.x + 4} y={plot.y - 12}>
              {deviation.onsetLabel}
            </text>
          ) : null}
          {deviation?.recoveryX != null ? (
            <g>
              <line className="sc-mark" x1={deviation.recoveryX} x2={deviation.recoveryX} y1={plot.y - (stacked ? 20 : 8)} y2={plot.y + plot.h} />
              <text className="sc-label" x={deviation.recoveryX - 4} y={plot.y - (stacked ? 24 : 12)} textAnchor="end">
                {deviation.recoveryLabel}
              </text>
            </g>
          ) : null}
        </svg>
      </div>
      <p className="sc-legend" aria-hidden>
        <span>
          <i className="lg lg-kpi" />
          Measured
        </span>
        {series.baseline_available ? (
          <span>
            <i className="lg lg-base" />
            Usual level
          </span>
        ) : null}
        <span className="mono">Africa/Tunis time</span>
      </p>
    </figure>
  );
}
