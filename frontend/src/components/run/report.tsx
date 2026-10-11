"use client";

import { ArrowRight } from "lucide-react";
import { Fragment, type ReactNode } from "react";
import { Badge, toneText } from "@/components/ui/badge";
import { Notice } from "@/components/ui/notice";
import { RichText } from "@/components/ui/rich-text";
import { Define } from "@/components/ui/term";
import { cx } from "@/lib/cx";
import { durationBetween, fmtLocal, fmtNumber, localClock, localDay } from "@/lib/format";
import { isPartialReport, type RunView } from "@/lib/investigation";
import { BASIS, CATEGORIES, CLASSIFICATIONS, CONFIDENCE, VERDICTS, categoryLabel, nodeKind } from "@/lib/labels";
import type { Report } from "@/lib/types";
import { CiteList } from "./cite";

export function ReportView({ view, animate }: { view: RunView; animate: boolean }) {
  const report = view.report;
  if (!report) return null;
  const partial = isPartialReport(view);
  const issues = view.issues;

  return (
    <article aria-labelledby="report-title" className={cx("space-y-8", animate && "report-enter")}>
      {partial ? (
        <Notice tone="warn" title="This report is incomplete" role="status">
          The investigation did not finish normally, so what follows is a placeholder with whatever was gathered. Treat it as a lead, not a conclusion.
        </Notice>
      ) : null}
      {issues.length > 0 ? (
        <Notice tone="warn" title={`The citation check found ${issues.length === 1 ? "a problem" : `${issues.length} problems`} in this report`}>
          <ul className="mt-1 list-disc space-y-0.5 pl-4">
            {issues.map((issue, i) => (
              <li key={i}>{issue}</li>
            ))}
          </ul>
        </Notice>
      ) : null}

      <Verdict report={report} />

      {report.timeline.length > 0 ? (
        <Section title="Timeline" note="Times are Africa/Tunis">
          <ol className="space-y-3">
            {report.timeline.map((entry, i) => {
              const day = localDay(entry.time);
              const prevDay = i > 0 ? localDay(report.timeline[i - 1].time) : null;
              return (
                <li key={i} className="grid grid-cols-[4.25rem_1fr] gap-x-3 sm:grid-cols-[5.5rem_1fr]">
                  <div className="font-mono text-[13px] leading-6">
                    <div>{localClock(entry.time)}</div>
                    {day && day !== prevDay ? <div className="text-[11px] leading-4 text-muted">{day}</div> : null}
                  </div>
                  <div className="min-w-0">
                    <p className="text-sm leading-6 break-anywhere">
                      <RichText text={entry.event} />
                    </p>
                    <div className="mt-1">
                      <CiteList refs={entry.refs} compact />
                    </div>
                  </div>
                </li>
              );
            })}
          </ol>
        </Section>
      ) : null}

      {report.findings.length > 0 ? (
        <Section title="Findings" note="Observed means a cited result shows it. Inferred is the agent's reasoning from the evidence.">
          <ul className="space-y-4">
            {report.findings.map((f, i) => (
              <li key={i} className="grid grid-cols-[5.5rem_1fr] items-start gap-x-3">
                <span className="mt-0.5">
                  <Define term={BASIS[f.basis]} className="no-underline">
                    <Badge tone={f.basis === "observed" ? "ok" : "neutral"} className={f.basis === "inferred" ? "border border-dashed border-line-strong" : ""}>
                      {BASIS[f.basis].label}
                    </Badge>
                  </Define>
                </span>
                <div className="min-w-0">
                  <p className="text-sm leading-6 break-anywhere">
                    <RichText text={f.claim} />
                  </p>
                  <div className="mt-1">
                    <CiteList refs={f.refs} compact />
                  </div>
                </div>
              </li>
            ))}
          </ul>
        </Section>
      ) : null}

      {report.hypotheses.length > 0 ? (
        <Section title="Explanations considered" note="Most likely first">
          <ul className="space-y-3">
            {report.hypotheses.map((h, i) => {
              const verdict = VERDICTS[h.verdict] ?? VERDICTS.unresolved;
              return (
                <li key={i} className="rounded-xl border border-line bg-surface p-3.5">
                  <div className="flex flex-wrap items-center gap-2">
                    <Define term={verdict} className="no-underline">
                      <Badge tone={verdict.tone}>{verdict.label}</Badge>
                    </Define>
                    <Define term={CATEGORIES[h.category] ?? { label: h.category, definition: "" }}>
                      <span className="text-sm font-medium">{categoryLabel(h.category)}</span>
                    </Define>
                    {h.node_id ? <NodeChip id={h.node_id} /> : null}
                  </div>
                  <p className="mt-2 text-sm leading-6 text-muted break-anywhere">
                    <RichText text={h.reason} />
                  </p>
                  <div className="mt-2">
                    <CiteList refs={h.refs} compact />
                  </div>
                </li>
              );
            })}
          </ul>
        </Section>
      ) : null}

      {report.dismissed_signals.length > 0 ? (
        <Section title="Signals ruled out" note="Things that looked relevant and were set aside, with the reason">
          <ul className="space-y-3">
            {report.dismissed_signals.map((d, i) => (
              <li key={i} className="grid grid-cols-[minmax(0,8.5rem)_1fr] items-start gap-x-3 sm:grid-cols-[9.5rem_1fr]">
                <CiteList refs={[d.ref]} compact />
                <p className="text-sm leading-6 text-muted break-anywhere">
                  <RichText text={d.reason} />
                </p>
              </li>
            ))}
          </ul>
        </Section>
      ) : null}

      {report.recommended_actions.length > 0 ? (
        <Section title="Recommended actions">
          <ol className="space-y-2">
            {report.recommended_actions.map((a, i) => (
              <li key={i} className="grid grid-cols-[1.5rem_1fr] text-sm leading-6">
                <span className="font-mono text-muted">{i + 1}.</span>
                <span className="break-anywhere">
                  <RichText text={a} />
                </span>
              </li>
            ))}
          </ol>
        </Section>
      ) : null}
    </article>
  );
}

