"use client";

import { ArrowRight, CalendarDays, Check, CircleCheck, CircleHelp, Minus, OctagonAlert, Wrench } from "lucide-react";
import type { ReactNode } from "react";
import { Notice } from "@/components/ui/notice";
import { RichText } from "@/components/ui/rich-text";
import { Define } from "@/components/ui/term";
import { durationBetween, fmtLocal, fmtNumber, localClock, localDay, plural } from "@/lib/format";
import { isPartialReport, type RunView } from "@/lib/investigation";
import { BASIS, CATEGORIES, CLASSIFICATIONS, CONFIDENCE, VERDICTS, categoryLabel, nodeKind } from "@/lib/labels";
import type { Classification } from "@/lib/types";
import { CiteList } from "./citations";
import { NodeChip } from "./node-chip";

const VERDICT_ICON: Record<Classification, ReactNode> = {
  incident: <OctagonAlert aria-hidden size={18} strokeWidth={2} />,
  planned_maintenance: <Wrench aria-hidden size={18} strokeWidth={2} />,
  expected_event: <CalendarDays aria-hidden size={18} strokeWidth={2} />,
  no_impact: <CircleCheck aria-hidden size={18} strokeWidth={2} />,
  inconclusive: <CircleHelp aria-hidden size={18} strokeWidth={2} />,
};

const NODE_LIMIT = 12;

interface ReportProps {
  view: RunView;
  hoverPin: number | null;
  onHoverPin(n: number | null): void;
}

