"use client";

import { Undo2 } from "lucide-react";
import { useCallback, useMemo, useState, type CSSProperties } from "react";
import { chartCaption, pctText } from "@/lib/chart";
import { capMarks, isoToMs, MARK_CAP, markLabelWidth, markTimes, packMarks, spanText, type BoardModel, type KpiRow, type LaneModel, type Mark, type Placed, type Span, type Tick } from "@/lib/board";
import { Conclusion } from "./board-conclusion";
import { useCoarsePointer } from "./use-coarse";

const MARK_ROW = 36;
/** With a finger, a row of marks is tall enough to press without hitting its neighbour. */
const MARK_ROW_TOUCH = 46;
const KPI_ROW = 68;
const KPI_CAP = 4;
const LANE_PAD = 8;
const MIN_LANE = 46;
const TOGGLE_ROOM = 30;
const TOGGLE_ROOM_TOUCH = 46;

export interface LaneProps {
  lane: LaneModel;
  model: BoardModel;
  domain: Span | null;
  width: number;
  x(ms: number): number;
  ticks: Tick[];
  selectedId: string | null;
  onSelect(id: string | null): void;
  highlightRefs: ReadonlySet<string>;
  hover: boolean;
  missing: boolean;
  refDay: number | null;
  showTip(el: HTMLElement, title: string, lines: string[]): void;
  hideTip(): void;
  conclusion: boolean;
  inert: boolean;
  kpiExpanded: boolean;
  onToggleKpis(): void;
}

export function LaneView(p: LaneProps) {
  const { lane, domain, width, x } = p;
  const isKpi = lane.def.id === "kpis";
  const coarse = useCoarsePointer();
  const markRow = coarse ? MARK_ROW_TOUCH : MARK_ROW;
  const toggleRoom = coarse ? TOGGLE_ROOM_TOUCH : TOGGLE_ROOM;
  const [allMarks, setAllMarks] = useState(false);
  const canToggleMarks = !isKpi && lane.marks.length > MARK_CAP;
  const capped = useMemo(
    () => (canToggleMarks && !allMarks ? capMarks(lane.marks, MARK_CAP, p.selectedId) : { shown: lane.marks, hidden: 0 }),
    [canToggleMarks, allMarks, lane.marks, p.selectedId],
  );
  const labelWidth = useCallback((m: Mark) => markLabelWidth(m.label, width), [width]);
  const packed = useMemo(
    () => (isKpi || !domain ? { placed: [] as Placed[], rows: 1 } : packMarks(capped.shown, x, width, labelWidth)),
    [isKpi, capped.shown, domain, x, width, labelWidth],
  );

  const kpiTotal = lane.kpis.length;
  const kpiShown = p.kpiExpanded ? lane.kpis : lane.kpis.slice(0, KPI_CAP);
  const canToggle = kpiTotal > KPI_CAP;

  let height = MIN_LANE;
  if (isKpi && kpiTotal) height = LANE_PAD * 2 + kpiShown.length * KPI_ROW + (canToggle ? toggleRoom : 0);
  else if (lane.marks.length) height = LANE_PAD * 2 + packed.rows * markRow + (canToggleMarks ? toggleRoom : 0);

  const checking = lane.state === "checking";
  const count = lane.marks.length + kpiTotal;
  const hasItems = count > 0;
  const cls = ["ln", `s-${lane.state}`, p.hover ? "is-hover" : "", p.missing ? "is-missing" : ""].filter(Boolean).join(" ");

  return (
    <section className={cls} aria-label={lane.def.label}>
      <div className="ln-label">
        <h3>{lane.def.label}</h3>
        <code>{lane.def.tool}</code>
        {checking && hasItems ? <span className="ln-note">checking…</span> : null}
        {!checking && hasItems ? <span className="ln-note">{isKpi ? `${count} series` : `${count} found`}</span> : null}
      </div>
      <div className="ln-track" style={{ height }}>
        {domain ? p.ticks.map((t) => <i key={t.ms} className="gl" style={{ left: x(t.ms) }} />) : null}
        {p.conclusion ? <Conclusion model={p.model} x={x} width={width} part="lane" /> : null}

        {lane.spans.map((s, i) => (
          <Cover key={i} span={s} domain={domain} x={x} clear={lane.state === "clear"} />
        ))}

        {lane.state === "idle" && !p.missing ? <span className="ln-state">not checked yet</span> : null}
        {lane.state === "idle" && p.missing ? (
          <span className="ln-state is-pointed">
            <Undo2 aria-hidden size={14} strokeWidth={2} /> Still blank. The agent is sent back to check here.
          </span>
        ) : null}
        {checking && !hasItems ? <span className="ln-state is-checking">checking…</span> : null}
        {lane.state === "clear" && domain ? <ClearText lane={lane} domain={domain} x={x} refDay={p.refDay} /> : null}

        {isKpi
          ? kpiShown.map((row, i) => <KpiLine key={row.id} row={row} index={i} {...p} />)
          : packed.placed.map((pl) => <MarkView key={pl.mark.id} placed={pl} rowH={markRow} {...p} />)}
        {canToggleMarks ? (
          <button type="button" className="link kp-toggle" aria-expanded={allMarks} onClick={() => setAllMarks((v) => !v)}>
            {allMarks ? "Show the most severe only" : `Show all ${lane.marks.length} (${MARK_CAP} most severe shown)`}
          </button>
        ) : null}
        {isKpi && canToggle ? (
          <button type="button" className="link kp-toggle" aria-expanded={p.kpiExpanded} onClick={p.onToggleKpis}>
            {p.kpiExpanded ? "Show fewer" : `Show all ${kpiTotal}`}
          </button>
        ) : null}

        {checking ? <i className="sweep" aria-hidden /> : null}
      </div>
    </section>
  );
}