function Section({ title, note, children }: { title: string; note?: string; children: ReactNode }) {
  return (
    <section aria-label={title}>
      <h3 className="text-lg font-semibold tracking-tight">{title}</h3>
      {note ? <p className="mb-3 mt-0.5 text-xs text-muted">{note}</p> : <div className="mb-3" />}
      {children}
    </section>
  );
}

function NodeChip({ id }: { id: string }) {
  const kind = nodeKind(id);
  const chip = <span className="inline-block rounded-md bg-surface-2 px-1.5 py-0.5 font-mono text-[13px] break-anywhere">{id}</span>;
  return kind ? (
    <Define term={{ label: id, definition: kind }} className="no-underline">
      {chip}
    </Define>
  ) : (
    chip
  );
}

function Verdict({ report }: { report: Report }) {
  const verdict = CLASSIFICATIONS[report.classification];
  const conf = CONFIDENCE[report.confidence];
  const duration = durationBetween(report.impact_start, report.impact_end);
  const category = CATEGORIES[report.root_cause_category];
  const nodes = report.affected_node_ids;
  const shownNodes = nodes.length > 10 ? nodes.slice(0, 10) : nodes;

  return (
    <header className="space-y-4">
      <div className="flex flex-wrap items-center gap-2">
        <Define term={verdict} className="no-underline">
          <Badge tone={verdict.tone} className="px-2 py-1 text-[13px]">
            {verdict.label}
          </Badge>
        </Define>
        <span className="text-sm text-muted">{verdict.sentence}</span>
      </div>
      <h2 id="report-title" className="text-balance text-2xl font-semibold leading-8 tracking-tight break-anywhere">
        {report.title}
      </h2>
      <p className="max-w-[70ch] text-[15px] leading-7 break-anywhere">
        <RichText text={report.root_cause_summary} />
      </p>

      <dl className="grid gap-x-8 gap-y-4 rounded-xl border border-line bg-surface p-4 sm:grid-cols-2">
        <Fact label="Root cause">
          <div className="flex flex-wrap items-center gap-2">
            {category ? (
              <Define term={category}>
                <span className="font-medium">{categoryLabel(report.root_cause_category)}</span>
              </Define>
            ) : (
              <span className="font-medium">{categoryLabel(report.root_cause_category)}</span>
            )}
            {report.root_cause_node_id ? (
              <>
                <span aria-hidden className="text-muted">
                  at
                </span>
                <NodeChip id={report.root_cause_node_id} />
              </>
            ) : null}
          </div>
          {report.root_cause_time ? <p className="mt-1 text-xs text-muted">Began {fmtLocal(report.root_cause_time)}</p> : null}
        </Fact>
        <Fact label="Impact window">
          {report.impact_start ? (
            <p className="flex flex-wrap items-center gap-x-2 text-sm">
              <span className="font-mono text-[13px]">{fmtLocal(report.impact_start)}</span>
              <ArrowRight aria-hidden className="size-3.5 text-muted" />
              <span className="font-mono text-[13px]">{report.impact_end ? fmtLocal(report.impact_end) : "not over or unknown"}</span>
            </p>
          ) : (
            <p className="text-sm text-muted">No impact window established</p>
          )}
          <p className="mt-1 text-xs text-muted">{duration ? `${duration} · ` : ""}Africa/Tunis time</p>
        </Fact>
        <Fact label="Confidence" wide>
          <div className="flex items-center gap-2.5">
            <Define term={conf} className="no-underline">
              <span className="flex items-center gap-2">
                <span role="img" aria-label={`${conf.level} of 3`} className="flex gap-0.5">
                  {[1, 2, 3].map((n) => (
                    <span
                      key={n}
                      className={cx("h-3 w-1.5 rounded-sm", n <= conf.level ? { ok: "bg-ok", warn: "bg-warn", danger: "bg-danger", neutral: "bg-muted", event: "bg-event" }[conf.tone] : "bg-line-strong")}
                    />
                  ))}
                </span>
                <span className={cx("text-sm font-medium", toneText[conf.tone])}>{conf.label}</span>
              </span>
            </Define>
          </div>
          <p className="mt-1.5 max-w-[70ch] text-sm leading-6 text-muted break-anywhere">
            <RichText text={report.confidence_reason} />
          </p>
        </Fact>
        {report.impact_summary ? (
          <Fact label="Impact" wide>
            <p className="max-w-[70ch] text-sm leading-6 break-anywhere">
              <RichText text={report.impact_summary} />
            </p>
          </Fact>
        ) : null}
        {nodes.length > 0 ? (
          <Fact label={`Affected (${nodes.length})`} wide>
            <div className="flex flex-wrap gap-1.5">
              {shownNodes.map((id) => (
                <Fragment key={id}>
                  <NodeChip id={id} />
                </Fragment>
              ))}
              {nodes.length > shownNodes.length ? <span className="text-xs text-muted">+{nodes.length - shownNodes.length} more</span> : null}
            </div>
          </Fact>
        ) : null}
      </dl>
    </header>
  );
}