export function ReportView({ view, hoverPin, onHoverPin }: ReportProps) {
  const report = view.report;
  if (!report) return null;
  const verdict = CLASSIFICATIONS[report.classification] ?? CLASSIFICATIONS.inconclusive;
  const conf = CONFIDENCE[report.confidence];
  const category = CATEGORIES[report.root_cause_category];
  const duration = durationBetween(report.impact_start, report.impact_end);
  const nodes = report.affected_node_ids;

  return (
    <article className="rp" aria-labelledby="run-report-title">
      {isPartialReport(view) ? (
        <Notice tone="warn" title="This report is incomplete" role="status" className="rp-notice">
          The investigation did not finish, so what is shown is a placeholder built from what was gathered. Treat it as a lead, not a conclusion.
        </Notice>
      ) : null}

      <header className="rp-head">
        <p className="rp-verdict">
          <Define term={verdict}>
            <span className="rp-verdict-name">
              {VERDICT_ICON[report.classification]} {verdict.label}
            </span>
          </Define>
          <span>{verdict.sentence}</span>
        </p>
        <h2 id="run-report-title" className={report.title.length > 90 ? "is-long" : undefined}>
          {report.title}
        </h2>
        <p className="rp-summary">
          <RichText text={report.root_cause_summary} />
        </p>
      </header>

      <dl className="rp-facts">
        <div>
          <dt>Cause</dt>
          <dd>
            {category ? (
              <Define term={category}>
                <strong>{categoryLabel(report.root_cause_category)}</strong>
              </Define>
            ) : (
              <strong>{categoryLabel(report.root_cause_category)}</strong>
            )}
          </dd>
        </div>
        <div>
          <dt>Where</dt>
          <dd>
            {report.root_cause_node_id ? (
              <>
                <NodeChip id={report.root_cause_node_id} />
                {nodeKind(report.root_cause_node_id) ? <span className="muted"> · {nodeKind(report.root_cause_node_id)}</span> : null}
              </>
            ) : (
              <span className="muted">Not established</span>
            )}
          </dd>
        </div>
        <div>
          <dt>When</dt>
          <dd>
            {report.impact_start ? (
              <>
                <span className="mono">{fmtLocal(report.impact_start)}</span> <ArrowRight aria-hidden size={13} className="inline-icon" />{" "}
                <span className="mono">{report.impact_end ? fmtLocal(report.impact_end) : "not over or unknown"}</span>
                <span className="muted">
                  {" "}
                  · {duration ? `${duration}, ` : ""}Africa/Tunis
                </span>
              </>
            ) : (
              <span className="muted">No impact window established</span>
            )}
          </dd>
        </div>
        <div>
          <dt>Confidence</dt>
          <dd>
            <Define term={conf}>
              <span className="conf">
                <span className="conf-steps" role="img" aria-label={`${conf.level} of 3`}>
                  {[1, 2, 3].map((n) => (
                    <i key={n} className={n <= conf.level ? "on" : ""} />
                  ))}
                </span>
                <strong>{conf.label}</strong>
              </span>
            </Define>
          </dd>
        </div>
      </dl>
      <p className="rp-reason">
        <RichText text={report.confidence_reason} />
      </p>

      {report.impact_summary || nodes.length > 0 ? (
        <section className="rp-sec" aria-labelledby="run-impact-title">
          <h3 id="run-impact-title">Impact</h3>
          {report.impact_summary ? (
            <p>
              <RichText text={report.impact_summary} />
            </p>
          ) : null}
          {nodes.length > 0 ? (
            <p className="rp-nodes">
              <span className="muted">Affected ({nodes.length}):</span>{" "}
              {nodes.slice(0, NODE_LIMIT).map((n) => (
                <NodeChip key={n} id={n} />
              ))}
              {nodes.length > NODE_LIMIT ? <span className="muted"> and {nodes.length - NODE_LIMIT} more</span> : null}
            </p>
          ) : null}
        </section>
      ) : null}

      {report.timeline.length > 0 ? (
        <section className="rp-sec" aria-labelledby="run-timeline-title">
          <h3 id="run-timeline-title">Timeline</h3>
          <p className="rp-note">The numbers match the pins under the board. Times are Africa/Tunis.</p>
          <ol className="rp-timeline">
            {report.timeline.map((t, i) => {
              const day = localDay(t.time);
              const prev = i > 0 ? localDay(report.timeline[i - 1].time) : null;
              return (
                <li
                  key={i}
                  id={`run-timeline-${i + 1}`}
                  className={hoverPin === i + 1 ? "is-on" : undefined}
                  onMouseEnter={() => onHoverPin(i + 1)}
                  onMouseLeave={() => onHoverPin(null)}
                  onFocus={() => onHoverPin(i + 1)}
                  onBlur={() => onHoverPin(null)}
                >
                  <span className="rp-pin">{i + 1}</span>
                  <span className="rp-time mono">
                    {localClock(t.time)}
                    {day && day !== prev ? <small>{day}</small> : null}
                  </span>
                  <span className="rp-ev">
                    <RichText text={t.event} />
                    <CiteList refs={t.refs} />
                  </span>
                </li>
              );
            })}
          </ol>
        </section>
      ) : null}

      {report.findings.length > 0 ? (
        <section className="rp-sec" aria-labelledby="run-findings-title">
          <h3 id="run-findings-title">Findings</h3>
          <p className="rp-note">Observed means a cited result shows it directly. Inferred is the agent’s reasoning from the evidence.</p>
          <ul className="rp-list">
            {report.findings.map((f, i) => {
              const basis = BASIS[f.basis] ?? BASIS.inferred;
              return (
                <li key={i}>
                  <Define term={basis}>
                    <span className={`basis is-${f.basis}`}>{basis.label}</span>
                  </Define>
                  <span>
                    <RichText text={f.claim} />
                    <CiteList refs={f.refs} />
                  </span>
                </li>
              );
            })}
          </ul>
        </section>
      ) : null}

      {report.hypotheses.length > 0 ? (
        <section className="rp-sec" aria-labelledby="run-hypotheses-title">
          <h3 id="run-hypotheses-title">Explanations considered</h3>
          <ul className="rp-list">
            {report.hypotheses.map((h, i) => {
              const v = VERDICTS[h.verdict] ?? VERDICTS.unresolved;
              const icon =
                h.verdict === "confirmed" ? (
                  <Check aria-hidden size={14} strokeWidth={2.5} />
                ) : h.verdict === "rejected" ? (
                  <Minus aria-hidden size={14} strokeWidth={2.5} />
                ) : (
                  <CircleHelp aria-hidden size={14} strokeWidth={2.25} />
                );
              return (
                <li key={i}>
                  <Define term={v}>
                    <span className={`verdict is-${h.verdict}`}>
                      {icon} {v.label}
                    </span>
                  </Define>
                  <span>
                    <strong>{categoryLabel(h.category)}</strong>
                    {h.node_id ? (
                      <>
                        {" at "}
                        <NodeChip id={h.node_id} />
                      </>
                    ) : null}
                    <br />
                    <RichText text={h.reason} />
                    <CiteList refs={h.refs} />
                  </span>
                </li>
              );
            })}
          </ul>
        </section>
      ) : null}

      {report.dismissed_signals.length > 0 ? (
        <section className="rp-sec" aria-labelledby="run-ruled-out-title">
          <h3 id="run-ruled-out-title">Signals ruled out</h3>
          <ul className="rp-list is-out">
            {report.dismissed_signals.map((d, i) => (
              <li key={i}>
                <CiteList refs={[d.ref]} />
                <span>
                  <RichText text={d.reason} />
                </span>
              </li>
            ))}
          </ul>
        </section>
      ) : null}

      {report.recommended_actions.length > 0 ? (
        <section className="rp-sec" aria-labelledby="run-actions-title">
          <h3 id="run-actions-title">Recommended actions</h3>
          <ol className="rp-actions">
            {report.recommended_actions.map((a, i) => (
              <li key={i}>
                <RichText text={a} />
              </li>
            ))}
          </ol>
        </section>
      ) : null}

      {view.issues.length > 0 ? (
        <div className="rp-issues">
          <p>The citation check found {view.issues.length === 1 ? "a problem" : `${view.issues.length} problems`} in this report.</p>
          <ul>
            {view.issues.map((issue, i) => (
              <li key={i}>{issue}</li>
            ))}
          </ul>
        </div>
      ) : null}

      <CostLine view={view} />
    </article>
  );
}

/** Model calls, tool calls, tokens, seconds and model: the cost of the run in one line. */
function CostLine({ view }: { view: RunView }) {
  const f = view.finished;
  if (!f) return null;
  const u = f.usage;
  const models = f.models_used.map((m) => m.split(":").slice(1).join(":") || m);
  const items = [
    plural(u.llm_calls, "model call"),
    plural(u.tool_calls, "tool call"),
    `${fmtNumber(u.input_tokens)} in / ${fmtNumber(u.output_tokens)} out tokens`,
    `${u.wall_seconds.toFixed(1)} s`,
  ];
  if (models.length) items.push(models.join(", "));
  if (f.fell_back) items.push("a fallback model answered some steps");
  return (
    <p className="rp-cost" aria-label="Cost of this investigation">
      {items.map((it, i) => (
        <span key={i}>{it}</span>
      ))}
    </p>
  );
}