function Cover({ span, domain, x, clear }: { span: Span; domain: Span | null; x(ms: number): number; clear: boolean }) {
  if (!domain) return null;
  const a = Math.max(span.a, domain.a);
  const b = Math.min(span.b, domain.b);
  if (b <= a) return null;
  const left = x(a);
  const w = Math.max(2, x(b) - left);
  return (
    <i className={`cv${clear ? " is-clear" : ""}`} style={{ left, width: w }} aria-hidden>
      {span.a >= domain.a ? <b className="cv-cap is-l" /> : null}
      {span.b <= domain.b ? <b className="cv-cap is-r" /> : null}
    </i>
  );
}

function ClearText({ lane, domain, x, refDay }: { lane: LaneModel; domain: Span; x(ms: number): number; refDay: number | null }) {
  const first = lane.spans[0];
  if (!first) return <span className="ln-state">checked, nothing found</span>;
  const text = lane.spans.length === 1 ? `nothing between ${spanText(first, refDay)}` : `nothing in the ${lane.spans.length} spans checked`;
  const left = Math.max(6, x(Math.max(first.a, domain.a)) + 6);
  return (
    <span className="ln-clear" style={{ left }}>
      {text}
    </span>
  );
}

function MarkView({ placed, rowH, width, selectedId, onSelect, highlightRefs, inert, showTip, hideTip }: LaneProps & { placed: Placed; rowH: number }) {
  const { mark, x0, x1, labelW, row, continues, before } = placed;
  const isTick = mark.end === null && !mark.open;
  const barW = isTick ? 2 : Math.max(6, x1 - x0);
  const cell = Math.max(barW + (isTick ? 7 : 0), labelW);
  const left = Math.max(0, Math.min(x0 - (isTick ? 3 : 0), width - cell));
  const shapeLeft = x0 - (isTick ? 3 : 0) - left;
  const edge = before ? 8 : 0;
  const selected = selectedId === mark.id;
  const outlined = highlightRefs.has(mark.origin) || mark.refs.some((r) => highlightRefs.has(r));
  const lines = [markTimes(mark), ...mark.rows.map(([k, v]) => `${k}: ${v}`)];
  const severity = mark.tone === "crit" ? "critical" : mark.tone === "major" ? "major" : mark.tone === "minor" ? "minor" : "";
  const cls = [
    "mk",
    `t-${mark.tone}`,
    selected && "is-selected",
    outlined && "is-hl",
    continues && "is-open",
    before && "is-before",
    isTick && "is-tick",
  ]
    .filter(Boolean)
    .join(" ");
  const inner = (
    <>
      {before ? <span className="mk-edge" style={{ left: shapeLeft }} aria-hidden /> : null}
      <span className="mk-shape" style={{ left: shapeLeft + edge, width: isTick ? 7 : Math.max(6, barW - edge) }} />
      <span className="mk-label" style={{ left: Math.max(0, Math.min(shapeLeft, cell - labelW)), maxWidth: Math.ceil(mark.label.length * 6.3) + 4 > labelW ? labelW : undefined }}>
        {mark.label}
      </span>
    </>
  );
  const style = { left, top: LANE_PAD + row * rowH, width: cell, height: rowH - 4 } as CSSProperties;
  if (inert) {
    return (
      <div className={cls} style={style}>
        {inner}
      </div>
    );
  }
  return (
    <button
      type="button"
      className={cls}
      style={style}
      aria-pressed={selected}
      aria-label={`${mark.kindLabel}: ${mark.label}. ${markTimes(mark)}${severity ? `. Severity ${severity}` : ""}.`}
      onClick={() => onSelect(selected ? null : mark.id)}
      onMouseEnter={(e) => showTip(e.currentTarget, mark.label, lines)}
      onMouseLeave={hideTip}
      onFocus={(e) => showTip(e.currentTarget, mark.label, lines)}
      onBlur={hideTip}
    >
      {inner}
    </button>
  );
}

