import type { RowBar } from "./bars";

/** A proportional bar from 0 to 100%, with the 95% interval as a bracket underneath when the note gives one. */
export function ResultBar({ bar }: { bar: RowBar }) {
  const share = (bar.k / bar.n) * 100;
  const interval = bar.interval;
  return (
    <svg className="hw-bar" aria-hidden focusable="false" width="100%" height="22">
      <rect className="hw-bar-track" x="0" y="0" width="100%" height="9" />
      <rect className="hw-bar-fill" x="0" y="0" width={`${share}%`} height="9" />
      {interval ? (
        <g className="hw-bar-ci">
          <line x1={`${interval.low}%`} x2={`${interval.high}%`} y1="15" y2="15" />
          <line x1={`${interval.low}%`} x2={`${interval.low}%`} y1="10" y2="20" />
          <line x1={`${interval.high}%`} x2={`${interval.high}%`} y1="10" y2="20" />
        </g>
      ) : null}
    </svg>
  );
}
