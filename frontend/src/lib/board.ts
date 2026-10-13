/**
 * Turns an investigation into the picture the board draws: one lane per evidence source, with the
 * span each lane has covered, the items found in it, and the conclusion once the report exists.
 * All times are held as UTC milliseconds; Africa/Tunis is UTC+1 all year.
 */
import { extractChart, extractDeviationPct } from "./chart";
import { dayTimeOf, timeOf } from "./format";
import type { RunView, ToolStep } from "./investigation";
import { ALARM_TYPES, categoryLabel, metricLabel } from "./labels";
import type { Classification, KpiSeries } from "./types";

export const HOUR = 3_600_000;
const MINUTE = 60_000;

export type LaneId = "alerts" | "alarms" | "kpis" | "changes" | "maintenance" | "events";

export interface LaneDef {
  id: LaneId;
  label: string;
  tool: string;
}

export const LANES: LaneDef[] = [
  { id: "alerts", label: "Detector alerts", tool: "get_anomalies" },
  { id: "alarms", label: "Alarms", tool: "get_alarms" },
  { id: "kpis", label: "KPIs", tool: "query_kpis" },
  { id: "changes", label: "Change log", tool: "get_changes" },
  { id: "maintenance", label: "Maintenance", tool: "get_maintenance" },
  { id: "events", label: "External events", tool: "get_external_events" },
];

export const TOOL_LANE: Record<string, LaneId> = Object.fromEntries(LANES.map((l) => [l.tool, l.id]));

export type Tone = "crit" | "major" | "minor" | "alert" | "change" | "maint" | "event";

export interface Mark {
  id: string;
  lane: LaneId;
  /** Evidence references the mark stands for. */
  refs: string[];
  /** The tool call that produced it. */
  origin: string;
  start: number;
  /** Null for a single moment. */
  end: number | null;
  /** Still going: no end is known. */
  open: boolean;
  label: string;
  kindLabel: string;
  tone: Tone;
  rows: Array<[string, string]>;
  /** How many alarms the mark stands for. */
  count: number;
}

export interface KpiRow {
  id: string;
  series: KpiSeries;
  deviationPct: number | undefined;
  origin: string;
  title: string;
}

export interface Span {
  a: number;
  b: number;
}

export type LaneState = "idle" | "checking" | "clear" | "found";

export interface LaneModel {
  def: LaneDef;
  state: LaneState;
  checking: boolean;
  spans: Span[];
  marks: Mark[];
  /** Every series found, those that moved away from their usual level first. */
  kpis: KpiRow[];
  calls: number;
}

export interface ContextLine {
  id: string;
  kind: "topology" | "runbooks" | "sql";
  label: string;
  chain?: string[];
  text?: string;
}

export interface Pin {
  n: number;
  ms: number;
  time: string;
  event: string;
  refs: string[];
}

export interface BoardModel {
  lanes: LaneModel[];
  scope: Span | null;
  domain: Span | null;
  impact: Span | null;
  cause: { ms: number; label: string } | null;
  /** The report verdict, which sets the colour and wording of the conclusion. */
  verdict: Classification | null;
  legend: { impact: string; cause: string };
  pins: Pin[];
  context: ContextLine[];
  /** Lanes the completeness check named that are still blank. */
  missing: Set<LaneId>;
}

const LOCAL = /^(\d{4})-(\d{2})-(\d{2})[ T](\d{2}):(\d{2})/;

/** "YYYY-MM-DD HH:MM" in Tunis time to UTC milliseconds. */
export function localToMs(s: unknown): number | null {
  if (typeof s !== "string") return null;
  const m = LOCAL.exec(s);
  if (!m) return null;
  return Date.UTC(+m[1], +m[2] - 1, +m[3], +m[4], +m[5]) - HOUR;
}

export function isoToMs(s: unknown): number | null {
  if (typeof s !== "string") return null;
  const t = Date.parse(s);
  return Number.isNaN(t) ? null : t;
}