const PLOT_H = 44;

function KpiLine({ row, index, x, width, selectedId, onSelect, highlightRefs, inert, showTip, hideTip }: LaneProps & { row: KpiRow; index: number }) {
  const { series } = row;
  const startMs = isoToMs(series.start);
  const start = startMs ?? 0;
  const step = series.step_minutes * 60_000;
  const finite = [...series.values, ...series.baseline].filter((v): v is number => typeof v === "number" && Number.isFinite(v));
  const hasValues = startMs !== null && series.values.some((v) => typeof v === "number" && Number.isFinite(v));
  const min = Math.min(...finite);
  const max = Math.max(...finite);
  const room = (max - min || Math.abs(max) || 1) * 0.1;
  const lo = min - room;
  const span = max + room - lo;
  const y = (v: number) => PLOT_H - ((v - lo) / span) * PLOT_H;
  const line = (vals: Array<number | null>) => {
    let d = "";
    let pen = false;
    vals.forEach((v, i) => {
      if (typeof v !== "number" || !Number.isFinite(v)) {
        pen = false;
        return;
      }
      d += `${pen ? "L" : "M"}${x(start + i * step).toFixed(1)} ${y(v).toFixed(1)}`;
      pen = true;
    });
    return d;
  };
  const dev = series.deviation;
  const devA = dev && hasValues ? isoToMs(dev.onset) : null;
  const devB = dev && hasValues ? (dev.recovery ? isoToMs(dev.recovery) : start + (series.values.length - 1) * step) : null;
  const selected = selectedId === row.id;
  const caption = chartCaption(series, row.deviationPct);
  const outlined = highlightRefs.has(row.origin);
  const pctShown = row.deviationPct !== undefined ? pctText(row.deviationPct) : "";
  const pct = !hasValues ? "no data in this window" : !series.baseline_available ? "no baseline" : pctShown ? `${pctShown} vs usual` : "";
  const className = `kp${selected ? " is-selected" : ""}${outlined ? " is-hl" : ""}`;
  const style = { top: LANE_PAD + index * KPI_ROW, height: KPI_ROW - 2 };
  const inner = (
    <>
      <span className="kp-title">
        <span className="kp-name">{row.title}</span>
        {pct ? <em>{pct}</em> : null}
      </span>
      <svg width={width} height={PLOT_H} viewBox={`0 0 ${width} ${PLOT_H}`} aria-hidden>
        {devA !== null && devB !== null ? <rect className="kp-dev" x={x(devA)} y={0} width={Math.max(2, x(devB) - x(devA))} height={PLOT_H} /> : null}
        {series.baseline_available && hasValues ? <path className="kp-base" d={line(series.baseline)} /> : null}
        {hasValues ? <path className="kp-line" d={line(series.values)} /> : null}
      </svg>
    </>
  );
  if (inert) {
    return (
      <div className={className} style={style}>
        {inner}
      </div>
    );
  }
  return (
    <button
      type="button"
      className={className}
      style={style}
      aria-pressed={selected}
      aria-label={`${row.title}. ${hasValues ? caption : "There is no data in this window."}`}
      onClick={() => onSelect(selected ? null : row.id)}
      onMouseEnter={(e) => showTip(e.currentTarget, row.title, [hasValues ? caption : "There is no data in this window."])}
      onMouseLeave={hideTip}
      onFocus={(e) => showTip(e.currentTarget, row.title, [hasValues ? caption : "There is no data in this window."])}
      onBlur={hideTip}
    >
      {inner}
    </button>
  );
}
