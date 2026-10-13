"use client";

import { Crosshair, PenLine, TriangleAlert } from "lucide-react";
import { useState } from "react";
import { Notice } from "@/components/ui/notice";
import { RichText } from "@/components/ui/rich-text";
import { lanesFromPhrase, TOOL_LANE, type LaneId } from "@/lib/board";
import { argRows, argSummary, listValueLabel } from "@/lib/args";
import { dayTimeOf, fmtSeconds, plural, toMs } from "@/lib/format";
import type { RunView, Step, ToolStep } from "@/lib/investigation";
import { ARG_LABELS, EVIDENCE_KINDS, REGIONS, TOOLS, toolLabel } from "@/lib/labels";
import { joinWords, missingSentence, plainText } from "@/lib/steps";

export function stepLanes(step: Step): LaneId[] {
  if (step.kind === "tool") {
    const lane = TOOL_LANE[step.tool];
    return lane ? [lane] : [];
  }
  if (step.kind === "gate") return step.data.missing.flatMap(lanesFromPhrase);
  return [];
}

export const stepDomId = (id: string) => `run-step-${id}`;

interface FeedProps {
  view: RunView;
  flashStep: string | null;
  /** A saved run that never finished, so nothing more is coming. */
  stopped?: boolean;
  /** The step the pointer or keyboard is on, or null when it leaves. */
  onHover(stepId: string | null): void;
}

/** What the agent did, in order: the scope it read, each tool call and its result, its notes and the completeness check. */
export function Feed({ view, flashStep, stopped = false, onHover }: FeedProps) {
  const steps = view.steps.filter((s) => s.kind !== "model");
  const models = view.steps.length - steps.length;
  const tools = view.steps.filter((s) => s.kind === "tool").length;
  return (
    <section className="feed" aria-labelledby="run-feed-title">
      <h2 id="run-feed-title">What the agent did</h2>
      <p className="feed-count">
        {plural(tools, "tool call")} · {plural(models, "model call")}
      </p>
      {steps.length === 0 ? <p className="feed-wait">{stopped ? "No steps were saved for this run." : "Waiting for the agent to read the question."}</p> : null}
      <ol>
        {steps.map((step) => (
          <li
            key={step.id}
            id={stepDomId(step.id)}
            tabIndex={-1}
            className={`fe fe-${step.kind}${flashStep === step.id ? " is-flash" : ""}`}
            onMouseEnter={() => onHover(step.id)}
            onMouseLeave={() => onHover(null)}
            onFocus={() => onHover(step.id)}
            onBlur={() => onHover(null)}
          >
            <div className="fe-gutter">
              {step.kind === "tool" ? <code>{step.id}</code> : null}
              {step.kind === "note" ? <PenLine aria-hidden size={15} strokeWidth={1.75} /> : null}
              {step.kind === "scope" ? <Crosshair aria-hidden size={15} strokeWidth={1.75} /> : null}
              {step.kind === "error" ? <TriangleAlert aria-hidden size={15} strokeWidth={1.75} /> : null}
              <time>{fmtSeconds(step.tMs)}</time>
            </div>
            <div className="fe-body">
              <StepBody step={step} />
            </div>
          </li>
        ))}
      </ol>
    </section>
  );
}

function StepBody({ step }: { step: Step }) {
  switch (step.kind) {
    case "scope":
      return <ScopeBody step={step} />;
    case "tool":
      return <ToolBody step={step} />;
    case "note":
      return (
        <>
          <p className="fe-title">The agent’s note</p>
          <p className="fe-note">
            <RichText text={step.text} />
          </p>
        </>
      );
    case "gate":
      return (
        <Notice tone="neutral" title="Completeness check" className="fe-gate">
          Not yet looked at: {missingSentence(step.data.missing)}. The agent is sent back to check before it writes the report.
        </Notice>
      );
    case "error":
      return (
        <>
          <p className="fe-title">Something went wrong</p>
          <p className="fe-fail">{plainText(step.message)}</p>
          {step.where ? <p className="fe-sub">While: {step.where}</p> : null}
        </>
      );
    default:
      return null;
  }
}