const str = (v: unknown): string => (typeof v === "string" ? v : "");
const num = (v: unknown): number | null => (typeof v === "number" && Number.isFinite(v) ? v : null);
const rowsOf = (data: unknown): Array<Record<string, unknown>> => {
  const rows = (data as { rows?: unknown } | null)?.rows;
  return Array.isArray(rows) ? (rows.filter((r) => r && typeof r === "object") as Array<Record<string, unknown>>) : [];
};

export function humanize(s: string): string {
  const t = s.replace(/_/g, " ").trim();
  return t ? t[0].toUpperCase() + t.slice(1) : t;
}

export function durationText(ms: number): string {
  const min = Math.round(ms / MINUTE);
  if (min < 1) return "under a minute";
  if (min < 60) return `${min} min`;
  const h = Math.floor(min / 60);
  const m = min % 60;
  if (h >= 48) return `${Math.round(min / 1440)} days`;
  return m === 0 ? `${h} h` : `${h} h ${m} min`;
}

/** "16:50", or "22 Sep, 00:29" when it is not on the reference day. */
export function clock(ms: number, refDay?: number | null): string {
  if (refDay !== undefined && refDay !== null) {
    const same = Math.floor((ms + HOUR) / 86_400_000) === Math.floor((refDay + HOUR) / 86_400_000);
    if (!same) return dayTimeOf(ms);
  }
  return timeOf(ms);
}

function severityTone(severity: string): Tone {
  if (severity === "critical") return "crit";
  if (severity === "major") return "major";
  return "minor";
}

function plural(n: number, one: string, many = `${one}s`): string {
  return `${n} ${n === 1 ? one : many}`;
}

function mergeSpans(spans: Span[]): Span[] {
  const sorted = [...spans].sort((x, y) => x.a - y.a);
  const out: Span[] = [];
  for (const s of sorted) {
    const last = out.at(-1);
    if (last && s.a <= last.b) last.b = Math.max(last.b, s.b);
    else out.push({ ...s });
  }
  return out;
}

function callSpan(step: ToolStep): Span | null {
  const a = localToMs(step.args.start);
  let b = localToMs(step.args.end);
  const window = (step.result?.data as { window?: unknown } | null)?.window;
  const wa = Array.isArray(window) ? isoToMs(window[0]) : null;
  const wb = Array.isArray(window) ? isoToMs(window[1]) : null;
  const from = a ?? wa;
  b = b ?? wb;
  if (from === null || b === null || b < from) return null;
  return { a: from, b };
}

function alarmMarks(step: ToolStep): Mark[] {
  const out: Mark[] = [];
  for (const r of rowsOf(step.result?.data)) {
    const start = isoToMs(r.raised_at);
    if (start === null) continue;
    const id = str(r.alarm_id) || `${str(r.node_id)}-${start}`;
    const type = str(r.alarm_type);
    const node = str(r.node_id);
    const severity = str(r.severity);
    const group = r.group === true;
    const count = num(r.count) ?? 1;
    const lastRaised = isoToMs(r.last_raised_at);
    const cleared = isoToMs(r.cleared_at);
    const end = group ? (lastRaised ?? start) : cleared;
    const name = ALARM_TYPES[type]?.label ?? humanize(type);
    const refs = Array.isArray(r.alarm_ids) ? (r.alarm_ids as unknown[]).map(String) : [id];
    const rows: Array<[string, string]> = [
      ["Severity", severity || "unknown"],
      ["Node", node],
    ];
    if (group) rows.push(["Repeats", `${count} alarms between ${timeOf(start)} and ${timeOf(end ?? start)}`]);
    out.push({
      id,
      lane: "alarms",
      refs,
      origin: step.id,
      start,
      end,
      open: !group && cleared === null,
      label: `${name} · ${node}${group ? ` ×${count}` : ""}`,
      kindLabel: "Alarm",
      tone: severityTone(severity),
      rows,
      count,
    });
  }
  return out;
}

