"use client";

import { ChevronDown, Radar, Search } from "lucide-react";
import Link from "next/link";
import { useMemo, useState } from "react";
import { Badge } from "@/components/ui/badge";
import { Notice, Skeleton, buttonStyles } from "@/components/ui/notice";
import { Define } from "@/components/ui/term";
import { useAsync } from "@/hooks/use-async";
import { api } from "@/lib/api";
import { cx } from "@/lib/cx";
import { fmtIso, fmtNumber, minutesText, timeOf, toMs } from "@/lib/format";
import { CLASSIFICATIONS, CONFIDENCE, REGIONS, categoryLabel, metricLabel, type Tone } from "@/lib/labels";
import type { AlertOut, InvestigationSummary } from "@/lib/types";

type Item =
  | { type: "run"; id: string; time: number; run: InvestigationSummary }
  | { type: "alert"; id: string; time: number; alert: AlertOut };

type Filter = "all" | "run" | "alert";

const loadRuns = (signal: AbortSignal) => api.investigations(50, signal);
const loadAlerts = (signal: AbortSignal) => api.alerts(50, signal);

const SEVERITY: Record<string, Tone> = { high: "danger", medium: "warn", low: "neutral" };

export function IncidentsView() {
  const runs = useAsync(loadRuns);
  const alerts = useAsync(loadAlerts);
  const [filter, setFilter] = useState<Filter>("all");

  const items = useMemo<Item[]>(() => {
    const out: Item[] = [];
    for (const run of runs.data ?? []) out.push({ type: "run", id: run.run_id, time: toMs(run.asked_at), run });
    for (const alert of alerts.data ?? []) out.push({ type: "alert", id: alert.id, time: toMs(alert.start_at), alert });
    return out.sort((a, b) => b.time - a.time);
  }, [runs.data, alerts.data]);

  const loading = runs.loading || alerts.loading;
  const bothFailed = !!runs.error && !!alerts.error;
  const shown = items.filter((i) => filter === "all" || i.type === filter);
  const noRuns = !runs.loading && !runs.error && (runs.data?.length ?? 0) === 0;
  const noAlerts = !alerts.loading && !alerts.error && (alerts.data?.length ?? 0) === 0;

  return (
    <div className="mx-auto w-full max-w-4xl px-4 pb-16 pt-8 sm:px-6 sm:pt-10">
      <h1 className="text-2xl font-semibold tracking-tight sm:text-3xl">Incidents</h1>
      <p className="mt-2 max-w-2xl text-muted">
        Investigations run on this server, and the alerts raised by the anomaly detector, in one list. Times are Africa/Tunis, as of the moment each
        was about.
      </p>

      <div role="group" aria-label="Show" className="mt-6 inline-flex gap-1 rounded-lg bg-surface-2 p-1">
        {(
          [
            ["all", "All"],
            ["run", "Investigations"],
            ["alert", "Detector alerts"],
          ] as const
        ).map(([key, label]) => (
          <button
            key={key}
            type="button"
            aria-pressed={filter === key}
            onClick={() => setFilter(key)}
            className={cx(
              "press min-h-9 rounded-md px-3 text-sm font-medium",
              filter === key ? "bg-surface text-fg shadow-sm" : "text-muted hover:text-fg",
            )}
          >
            {label}
          </button>
        ))}
      </div>

      <div className="mt-5 space-y-3">
        {loading ? (
          <div aria-hidden className="space-y-3">
            {Array.from({ length: 5 }, (_, i) => (
              <Skeleton key={i} className="h-24 w-full rounded-xl" />
            ))}
          </div>
        ) : bothFailed ? (
          <Notice
            role="alert"
            tone="danger"
            title="The incident list could not be loaded"
            action={
              <button
                type="button"
                className={buttonStyles.secondary}
                onClick={() => {
                  runs.reload();
                  alerts.reload();
                }}
              >
                Try again
              </button>
            }
          >
            The server did not answer.
          </Notice>
        ) : (
          <>
            {runs.error && filter !== "alert" ? (
              <Notice tone="warn" title="Investigations could not be loaded" action={<button type="button" className={buttonStyles.secondary} onClick={runs.reload}>Try again</button>}>
                The detector alerts are shown below.
              </Notice>
            ) : null}
            {alerts.error && filter !== "run" ? (
              <Notice tone="warn" title="Detector alerts could not be loaded" action={<button type="button" className={buttonStyles.secondary} onClick={alerts.reload}>Try again</button>}>
                The investigations are shown below.
              </Notice>
            ) : null}
            {noRuns && noAlerts && filter === "all" ? (
              <Notice
                title="Nothing here yet"
                action={
                  <Link href="/" className={buttonStyles.secondary}>
                    Start an investigation
                  </Link>
                }
              >
                Investigations started in live mode are saved and appear here, next to the detector&apos;s alerts. Recorded replays are not saved, because they are always available.
              </Notice>
            ) : null}
            {noRuns && !noAlerts && filter !== "alert" ? (
              <Notice
                title="No investigations yet"
                action={
                  <Link href="/" className={buttonStyles.secondary}>
                    Start one
                  </Link>
                }
              >
                Investigations started in live mode are saved and appear here. Recorded replays are not saved, because they are always available.
              </Notice>
            ) : null}
            {noRuns && noAlerts && filter === "run" ? (
              <Notice title="No investigations yet">Investigations started in live mode appear here.</Notice>
            ) : null}
            {noAlerts && filter === "alert" ? <Notice title="No detector alerts">The detector has not raised any alerts.</Notice> : null}
            <ul className="space-y-3">
              {shown.map((item) => (
                <li key={`${item.type}-${item.id}`}>{item.type === "run" ? <RunRow run={item.run} /> : <AlertRow alert={item.alert} />}</li>
              ))}
            </ul>
          </>
        )}
      </div>
    </div>
  );
}

