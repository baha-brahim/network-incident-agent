"use client";

import { AlertTriangle, ArrowRight, ChevronDown } from "lucide-react";
import Link from "next/link";
import { useState } from "react";
import { toolCalls } from "@/components/investigate/demo-text";
import { Define } from "@/components/ui/term";
import { cx } from "@/lib/cx";
import { fmtIso, toMs } from "@/lib/format";
import { CLASSIFICATIONS, CONFIDENCE, REGIONS, categoryLabel, metricLabel } from "@/lib/labels";
import type { AlertOut, Classification, Confidence, InvestigationSummary } from "@/lib/types";
import { SeverityMark, VerdictMark } from "./marks";
import { alertSpan, clock, counted, firstNames, humanize, scoreText, secondsText, sentenceCase, triggerText } from "./text";

const MAX_SITES = 3;
const MAX_METRICS = 5;
/** Node IDs shown in an open alert before "Show all". */
const MAX_NODES = 12;

export function RunRow({ run }: { run: InvestigationSummary }) {
  const verdict = run.verdict ?? "";
  const verdictLabel = verdict
    ? Object.hasOwn(CLASSIFICATIONS, verdict)
      ? CLASSIFICATIONS[verdict as Classification].label
      : sentenceCase(humanize(verdict))
    : "";
  const confidence = run.confidence
    ? Object.hasOwn(CONFIDENCE, run.confidence)
      ? CONFIDENCE[run.confidence as Confidence].label
      : `${humanize(run.confidence)} confidence`
    : null;
  const failed = run.status === "error";
  const asked = toMs(run.asked_at);
  const seconds = run.seconds != null ? secondsText(run.seconds) : "";
  const facts = [
    run.tool_calls != null ? toolCalls(run.tool_calls) : null,
    seconds || null,
    run.trigger && run.trigger !== "user" ? triggerText(run.trigger, run.alert_id) : null,
  ].filter(Boolean);
  const cause = !failed && run.cause && run.cause !== run.verdict ? categoryLabel(run.cause) : null;
  const nothing = !failed && !verdictLabel && !cause && !run.node_id && !confidence;

  return (
    <li>
      <Link href={`/incidents/${encodeURIComponent(run.run_id)}`} className="row row-run">
        <time className="row-time mono" dateTime={Number.isNaN(asked) ? undefined : run.asked_at}>
          {clock(asked)}
        </time>
        <span className="row-main">
          <span className="row-title" dir="auto">
            {run.question}
          </span>
          <span className="row-line">
            {failed ? (
              <span className="out-error">
                <AlertTriangle aria-hidden size={14} />
                Stopped with an error
              </span>
            ) : verdictLabel ? (
              <span className="out-verdict">
                <VerdictMark verdict={verdict} />
                {verdictLabel}
              </span>
            ) : null}
            {cause ? <span>{cause}</span> : null}
            {run.node_id ? <span className="mono id">{run.node_id}</span> : null}
            {!failed && confidence ? <span className="quiet">{confidence.toLowerCase()}</span> : null}
            {nothing ? <span className="quiet">No result recorded</span> : null}
          </span>
        </span>
        <span className="row-aside">
          <span className="mono quiet">{facts.join(" · ")}</span>
          <ArrowRight aria-hidden size={18} className="row-arrow" />
        </span>
      </Link>
    </li>
  );
}

/** Node IDs: the first few and a button for the rest, so an alert that spans many sites does not fill the screen. */
function NodeIds({ ids }: { ids: readonly string[] }) {
  const [all, setAll] = useState(false);
  const { shown, more } = firstNames(ids, MAX_NODES);
  return (
    <>
      {(all ? ids : shown).map((id) => (
        <span key={id} className="mono id">
          {id}
        </span>
      ))}
      {more > 0 ? (
        <button type="button" className="link" aria-expanded={all} onClick={() => setAll((v) => !v)}>
          {all ? "Show fewer" : `Show all ${ids.length}`}
        </button>
      ) : null}
    </>
  );
}