/** When there are many alarms, one mark per node and alarm type, with a count. */
function groupAlarms(marks: Mark[]): Mark[] {
  if (marks.length <= 12) return marks;
  const byKey = new Map<string, Mark[]>();
  for (const m of marks) {
    const key = `${m.label.split(" ×")[0]}|${m.tone}`;
    byKey.set(key, [...(byKey.get(key) ?? []), m]);
  }
  const out: Mark[] = [];
  for (const [key, list] of byKey) {
    if (list.length === 1) {
      out.push(list[0]);
      continue;
    }
    const start = Math.min(...list.map((m) => m.start));
    const end = Math.max(...list.map((m) => m.end ?? m.start));
    const base = list[0].label.split(" ×")[0];
    const total = list.reduce((n, m) => n + m.count, 0);
    out.push({
      ...list[0],
      id: `group-${key}`,
      refs: list.flatMap((m) => m.refs),
      start,
      end,
      open: list.some((m) => m.open),
      label: `${base} ×${total}`,
      count: total,
      rows: [...list[0].rows.slice(0, 2), ["Repeats", `${total} alarms from ${timeOf(start)} to ${timeOf(end)}`]],
    });
  }
  return out;
}

function alertMarks(step: ToolStep): Mark[] {
  const alerts = (step.result?.data as { alerts?: unknown } | null)?.alerts;
  if (!Array.isArray(alerts)) return [];
  const out: Mark[] = [];
  for (const a of alerts as Array<Record<string, unknown>>) {
    const start = isoToMs(a.start_at);
    if (start === null) continue;
    const id = str(a.alert_id);
    if (!id) continue;
    const entities = Array.isArray(a.entities) ? (a.entities as unknown[]).map(String) : [];
    const sites = entities.filter((e) => /^S-[A-Z]{3}-\d+/.test(e));
    const others = entities.filter((e) => !/^S-[A-Z]{3}-\d+/.test(e) && !/^[A-Z]{3}$/.test(e));
    const regions = entities.filter((e) => /^[A-Z]{3}$/.test(e));
    const severity = str(a.severity);
    const metrics = Array.isArray(a.metrics) ? (a.metrics as unknown[]).map((m) => metricLabel(String(m))) : [];
    const what = sites.length > 0 ? plural(sites.length, "site") : others.length > 0 ? others[0] : regions.length > 0 ? regions.join(", ") : "no named node";
    const ongoing = a.ongoing === true;
    const rows: Array<[string, string]> = [
      ["Severity", severity || "unknown"],
      ["Covers", [sites.length > 0 ? sites.slice(0, 4).join(", ") + (sites.length > 4 ? ` and ${sites.length - 4} more` : "") : "", others.join(", ")].filter(Boolean).join(" and ") || what],
    ];
    if (metrics.length) rows.push(["KPIs", metrics.join(", ")]);
    out.push({
      id,
      lane: "alerts",
      refs: [id],
      origin: step.id,
      start,
      end: isoToMs(a.end_at),
      open: ongoing,
      label: `${humanize(severity || "alert")} · ${what}`,
      kindLabel: "Detector alert",
      tone: "alert",
      rows,
      count: 1,
    });
  }
  return out;
}

function changeMarks(step: ToolStep): Mark[] {
  const raw = rowsOf(step.result?.data);
  const byKey = new Map<string, Array<Record<string, unknown>>>();
  for (const r of raw) {
    const key = `${str(r.change_type)}|${str(r.executed_at)}|${r.rolled_back === true}`;
    byKey.set(key, [...(byKey.get(key) ?? []), r]);
  }
  const out: Mark[] = [];
  for (const list of byKey.values()) {
    const first = list[0];
    const start = isoToMs(first.executed_at);
    if (start === null) continue;
    const nodes = list.map((r) => str(r.node_id)).filter(Boolean);
    const rolled = first.rolled_back === true;
    const type = humanize(str(first.change_type) || "change");
    const where = nodes.length > 1 ? `${nodes.length} nodes` : (nodes[0] ?? "");
    out.push({
      id: str(first.change_id) || `chg-${start}`,
      lane: "changes",
      refs: list.map((r) => str(r.change_id)).filter(Boolean),
      origin: step.id,
      start,
      end: null,
      open: false,
      label: `${type} · ${where}${rolled ? " · rolled back" : ""}`,
      kindLabel: "Change",
      tone: "change",
      rows: [
        ["Nodes", nodes.join(", ")],
        ["What", str(first.description)],
        ["Rolled back", rolled ? "yes" : "no"],
      ],
      count: list.length,
    });
  }
  return out;
}

