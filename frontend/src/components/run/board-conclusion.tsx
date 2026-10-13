"use client";

import { useMemo } from "react";
import { layoutPins, PIN_SIZE, type BoardModel } from "@/lib/board";
import { fmtLocal } from "@/lib/format";
import { plainText } from "@/lib/steps";
import { scrollBehavior } from "./motion";
import { useCoarsePointer } from "./use-coarse";

/** The impact band behind the lanes and the line at the cause. */
export function Conclusion({ model, x, width, part }: { model: BoardModel; x(ms: number): number; width: number; part: "lane" | "axis" }) {
  const { impact, cause } = model;
  const bandA = impact ? Math.max(0, x(impact.a)) : 0;
  const bandB = impact ? Math.min(width, x(impact.b)) : 0;
  return (
    <>
      {impact && bandB > bandA ? <i className="cc-band" style={{ left: bandA, width: Math.max(2, bandB - bandA) }} aria-hidden /> : null}
      {cause && part === "lane" ? <i className="cc-line" style={{ left: x(cause.ms) }} aria-hidden /> : null}
    </>
  );
}

const PIN_ROW = 24;
interface StripProps {
  model: BoardModel;
  x(ms: number): number;
  width: number;
  hoverPin: number | null;
  onHoverPin(n: number | null): void;
  showTip(el: HTMLElement, title: string, lines: string[]): void;
  hideTip(): void;
  inert?: boolean;
}

/** Under the axis: the timeline's numbered pins, and the flag naming the cause. */
export function Strip({ model, x, width, hoverPin, onHoverPin, showTip, hideTip, inert = false }: StripProps) {
  const coarse = useCoarsePointer();
  const { placed, hidden, rows } = useMemo(() => layoutPins(model.pins, x, width, coarse ? 8 : 2), [model.pins, x, width, coarse]);
  const cause = model.cause;
  const flagTop = 14 + rows * PIN_ROW + 2;
  const trackH = flagTop + (cause ? 24 : 8) + (width < 520 && cause ? 18 : 0) + (hidden ? 20 : 0);
  const causeX = cause ? x(cause.ms) : 0;
  const flip = causeX > width * 0.55;

  const goToRow = (n: number) => {
    const row = document.getElementById(`run-timeline-${n}`);
    if (!row) return;
    row.scrollIntoView({ block: "center", behavior: scrollBehavior() });
  };

  return (
    <div className="bd-strip">
      <div className="bd-strip-label">{model.pins.length ? "Report timeline" : ""}</div>
      <div className="bd-strip-track" style={{ height: trackH }}>
        {placed.length ? (
          <svg className="pin-leaders" width={width} height={30} aria-hidden>
            {placed
              .filter((p) => p.row === 0)
              .map(({ pin, at, px }) => (
                <path key={pin.n} className={hoverPin === pin.n ? "is-on" : ""} d={`M${at.toFixed(1)} 0V6L${px.toFixed(1)} 14`} />
              ))}
          </svg>
        ) : null}
        {placed.map(({ pin, px, row }) => {
          const lines = [fmtLocal(pin.time), ...(pin.refs.length ? [`Evidence: ${pin.refs.join(", ")}`] : [])];
          const title = `${pin.n}. ${plainText(pin.event)}`;
          const on = () => {
            onHoverPin(pin.n);
          };
          const off = () => {
            onHoverPin(null);
            hideTip();
          };
          const className = `pin${hoverPin === pin.n ? " is-on" : ""}`;
          const style = { left: px - PIN_SIZE / 2, top: 14 + row * PIN_ROW };
          if (inert) {
            return (
              <span key={pin.n} className={className} style={style}>
                {pin.n}
              </span>
            );
          }
          return (
            <button
              key={pin.n}
              type="button"
              className={className}
              style={style}
              aria-label={`Timeline entry ${pin.n}: ${plainText(pin.event)}`}
              onClick={() => goToRow(pin.n)}
              onMouseEnter={(e) => {
                on();
                showTip(e.currentTarget, title, lines);
              }}
              onMouseLeave={off}
              onFocus={(e) => {
                on();
                showTip(e.currentTarget, title, lines);
              }}
              onBlur={off}
            >
              {pin.n}
            </button>
          );
        })}
        {hidden ? (
          <p className="pin-more" style={{ top: trackH - 18 }}>
            and {hidden} more entries in the report timeline below
          </p>
        ) : null}
        {cause ? (
          <>
            <i className="cc-line is-strip" style={{ left: causeX, height: flagTop + 14 }} aria-hidden />
            <span
              className={`cc-flag${flip ? " is-flip" : ""}`}
              style={
                flip
                  ? { top: flagTop, right: width - causeX + 6, maxWidth: Math.max(120, causeX - 12) }
                  : { top: flagTop, left: causeX + 6, maxWidth: Math.max(120, width - causeX - 12) }
              }
            >
              {cause.label}
            </span>
          </>
        ) : null}
      </div>
    </div>
  );
}