function Marker({ type }: { type: "run" | "alert" }) {
  const Icon = type === "run" ? Search : Radar;
  return (
    <span className="inline-flex items-center gap-1.5 text-[11px] font-semibold uppercase tracking-wider text-muted">
      <span aria-hidden className={cx("grid size-5 place-items-center rounded-md", type === "run" ? "bg-accent-soft text-accent" : "bg-surface-2")}>
        <Icon className="size-3" />
      </span>
      {type === "run" ? "Investigation" : "Detector alert"}
    </span>
  );
}

function RunRow({ run }: { run: InvestigationSummary }) {
  const verdict = run.verdict ? CLASSIFICATIONS[run.verdict as keyof typeof CLASSIFICATIONS] : null;
  const conf = run.confidence ? CONFIDENCE[run.confidence as keyof typeof CONFIDENCE] : null;
  const failed = run.status === "error";
  return (
    <Link
      href={`/incidents/${encodeURIComponent(run.run_id)}`}
      className="press hover-border block rounded-xl border border-line bg-surface p-4"
    >
      <div className="flex flex-wrap items-center justify-between gap-2">
        <Marker type="run" />
        <span className="font-mono text-xs text-muted">{fmtIso(run.asked_at)}</span>
      </div>
      <p className="mt-2 line-clamp-2 font-medium leading-snug break-anywhere">{run.title ?? run.question}</p>
      {run.title ? <p className="mt-0.5 line-clamp-1 text-sm text-muted break-anywhere">“{run.question}”</p> : null}
      <div className="mt-3 flex flex-wrap items-center gap-x-3 gap-y-1.5 text-sm">
        {failed ? <Badge tone="warn">Stopped with an error</Badge> : null}
        {verdict ? <Badge tone={verdict.tone}>{verdict.label}</Badge> : null}
        {run.cause && run.cause !== run.verdict ? <span className="text-muted">{categoryLabel(run.cause)}</span> : null}
        {run.node_id ? <span className="rounded bg-surface-2 px-1.5 font-mono text-xs break-anywhere">{run.node_id}</span> : null}
        {conf ? <span className="text-xs text-muted">{conf.label.toLowerCase()}</span> : null}
        <span className="ml-auto font-mono text-xs text-muted">
          {run.trigger === "user" ? "asked by a visitor" : run.trigger}
          {run.seconds != null ? ` · ${run.seconds.toFixed(1)} s` : ""}
          {run.input_tokens != null && run.output_tokens != null ? ` · ${fmtNumber(run.input_tokens + run.output_tokens)} tokens` : ""}
        </span>
      </div>
    </Link>
  );
}