function windowMarks(step: ToolStep, lane: "maintenance" | "events"): Mark[] {
  const out: Mark[] = [];
  for (const r of rowsOf(step.result?.data)) {
    const start = isoToMs(r.start_at);
    if (start === null) continue;
    const id = str(lane === "maintenance" ? r.mw_id : r.event_id) || `${lane}-${start}`;
    const desc = str(r.description) || (lane === "maintenance" ? "Maintenance window" : humanize(str(r.event_type)));
    const node = str(r.node_id);
    const end = isoToMs(r.end_at);
    const rows: Array<[string, string]> = [["What", desc]];
    if (node) rows.push(["Node", node]);
    if (lane === "maintenance") {
      if (str(r.expected_impact)) rows.push(["Expected impact", str(r.expected_impact)]);
      if (str(r.state)) rows.push(["State", str(r.state)]);
    } else if (str(r.region_id)) rows.push(["Region", str(r.region_id)]);
    out.push({
      id,
      lane,
      refs: [id],
      origin: step.id,
      start,
      end,
      open: end === null,
      label: node ? `${desc} · ${node}` : desc,
      kindLabel: lane === "maintenance" ? "Maintenance window" : "External event",
      tone: lane === "maintenance" ? "maint" : "event",
      rows,
      count: 1,
    });
  }
  return out;
}

function kpiRows(step: ToolStep): KpiRow[] {
  const data = step.result?.data;
  const dev = extractDeviationPct(data);
  return extractChart(data).map((series) => ({
    id: `${series.entity_id}|${series.metric}`,
    series,
    deviationPct: dev.get(`${series.entity_id}|${series.metric}`),
    origin: step.id,
    title: `${series.entity_id} · ${metricLabel(series.metric)}`,
  }));
}

function seriesSpan(series: KpiSeries): Span | null {
  const a = isoToMs(series.start);
  if (a === null) return null;
  return { a, b: a + (series.values.length - 1) * series.step_minutes * MINUTE };
}

/** Which lanes a completeness-check phrase such as "the change log" refers to. */
export function lanesFromPhrase(phrase: string): LaneId[] {
  const p = phrase.toLowerCase();
  const out: LaneId[] = [];
  if (/external|event|holiday/.test(p)) out.push("events");
  if (/change/.test(p)) out.push("changes");
  if (/maintenance/.test(p)) out.push("maintenance");
  if (/alarm/.test(p)) out.push("alarms");
  if (/anomal|detector|alert/.test(p)) out.push("alerts");
  if (/kpi|metric/.test(p)) out.push("kpis");
  return out;
}

function chain(headline: string): string[] | null {
  const body = headline.includes(":") ? headline.slice(headline.indexOf(":") + 1) : headline;
  const parts = body.split("->").map((p) => p.replace(/\(.*?\)/g, "").trim());
  return parts.length >= 2 && parts.every((p) => /^[A-Z][A-Z0-9-]+$/.test(p)) ? parts : null;
}

function byDeviation(a: KpiRow, b: KpiRow): number {
  const rank = (r: KpiRow) => (r.series.deviation ? 1 : 0);
  return rank(b) - rank(a) || Math.abs(b.deviationPct ?? 0) - Math.abs(a.deviationPct ?? 0);
}