function Fact({ label, children, wide }: { label: string; children: ReactNode; wide?: boolean }) {
  return (
    <div className={cx("min-w-0", wide && "sm:col-span-2")}>
      <dt className="mb-1 text-[11px] font-semibold uppercase tracking-wider text-muted">{label}</dt>
      <dd>{children}</dd>
    </div>
  );
}

/** Model calls, tool calls, tokens, seconds and model: the cost of the run in one line. */
export function CostLine({ view }: { view: RunView }) {
  const f = view.finished;
  if (!f) return null;
  const u = f.usage;
  const models = f.models_used.map((m) => m.split(":").slice(1).join(":") || m);
  const items = [
    `${u.llm_calls} model call${u.llm_calls === 1 ? "" : "s"}`,
    `${u.tool_calls} tool call${u.tool_calls === 1 ? "" : "s"}`,
    `${fmtNumber(u.input_tokens)} in / ${fmtNumber(u.output_tokens)} out tokens`,
    `${u.wall_seconds.toFixed(1)} s`,
  ];
  if (models.length) items.push(models.join(", "));
  if (f.fell_back) items.push("a fallback model answered some steps");
  return (
    <p className="flex flex-wrap gap-x-3 gap-y-1 font-mono text-xs text-muted">
      {items.map((item, i) => (
        <span key={i} className="whitespace-nowrap">
          {item}
        </span>
      ))}
    </p>
  );
}