function AlertRow({ alert }: { alert: AlertOut }) {
  const [open, setOpen] = useState(false);
  const tone = SEVERITY[alert.severity] ?? "neutral";
  const duration = minutesText((toMs(alert.end_at) - toMs(alert.start_at)) / 60_000);
  const panelId = `alert-${alert.id}`;
  return (
    <div className="rounded-xl border border-line bg-surface">
      <button
        type="button"
        aria-expanded={open}
        aria-controls={panelId}
        onClick={() => setOpen((v) => !v)}
        className="press hover-surface block w-full rounded-xl p-4 text-left"
      >
        <div className="flex flex-wrap items-center justify-between gap-2">
          <Marker type="alert" />
          <span className="font-mono text-xs text-muted">{fmtIso(alert.start_at)}</span>
        </div>
        <div className="mt-2 flex items-start gap-3">
          <p className={cx("min-w-0 flex-1 font-medium leading-snug break-anywhere", !open && "line-clamp-3")}>{alert.summary}</p>
          <ChevronDown aria-hidden className={cx("mt-1 size-4 shrink-0 text-muted transition-transform duration-200 ease-[var(--ease-out)] motion-reduce:transition-none", open && "rotate-180")} />
        </div>
        <div className="mt-3 flex flex-wrap items-center gap-x-3 gap-y-1.5 text-sm">
          <Badge tone={tone}>{alert.severity} severity</Badge>
          {alert.region_ids.map((r) => (
            <span key={r} className="text-muted">
              {REGIONS[r] ?? r}
            </span>
          ))}
          <span className="ml-auto font-mono text-xs text-muted">
            until {timeOf(toMs(alert.end_at))}
            {duration ? ` · ${duration}` : ""}
          </span>
        </div>
      </button>
      {open ? (
        <div id={panelId} className="space-y-4 border-t border-line p-4 text-sm">
          <dl className="grid grid-cols-[7rem_1fr] gap-x-3 gap-y-2">
            <dt className="text-muted">Alert</dt>
            <dd className="font-mono text-xs leading-5">{alert.id}</dd>
            <dt className="text-muted">Window</dt>
            <dd>
              {fmtIso(alert.start_at)} to {fmtIso(alert.end_at)}
            </dd>
            <dt className="text-muted">Status</dt>
            <dd>{alert.status}</dd>
            <dt className="text-muted">
              <Define term={{ label: "Score", definition: "The detector's ranking of how large, long and widespread the deviation is. Medium starts at 9, high at 12." }}>Score</Define>
            </dt>
            <dd className="font-mono text-xs leading-5">{alert.score.toFixed(1)}</dd>
            <dt className="text-muted">Anomalies</dt>
            <dd>{alert.n_anomalies} grouped</dd>
            <dt className="text-muted">Nodes</dt>
            <dd className="flex flex-wrap gap-1">
              {alert.entity_ids.map((id) => (
                <span key={id} className="rounded bg-surface-2 px-1.5 py-0.5 font-mono text-xs break-anywhere">
                  {id}
                </span>
              ))}
            </dd>
            <dt className="text-muted">KPIs</dt>
            <dd className="flex flex-wrap gap-1">
              {alert.metrics.map((m) => (
                <span key={m} className="rounded bg-surface-2 px-1.5 py-0.5 text-xs">
                  {metricLabel(m)}
                </span>
              ))}
            </dd>
          </dl>
          <div>
            <button type="button" disabled className={cx(buttonStyles.secondary)} aria-describedby={`${panelId}-why`}>
              Investigate this alert
            </button>
            <p id={`${panelId}-why`} className="mt-1.5 text-xs text-muted">
              Not available yet. Investigating alerts automatically comes later; for now, ask about it in live mode.
            </p>
          </div>
        </div>
      ) : null}
    </div>
  );
}
