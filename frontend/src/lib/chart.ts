/** Geometry and wording for the KPI charts. Pure functions, so they can be tested without a DOM. */
import { compact, dayTimeOf, timeOf, toMs } from "./format";
import { metricLabel } from "./labels";
import type { KpiSeries } from "./types";

export interface Margins {
  left: number;
  right: number;
  top: number;
  bottom: number;
}

export interface XTick {
  x: number;
  label: string;
  /** A day boundary, labelled with the date instead of the time. */
  day: boolean;
}

export interface YTick {
  y: number;
  label: string;
}

export interface DeviationMark {
  x1: number;
  x2: number;
  onsetX: number | null;
  recoveryX: number | null;
  onsetLabel: string;
  recoveryLabel: string;
}

export interface ChartLayout {
  width: number;
  height: number;
  margins: Margins;
  plot: { x: number; y: number; w: number; h: number };
  actualPath: string;
  baselinePath: string;
  xTicks: XTick[];
  yTicks: YTick[];
  deviation: DeviationMark | null;
}

const MINUTE = 60_000;
const TUNIS_OFFSET = 3_600_000;
const TICK_STEPS_MIN = [15, 30, 60, 120, 180, 360, 720, 1440];

/** Accepts the `chart` field of a `query_kpis` result and drops anything malformed. */
export function extractChart(data: unknown): KpiSeries[] {
  if (!data || typeof data !== "object") return [];
  const chart = (data as { chart?: unknown }).chart;
  if (!Array.isArray(chart)) return [];
  return chart.filter(isSeries);
}

function isSeries(x: unknown): x is KpiSeries {
  if (!x || typeof x !== "object") return false;
  const s = x as Partial<KpiSeries>;
  return (
    typeof s.start === "string" &&
    typeof s.step_minutes === "number" &&
    s.step_minutes > 0 &&
    Array.isArray(s.values) &&
    s.values.length > 1 &&
    Array.isArray(s.baseline)
  );
}

/** Mean deviation from baseline per "entity|metric", from the `pairs` of a `query_kpis` result. */
export function extractDeviationPct(data: unknown): Map<string, number> {
  const out = new Map<string, number>();
  const pairs = (data as { pairs?: unknown } | null)?.pairs;
  if (!Array.isArray(pairs)) return out;
  for (const p of pairs as Array<Record<string, unknown>>) {
    if (typeof p.entity === "string" && typeof p.metric === "string" && typeof p.deviation_pct === "number") {
      out.set(`${p.entity}|${p.metric}`, p.deviation_pct);
    }
  }
  return out;
}

export function niceTicks(min: number, max: number, count = 3): number[] {
  if (!(max > min)) return [min];
  const rough = (max - min) / count;
  const pow = 10 ** Math.floor(Math.log10(rough));
  const norm = rough / pow;
  const step = (norm <= 1 ? 1 : norm <= 2 ? 2 : norm <= 5 ? 5 : 10) * pow;
  const ticks: number[] = [];
  for (let v = Math.ceil(min / step) * step; v <= max + step * 1e-9; v += step) ticks.push(Number(v.toPrecision(12)));
  return ticks;
}

function finite(values: Array<number | null>): number[] {
  return values.filter((v): v is number => typeof v === "number" && Number.isFinite(v));
}

function path(values: Array<number | null>, x: (i: number) => number, y: (v: number) => number): string {
  let d = "";
  let open = false;
  values.forEach((v, i) => {
    if (typeof v !== "number" || !Number.isFinite(v)) {
      open = false;
      return;
    }
    d += `${open ? "L" : "M"}${x(i).toFixed(1)} ${y(v).toFixed(1)}`;
    open = true;
  });
  return d;
}