function ScopeBody({ step }: { step: Extract<Step, { kind: "scope" }> }) {
  const d = step.data;
  const where = d.nationwide
    ? "across the country"
    : d.node_ids.length
      ? `at ${joinWords(d.node_ids)}`
      : d.region_ids.length
        ? `in ${joinWords(d.region_ids.map((r) => REGIONS[r] ?? r))}`
        : "";
  return (
    <>
      <p className="fe-title">Read the question</p>
      <p>
        The symptom is “{d.symptom.toLowerCase()}” {where ? `${where}, ` : ""}
        between {dayTimeOf(toMs(d.window_start))} and {dayTimeOf(toMs(d.window_end))}
        {d.ongoing ? ", and it is still going on" : ""}.
      </p>
      {d.source === "default" ? <p className="fe-sub">The question was too vague to read a window from, so a default window was used.</p> : null}
      {d.unknown_ids.length ? <p className="fe-sub">Not found in the network: {d.unknown_ids.join(", ")}.</p> : null}
    </>
  );
}

function duration(ms: number): string {
  return ms < 1000 ? `${Math.max(1, Math.round(ms))} ms` : `${(ms / 1000).toFixed(1)} s`;
}

function ToolBody({ step }: { step: ToolStep }) {
  const label = toolLabel(step.tool);
  const summary = argSummary(step.args);
  const result = step.result;
  if (step.status === "running") {
    return (
      <>
        <p className="fe-title">
          <span className="here">{TOOLS[step.tool]?.verb ?? `Running ${label}`}…</span>
        </p>
        {summary ? <p className="fe-sub">{summary}</p> : null}
      </>
    );
  }
  if (step.status === "skipped") {
    return (
      <>
        <p className="fe-title">{label}</p>
        <p className="fe-sub">Same as {result?.duplicate_of ?? "an earlier step"}, not run again.</p>
      </>
    );
  }
  const failed = step.status === "error";
  return (
    <>
      <p className="fe-title">
        {label}
        {result ? <span className="fe-ms mono">{duration(result.wall_ms)}</span> : null}
      </p>
      {summary ? <p className="fe-sub">{summary}</p> : null}
      <p className={failed ? "fe-fail" : undefined}>{plainText(result?.error ?? result?.headline ?? "")}</p>
      <Details step={step} />
    </>
  );
}

const REF_LIMIT = 6;

function Details({ step }: { step: ToolStep }) {
  const [allRefs, setAllRefs] = useState(false);
  const rows = argRows(step.args);
  const result = step.result;
  const refs = result?.refs ?? [];
  const body = result?.body ?? "";
  if (rows.length === 0 && refs.length === 0 && !body) return null;
  const shown = allRefs ? refs : refs.slice(0, REF_LIMIT);
  return (
    <details className="fe-details">
      <summary>Details</summary>
      {rows.length ? (
        <dl className="fe-args">
          {rows.map((r) => (
            <div key={r.key}>
              <dt>{ARG_LABELS[r.key] ?? r.label}</dt>
              <dd className={r.kind === "time" || r.kind === "code" ? "mono" : undefined}>
                {Array.isArray(r.value) ? r.value.map((v) => listValueLabel(r.key, v)).join(", ") : r.value}
              </dd>
            </div>
          ))}
        </dl>
      ) : null}
      {rows.some((r) => r.kind === "time") ? <p className="fe-sub">Times are Africa/Tunis.</p> : null}
      {refs.length ? (
        <>
          <p className="fe-read">Evidence returned ({refs.length})</p>
          <ul className="fe-refs">
            {shown.map((r) => (
              <li key={r.ref}>
                <code>{r.ref}</code>
                <span className="fe-sub">{EVIDENCE_KINDS[r.kind]?.label ?? r.kind}</span>
                <span>{plainText(r.summary)}</span>
              </li>
            ))}
          </ul>
          {refs.length > REF_LIMIT ? (
            <button type="button" className="link fe-more" aria-expanded={allRefs} onClick={() => setAllRefs((v) => !v)}>
              {allRefs ? "Show fewer" : `Show all ${refs.length}`}
            </button>
          ) : null}
        </>
      ) : null}
      {body ? (
        <>
          <p className="fe-read">What the agent read</p>
          <pre>{body}</pre>
        </>
      ) : null}
      {result?.truncated ? <p className="fe-sub">The text the agent read was cut short.</p> : null}
      {result?.data_truncated ? <p className="fe-sub">The data behind this result was cut short, so the board may show only part of it.</p> : null}
    </details>
  );
}
