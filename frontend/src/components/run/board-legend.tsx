import { ArrowRight } from "lucide-react";
import type { ReactNode } from "react";
import type { BoardModel, ContextLine, Tone } from "@/lib/board";

const TONE_TEXT: Record<Tone, string> = {
  crit: "Critical alarm",
  major: "Major alarm",
  minor: "Minor alarm",
  alert: "Detector alert",
  change: "Change",
  maint: "Maintenance window",
  event: "External event",
};

const ORDER: Tone[] = ["crit", "major", "minor", "alert", "change", "maint", "event"];

export function Legend({ model, hasConclusion }: { model: BoardModel; hasConclusion: boolean }) {
  const tones = new Set<Tone>();
  for (const l of model.lanes) for (const m of l.marks) tones.add(m.tone);
  const hasKpi = model.lanes.some((l) => l.kpis.length > 0);
  if (tones.size === 0 && !hasKpi && !hasConclusion) return null;
  const item = (key: string, shape: ReactNode, text: string) => (
    <li key={key}>
      {shape}
      {text}
    </li>
  );
  return (
    <ul className="bd-legend" aria-label="How to read the marks">
      {ORDER.filter((t) => tones.has(t)).map((t) => item(t, <i className={`lg t-${t}`} aria-hidden />, TONE_TEXT[t]))}
      {hasKpi ? item("kpi", <i className="lg lg-kpi" aria-hidden />, "Measured") : null}
      {hasKpi ? item("base", <i className="lg lg-base" aria-hidden />, "Usual level") : null}
      {hasConclusion && model.impact ? item("impact", <i className="lg lg-impact" aria-hidden />, model.legend.impact) : null}
      {hasConclusion && model.cause ? item("cause", <i className="lg lg-cause" aria-hidden />, model.legend.cause) : null}
    </ul>
  );
}

/** Sources with no time dimension: topology, runbook search and SQL. */
export function ContextRows({ lines }: { lines: ContextLine[] }) {
  if (lines.length === 0) return null;
  return (
    <ul className="ctxrows" aria-label="Sources without a time dimension">
      {lines.map((l) => (
        <li key={l.id}>
          <strong>{l.label}:</strong>{" "}
          {l.chain ? (
            <span className="chain">
              {l.chain.map((id, i) => (
                <span key={`${id}-${i}`}>
                  {i > 0 ? <ArrowRight aria-hidden size={13} strokeWidth={2} /> : null}
                  <code>{id}</code>
                </span>
              ))}
            </span>
          ) : (
            <span>{l.text}</span>
          )}
        </li>
      ))}
    </ul>
  );
}