export function buildBoard(view: RunView): BoardModel {
  const lanes = new Map<LaneId, LaneModel>(
    LANES.map((def) => [def.id, { def, state: "idle", checking: false, spans: [], marks: [], kpis: [], calls: 0 }]),
  );
  const marks = new Map<LaneId, Map<string, Mark>>(LANES.map((l) => [l.id, new Map()]));
  const kpis = new Map<string, KpiRow>();
  const spans = new Map<LaneId, Span[]>(LANES.map((l) => [l.id, []]));
  const context: ContextLine[] = [];
  const missing = new Set<LaneId>();
  let scope: Span | null = null;

  for (const step of view.steps) {
    if (step.kind === "scope") {
      const a = isoToMs(step.data.window_start);
      const b = isoToMs(step.data.window_end);
      if (a !== null && b !== null && b > a) scope = { a, b };
    } else if (step.kind === "gate") {
      for (const phrase of step.data.missing ?? []) for (const l of lanesFromPhrase(phrase)) missing.add(l);
    } else if (step.kind === "tool") {
      const lane = TOOL_LANE[step.tool];
      if (lane) {
        const model = lanes.get(lane)!;
        if (step.status === "running") model.checking = true;
        if (step.status === "done") {
          model.calls += 1;
          const span = callSpan(step);
          if (span) spans.get(lane)!.push(span);
          const bucket = marks.get(lane)!;
          let found: Mark[] = [];
          if (lane === "alarms") found = alarmMarks(step);
          else if (lane === "alerts") found = alertMarks(step);
          else if (lane === "changes") found = changeMarks(step);
          else if (lane === "maintenance") found = windowMarks(step, "maintenance");
          else if (lane === "events") found = windowMarks(step, "events");
          else if (lane === "kpis") {
            for (const row of kpiRows(step)) {
              kpis.set(row.id, row);
              const s = seriesSpan(row.series);
              if (s) spans.get(lane)!.push(s);
            }
          }
          for (const m of found) bucket.set(m.id, m);
        }
      } else if (step.status === "done" && step.result) {
        const r = step.result;
        if (step.tool === "get_topology") {
          const nodes = chain(r.headline);
          context.push({ id: step.id, kind: "topology", label: "Topology", chain: nodes ?? undefined, text: nodes ? undefined : r.headline });
        } else if (step.tool === "search_runbooks") {
          const hits = (r.data as { hits?: unknown } | null)?.hits;
          const n = Array.isArray(hits) ? hits.length : r.refs.length;
          const query = str(step.args.query);
          context.push({ id: step.id, kind: "runbooks", label: "Runbooks", text: `${plural(n, "passage")}${query ? ` for “${query}”` : ""}` });
        } else if (step.tool === "run_sql") {
          context.push({ id: step.id, kind: "sql", label: "Query", text: r.headline.replace(/^run_sql:?\s*/, "") });
        }
      }
    }
  }

  // A lane that was filled after the check named it no longer needs pointing at.
  for (const l of [...missing]) if ((lanes.get(l)?.calls ?? 0) > 0) missing.delete(l);

  for (const def of LANES) {
    const m = lanes.get(def.id)!;
    m.spans = mergeSpans(spans.get(def.id)!);
    let found = [...marks.get(def.id)!.values()];
    if (def.id === "alarms") found = groupAlarms(found);
    m.marks = found.sort((x, y) => x.start - y.start);
    if (def.id === "kpis") m.kpis = [...kpis.values()].sort(byDeviation);
    const hasItems = m.marks.length > 0 || m.kpis.length > 0;
    m.state = m.checking ? "checking" : hasItems ? "found" : m.calls > 0 ? "clear" : "idle";
  }

  const report = view.report;
  const impactA = localToMs(report?.impact_start);
  const impactB = localToMs(report?.impact_end);
  const impact = impactA !== null ? { a: impactA, b: impactB ?? impactA } : null;
  const causeMs = localToMs(report?.root_cause_time);
  const verdict = report?.classification ?? null;
  const cause = report && causeMs !== null ? { ms: causeMs, label: causeText(report.classification, report.root_cause_category, report.root_cause_node_id) } : null;
  const pins: Pin[] = [];
  (report?.timeline ?? []).forEach((t, i) => {
    const ms = localToMs(t.time);
    if (ms !== null) pins.push({ n: i + 1, ms, time: t.time, event: t.event, refs: t.refs });
  });

  const all = [...lanes.values()];
  return {
    lanes: all,
    scope,
    domain: computeDomain(scope, all, impact, cause?.ms ?? null, pins),
    impact,
    cause,
    verdict,
    legend: legendText(verdict),
    pins,
    context,
    missing,
  };
}

function causeText(verdict: Classification, category: string, node: string | null): string {
  if (verdict === "no_impact") return "No customer impact";
  if (category === "unknown") return "Cause unknown";
  const c = categoryLabel(category);
  const what = node ? `${c} at ${node}` : c;
  if (verdict === "planned_maintenance" || verdict === "expected_event") return `Explained by: ${what}`;
  return `Cause: ${what}`;
}