export function layoutChart(series: KpiSeries, width: number, height: number, margins?: Partial<Margins>): ChartLayout {
  const m: Margins = { left: 40, right: 12, top: 30, bottom: 24, ...margins };
  const plot = { x: m.left, y: m.top, w: Math.max(40, width - m.left - m.right), h: Math.max(40, height - m.top - m.bottom) };
  const n = series.values.length;
  const startMs = toMs(series.start);
  const stepMs = series.step_minutes * MINUTE;
  const x = (i: number) => plot.x + (i / (n - 1)) * plot.w;

  const all = [...finite(series.values), ...finite(series.baseline)];
  let lo = all.length ? Math.min(...all) : 0;
  let hi = all.length ? Math.max(...all) : 1;
  if (lo >= 0 && lo <= hi * 0.5) lo = 0;
  else {
    const pad = (hi - lo) * 0.1 || Math.abs(hi) * 0.1 || 1;
    lo -= pad;
  }
  const headroom = (hi - lo) * 0.06 || 1;
  hi += headroom;
  const y = (v: number) => plot.y + plot.h - ((v - lo) / (hi - lo)) * plot.h;

  const yTicks = niceTicks(lo, hi, 3).map((v) => ({ y: y(v), label: compact(v) }));

  // Time ticks sit on whole local hours (or the nearest step), never closer than ~64px.
  const spanMin = ((n - 1) * series.step_minutes) / 1;
  const maxTicks = Math.max(2, Math.floor(plot.w / 64));
  const tickStep = TICK_STEPS_MIN.find((s) => spanMin / s <= maxTicks) ?? 1440;
  const tickMs = tickStep * MINUTE;
  const xTicks: XTick[] = [];
  const firstLocal = startMs + TUNIS_OFFSET;
  for (let t = Math.ceil(firstLocal / tickMs) * tickMs; t <= firstLocal + (n - 1) * stepMs; t += tickMs) {
    const utc = t - TUNIS_OFFSET;
    const i = (utc - startMs) / stepMs;
    const midnight = t % 86_400_000 === 0;
    xTicks.push({
      x: x(i),
      label: midnight ? dayTimeOf(utc).split(",")[0] : timeOf(utc),
      day: midnight,
    });
  }

  let deviation: DeviationMark | null = null;
  const d = series.deviation;
  if (d && series.baseline_available) {
    const onsetIdx = clamp((toMs(d.onset) - startMs) / stepMs, 0, n - 1);
    const recIdx = d.recovery ? clamp((toMs(d.recovery) - startMs) / stepMs, 0, n - 1) : null;
    deviation = {
      x1: x(onsetIdx),
      x2: x(recIdx ?? n - 1),
      onsetX: d.began_before_window ? null : x(onsetIdx),
      recoveryX: recIdx === null ? null : x(recIdx),
      onsetLabel: d.began_before_window ? "began earlier" : `${d.direction === "above" ? "above" : "below"} from ${timeOf(toMs(d.onset))}`,
      recoveryLabel: recIdx === null ? "" : `back to normal ${timeOf(toMs(d.recovery!))}`,
    };
  }

  return {
    width,
    height,
    margins: m,
    plot,
    actualPath: path(series.values, x, y),
    baselinePath: series.baseline_available ? path(series.baseline, x, y) : "",
    xTicks,
    yTicks,
    deviation,
  };
}

function clamp(v: number, lo: number, hi: number): number {
  return Math.min(hi, Math.max(lo, v));
}

/** A deviation from the usual level as a signed percentage; extreme values are capped so they stay readable. */
export function pctText(pct: number): string {
  if (!Number.isFinite(pct)) return "";
  if (pct >= 1000) return "over +999%";
  if (pct <= -1000) return "under -999%";
  return `${pct > 0 ? "+" : ""}${Math.round(pct)}%`;
}

/** The one message of the chart, as a sentence. */
export function chartCaption(series: KpiSeries, deviationPct?: number): string {
  if (!series.baseline_available) return "No baseline is available; the measured values are shown on their own.";
  const d = series.deviation;
  if (!d) return "Stays within its usual range for this time of day.";
  const dir = d.direction === "above" ? "Above" : "Below";
  const pct = deviationPct !== undefined && Number.isFinite(deviationPct) ? ` (${pctText(deviationPct)} on average)` : "";
  const from = d.began_before_window ? "since before this window" : `from ${timeOf(toMs(d.onset))}`;
  const to = d.recovery ? `until ${timeOf(toMs(d.recovery))}` : "and still running";
  return `${dir} its usual level ${from} ${to}${pct}.`;
}

/** The text alternative for the chart. */
export function chartAlt(series: KpiSeries, deviationPct?: number): string {
  const values = finite(series.values);
  const peak = values.length ? Math.max(...values) : null;
  const low = values.length ? Math.min(...values) : null;
  const end = toMs(series.start) + (series.values.length - 1) * series.step_minutes * MINUTE;
  const range = `from ${dayTimeOf(toMs(series.start))} to ${dayTimeOf(end)}, Tunis time`;
  const extremes = peak !== null && low !== null ? ` Values range from ${compact(low)} to ${compact(peak)} ${series.unit}.` : "";
  return `${metricLabel(series.metric)} for ${series.entity_id}, in ${series.unit}, ${range}. ${chartCaption(series, deviationPct)}${extremes} The dashed line is the baseline.`;
}