export function AlertRow({ alert }: { alert: AlertOut }) {
  const [open, setOpen] = useState(false);
  const start = toMs(alert.start_at);
  const end = toMs(alert.end_at);
  const panelId = `alert-${alert.id}`;
  const sites = alert.entity_ids.filter((id) => !alert.region_ids.includes(id));
  const metrics = firstNames(alert.metrics.map(metricLabel), MAX_METRICS);
  const summary = alert.summary.trim() || `Alert ${alert.id}`;

  return (
    <li className={cx("alert", open && "is-open")}>
      <button type="button" aria-expanded={open} aria-controls={open ? panelId : undefined} onClick={() => setOpen((v) => !v)} className="row row-alert">
        <time className="row-time mono" dateTime={Number.isNaN(start) ? undefined : alert.start_at}>
          {clock(start)}
        </time>
        <span className="row-main">
          <span className="row-summary" dir="auto">
            <span className="row-summary-text">{summary}</span>
          </span>
          <span className="row-line">
            <SeverityMark severity={alert.severity} />
            {alert.region_ids.length > 0 ? <span>{alert.region_ids.map((r) => (Object.hasOwn(REGIONS, r) ? REGIONS[r] : r)).join(", ")}</span> : null}
            {sites.length > 0 ? (
              <span className="mono id">
                {sites.slice(0, MAX_SITES).join(", ")}
                {sites.length > MAX_SITES ? ` +${sites.length - MAX_SITES}` : ""}
              </span>
            ) : null}
            {alert.run_id ? <span className="quiet">Investigated</span> : null}
          </span>
          {metrics.shown.length > 0 ? (
            <span className="row-line quiet">
              KPIs moved: {metrics.shown.join(", ")}
              {metrics.more > 0 ? ` and ${metrics.more} more` : ""}
            </span>
          ) : null}
        </span>
        <span className="row-aside">
          <span className="mono quiet">{alertSpan(start, end)}</span>
          <ChevronDown aria-hidden size={18} className="row-chevron" />
        </span>
      </button>

      {open ? (
        <div id={panelId} className="panel">
          <dl className="panel-facts">
            <div>
              <dt>Alert</dt>
              <dd className="mono">{alert.id}</dd>
            </div>
            <div>
              <dt>Window</dt>
              <dd>
                {fmtIso(alert.start_at)} to {fmtIso(alert.end_at)}
              </dd>
            </div>
            <div>
              <dt>Status</dt>
              <dd>{humanize(alert.status) || "Not given"}</dd>
            </div>
            <div>
              <dt>
                <Define
                  term={{
                    label: "Score",
                    definition: "The detector's ranking of how large, long and widespread the deviation is. Medium starts at 9, high at 12.",
                  }}
                >
                  Score
                </Define>
              </dt>
              <dd className="mono">{scoreText(alert.score)}</dd>
            </div>
            <div>
              <dt>Anomalies</dt>
              <dd>{counted(alert.n_anomalies, "anomaly", "anomalies")} grouped</dd>
            </div>
            <div>
              <dt>Nodes</dt>
              <dd className="panel-ids">{alert.entity_ids.length > 0 ? <NodeIds ids={alert.entity_ids} /> : "None listed"}</dd>
            </div>
            <div>
              <dt>KPIs</dt>
              <dd>{alert.metrics.length > 0 ? alert.metrics.map(metricLabel).join(", ") : "None listed"}</dd>
            </div>
          </dl>
          <div className="panel-action">
            {alert.run_id ? (
              <>
                <Link href={`/incidents/${encodeURIComponent(alert.run_id)}`} className="link">
                  Investigated
                </Link>
                <p>The server investigated this alert. Open the saved run to read the report and the steps behind it.</p>
              </>
            ) : (
              <>
                <button type="button" disabled className="btn" aria-describedby={`${panelId}-why`}>
                  Investigate this alert
                </button>
                <p id={`${panelId}-why`}>Not investigated yet. The server investigates alerts on its own; to ask about this one now, use live mode.</p>
              </>
            )}
          </div>
        </div>
      ) : null}
    </li>
  );
}
