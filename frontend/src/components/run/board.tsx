"use client";

import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { LANES, makeTicks, spanText, type BoardModel, type LaneId } from "@/lib/board";
import "./board.css";
import { Strip, Conclusion } from "./board-conclusion";
import { LaneView } from "./board-lane";
import { Legend } from "./board-legend";

interface Tip {
  x: number;
  y: number;
  below: boolean;
  title: string;
  lines: string[];
}

export interface BoardProps {
  model: BoardModel;
  /** Switches the board motion on: marks grow in, the checking sweep runs, the conclusion wipes in. */
  animate?: boolean;
  /** A display-only board: marks, KPI rows and pins cannot be focused or clicked and show no tooltip. */
  inert?: boolean;
  selectedId?: string | null;
  onSelect?(id: string | null): void;
  /** References whose marks are outlined, for example the one open in a citation. */
  highlightRefs?: ReadonlySet<string>;
  hoverLanes?: readonly LaneId[];
  hoverPin?: number | null;
  onHoverPin?(n: number | null): void;
  /** Rows under the board for sources that have no time dimension. */
  children?: ReactNode;
}

/** A tick label closer than this to either end would be cut off by the axis. */
const TICK_EDGE = 20;
const NO_REFS: ReadonlySet<string> = new Set();
const NO_LANES: readonly LaneId[] = [];
const noop = () => {};

function useWidth<T extends HTMLElement>(): [React.RefObject<T | null>, number] {
  const ref = useRef<T | null>(null);
  const [w, setW] = useState(760);
  useLayoutEffect(() => {
    const el = ref.current;
    if (!el) return;
    const measure = () => setW(Math.max(200, Math.round(el.getBoundingClientRect().width)));
    measure();
    const ro = new ResizeObserver(measure);
    ro.observe(el);
    return () => ro.disconnect();
  }, []);
  return [ref, w];
}

/** One time axis with a lane per evidence source; each lane fills in as the agent checks it. */
export function Board({
  model,
  animate = true,
  inert = false,
  selectedId = null,
  onSelect = noop,
  highlightRefs = NO_REFS,
  hoverLanes = NO_LANES,
  hoverPin = null,
  onHoverPin = noop,
  children,
}: BoardProps) {
  const [axisRef, width] = useWidth<HTMLDivElement>();
  const rootRef = useRef<HTMLElement | null>(null);
  const [tip, setTip] = useState<Tip | null>(null);
  const [kpiExpanded, setKpiExpanded] = useState(false);
  const domain = model.domain;
  const narrow = width < 520;

  const x = useCallback((ms: number) => (domain ? ((ms - domain.a) / (domain.b - domain.a)) * width : 0), [domain, width]);
  const ticks = useMemo(() => (domain ? makeTicks(domain, width, narrow ? 52 : 70) : []), [domain, width, narrow]);

  const showTip = useCallback((el: HTMLElement, title: string, lines: string[]) => {
    const root = rootRef.current;
    if (!root) return;
    const r = el.getBoundingClientRect();
    const c = root.getBoundingClientRect();
    const below = r.top - c.top < 130;
    const half = Math.min(150, Math.max(60, c.width / 2 - 8));
    const cx = Math.min(Math.max(r.left - c.left + Math.min(r.width, 160) / 2, half), c.width - half);
    setTip({
      x: cx,
      y: below ? r.bottom - c.top + 6 : r.top - c.top - 6,
      below,
      title,
      lines,
    });
  }, []);
  const hideTip = useCallback(() => setTip(null), []);

  useEffect(() => {
    if (!tip) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setTip(null);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [tip]);

  const conclusion = !!(model.impact || model.cause || model.pins.length > 0);
  const refDay = model.scope?.a ?? null;
  const summary = useMemo(() => describeBoard(model), [model]);

  return (
    <figure
      ref={rootRef}
      className="bd"
      data-verdict={model.verdict ?? undefined}
      data-animate={animate ? "" : undefined}
      data-narrow={narrow ? "" : undefined}
    >
      <figcaption className="sr-only">{summary}</figcaption>
      <div className="bd-lanes">
        {LANES.map((def) => {
          const lane = model.lanes.find((l) => l.def.id === def.id)!;
          return (
            <LaneView
              key={def.id}
              lane={lane}
              model={model}
              domain={domain}
              width={width}
              x={x}
              ticks={ticks}
              selectedId={selectedId}
              onSelect={onSelect}
              highlightRefs={highlightRefs}
              hover={hoverLanes.includes(def.id)}
              missing={!model.cause && model.missing.has(def.id)}
              refDay={refDay}
              showTip={showTip}
              hideTip={hideTip}
              conclusion={conclusion}
              inert={inert}
              kpiExpanded={kpiExpanded}
              onToggleKpis={() => setKpiExpanded((v) => !v)}
            />
          );
        })}
      </div>

      <div className="bd-axis">
        <div className="bd-axis-label">Africa/Tunis time</div>
        <div className="bd-axis-track" ref={axisRef}>
          {ticks
            .filter((t) => x(t.ms) >= TICK_EDGE && x(t.ms) <= width - TICK_EDGE)
            .map((t) => (
              <span key={t.ms} className="tk" style={{ left: x(t.ms) }}>
                <span className="tk-time">{t.label}</span>
                {t.date ? <span className="tk-date">{t.date}</span> : null}
              </span>
            ))}
          {conclusion ? <Conclusion model={model} x={x} width={width} part="axis" /> : null}
        </div>
      </div>

      {conclusion ? (
        <Strip model={model} x={x} width={width} hoverPin={hoverPin} onHoverPin={onHoverPin} inert={inert} showTip={showTip} hideTip={hideTip} />
      ) : null}

      <Legend model={model} hasConclusion={conclusion} />
      {children}

      {tip ? (
        <div className="bd-tip" role="tooltip" data-below={tip.below ? "" : undefined} style={{ left: tip.x, top: tip.y }}>
          <strong>{tip.title}</strong>
          {tip.lines.map((l, i) => (
            <span key={i}>{l}</span>
          ))}
        </div>
      ) : null}
      {refDay === null ? <p className="bd-wait">The time axis is set once the agent has read the question.</p> : null}
    </figure>
  );
}

/** The text alternative: what each lane holds, and the impact window once there is one. */
function describeBoard(model: BoardModel): string {
  const parts = model.lanes.map((l) => {
    if (l.state === "idle") return `${l.def.label}: not checked yet.`;
    if (l.state === "checking") return `${l.def.label}: being checked.`;
    if (l.state === "clear") return `${l.def.label}: checked, nothing found.`;
    const n = l.marks.length + l.kpis.length;
    const names =
      l.marks
        .slice(0, 3)
        .map((m) => m.label)
        .join("; ") ||
      l.kpis
        .slice(0, 3)
        .map((k) => k.title)
        .join("; ");
    return `${l.def.label}: ${n} found${names ? `, for example ${names}` : ""}.`;
  });
  const tail = model.impact ? ` Impact shaded from ${spanText(model.impact, null).replace(" and ", " to ")}.` : "";
  return `Evidence board over time, Africa/Tunis. ${parts.join(" ")}${tail}`;
}