function legendText(verdict: Classification | null): { impact: string; cause: string } {
  if (verdict === "no_impact") return { impact: "Window examined", cause: "No customer impact" };
  if (verdict === "planned_maintenance" || verdict === "expected_event") return { impact: "Impact window", cause: "Explained by" };
  return { impact: "Impact window", cause: "Cause" };
}

/**
 * The time span the axis covers: the scope, widened to everything found. A query that looked far
 * beyond the scope, or an item that ran for a day, widens it only so far.
 */
function computeDomain(scope: Span | null, lanes: LaneModel[], impact: Span | null, cause: number | null, pins: Pin[]): Span | null {
  if (!scope) return null;
  const lo = scope.a - 2 * HOUR;
  const hi = scope.b + 8 * HOUR;
  let a = scope.a;
  let b = scope.b;
  const take = (x: number | null | undefined, y?: number | null, reach = 0) => {
    if (x === null || x === undefined) return;
    const floor = reach ? scope.a - reach : lo;
    const ceil = reach ? scope.b + reach : hi;
    const cx = Math.min(ceil, Math.max(floor, x));
    a = Math.min(a, cx);
    b = Math.max(b, cx);
    if (y !== null && y !== undefined) {
      const cy = Math.min(ceil, Math.max(floor, y));
      a = Math.min(a, cy);
      b = Math.max(b, cy);
    }
  };
  for (const lane of lanes) {
    for (const s of lane.spans) take(s.a, s.b, HOUR / 2);
    for (const m of lane.marks) {
      // A detector alert is a loose window and can run for a day; it widens the axis only a little.
      if (lane.def.id === "alerts") take(m.start, m.end === null ? null : Math.min(m.end, scope.b + HOUR));
      else take(m.start, m.end);
    }
  }
  if (impact) take(impact.a, impact.b);
  take(cause);
  for (const p of pins) take(p.ms);
  const pad = Math.max((b - a) * 0.035, 10 * MINUTE);
  return { a: a - pad, b: b + pad };
}

export interface Tick {
  ms: number;
  label: string;
  /** The date to print under the time, on midnight and on the first tick. */
  date: string | null;
}

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

export function makeTicks(domain: Span, width: number, minGap = 64): Tick[] {
  const max = Math.max(2, Math.floor(width / minGap));
  const span = domain.b - domain.a;
  const steps = [1, 2, 3, 4, 6, 12, 24];
  const step = steps.find((s) => span / (s * HOUR) <= max) ?? 24;
  const stepMs = step * HOUR;
  const out: Tick[] = [];
  const first = Math.ceil((domain.a + HOUR) / stepMs) * stepMs - HOUR;
  for (let t = first; t <= domain.b; t += stepMs) {
    const local = new Date(t + HOUR);
    const midnight = local.getUTCHours() === 0;
    out.push({
      ms: t,
      label: timeOf(t),
      date: midnight || out.length === 0 ? `${local.getUTCDate()} ${MONTHS[local.getUTCMonth()]}` : null,
    });
  }
  return out;
}

export interface Placed {
  mark: Mark;
  x0: number;
  x1: number;
  labelW: number;
  row: number;
  /** The mark runs past the right edge of the axis. */
  continues: boolean;
  /** The mark starts before the left edge of the axis. */
  before: boolean;
}

/** Stack marks into rows so neither a bar nor its label overlaps the next. */
export function packMarks(marks: Mark[], x: (ms: number) => number, width: number, labelWidth: (m: Mark) => number): { placed: Placed[]; rows: number } {
  const rowEnds: number[] = [];
  const placed: Placed[] = [];
  for (const mark of marks) {
    const rawX0 = x(mark.start);
    const before = rawX0 < -0.5;
    const x0 = Math.max(0, rawX0);
    const rawEnd = mark.end ?? mark.start;
    const x1 = Math.max(x0 + (mark.end === null ? 0 : 6), x(mark.open && mark.end === null ? Number.POSITIVE_INFINITY : rawEnd));
    const clipped = Math.min(x1, width);
    const labelW = labelWidth(mark);
    const extent = Math.max(clipped, x0 + labelW) + 10;
    let row = rowEnds.findIndex((end) => end <= x0);
    if (row === -1) {
      row = rowEnds.length;
      rowEnds.push(extent);
    } else rowEnds[row] = extent;
    placed.push({ mark, x0, x1: clipped, labelW, row, before, continues: x1 > width + 0.5 || (mark.open && mark.end === null) });
  }
  return { placed, rows: Math.max(1, rowEnds.length) };
}

export function spanText(span: Span, refDay: number | null): string {
  return `${clock(span.a, refDay)} and ${clock(span.b, refDay)}`;
}

export function markTimes(m: Mark): string {
  if (m.end === null) return clock(m.start);
  const dur = durationText(m.end - m.start);
  return `${clock(m.start)} to ${clock(m.end, m.start)}${m.open ? " (not cleared)" : ` (${dur})`}`;
}

/** The most marks one lane draws before it offers to show the rest. */
export const MARK_CAP = 12;

const TONE_RANK: Record<Tone, number> = { crit: 6, major: 5, alert: 4, change: 4, maint: 4, event: 4, minor: 3 };

/**
 * Keeps the most severe marks of a crowded lane, in time order, and says how many were left out.
 * A mark the reader has selected always stays.
 */
export function capMarks(marks: Mark[], cap: number, keepId: string | null = null): { shown: Mark[]; hidden: number } {
  if (marks.length <= cap) return { shown: marks, hidden: 0 };
  const ranked = [...marks].sort((a, b) => TONE_RANK[b.tone] - TONE_RANK[a.tone] || Number(b.open) - Number(a.open) || a.start - b.start);
  const keep = new Set(ranked.slice(0, cap).map((m) => m.id));
  if (keepId && marks.some((m) => m.id === keepId) && !keep.has(keepId)) {
    keep.delete(ranked[cap - 1].id);
    keep.add(keepId);
  }
  return { shown: marks.filter((m) => keep.has(m.id)), hidden: marks.length - cap };
}

/** The longest a mark's label may be drawn before it is cut with an ellipsis. */
export const LABEL_MAX = 260;

export function markLabelWidth(label: string, boardWidth: number): number {
  return Math.min(Math.ceil(label.length * 6.3) + 4, LABEL_MAX, Math.max(60, boardWidth - 16));
}

export const PIN_SIZE = 22;
export const MAX_PIN_ROWS = 3;

export interface PlacedPin {
  pin: Pin;
  /** Where the entry sits on the axis. */
  at: number;
  /** Where its numbered circle is drawn. */
  px: number;
  row: number;
}

/**
 * Places the timeline pins under the axis, nudged apart so none overlaps. Too many for one line
 * wrap onto up to three, and any beyond that are counted.
 */
export function layoutPins(pins: Pin[], x: (ms: number) => number, width: number, gap = 2): { placed: PlacedPin[]; hidden: number; rows: number } {
  const sorted = [...pins].sort((p, q) => p.ms - q.ms || p.n - q.n);
  const half = PIN_SIZE / 2 + 1;
  const maxPx = width - half;
  const step = PIN_SIZE + gap;
  const clampX = (at: number) => Math.min(Math.max(at, half), maxPx);
  const perRow = Math.max(1, Math.floor((width - 2) / step));

  // Each line holds the next run of entries in time order, nudged apart and pulled back from the edge.
  const placed: PlacedPin[] = [];
  const shown = sorted.slice(0, perRow * MAX_PIN_ROWS);
  for (let start = 0, row = 0; start < shown.length; start += perRow, row++) {
    let prev = -Infinity;
    const line = shown.slice(start, start + perRow).map((pin) => {
      const at = x(pin.ms);
      const px = Math.max(prev + step, clampX(at));
      prev = px;
      return { pin, at, px, row };
    });
    // A run pushed past the right edge is pulled back in, never past the left edge.
    line.forEach((p, i) => placed.push({ ...p, px: Math.min(p.px, maxPx - (line.length - 1 - i) * step) }));
  }
  return { placed, hidden: sorted.length - shown.length, rows: Math.max(1, Math.ceil(shown.length / perRow)) };
}
