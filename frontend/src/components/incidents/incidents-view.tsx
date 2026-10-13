"use client";

import Link from "next/link";
import { useMemo, useState, type ReactNode } from "react";
import { Notice, Skeleton, SlowNote } from "@/components/ui/notice";
import { useAsync } from "@/hooks/use-async";
import { api } from "@/lib/api";
import { fmtNumber, toMs } from "@/lib/format";
import type { AlertOut, InvestigationSummary } from "@/lib/types";
import { groupByDay, newestFirst } from "./days";
import { AlertRow, RunRow } from "./rows";
import "./incidents.css";

type Item = { type: "run"; id: string; time: number; run: InvestigationSummary } | { type: "alert"; id: string; time: number; alert: AlertOut };

type Filter = "all" | "run" | "alert";

/** Rows shown at first, and added by each "Show more". */
const PAGE = 50;

const FILTERS: ReadonlyArray<readonly [Filter, string]> = [
  ["all", "All"],
  ["run", "Investigations"],
  ["alert", "Alerts"],
];

const loadRuns = (signal: AbortSignal) => api.investigations(50, signal);
const loadAlerts = (signal: AbortSignal) => api.alerts(50, signal);

export function IncidentsView() {
  const runs = useAsync(loadRuns);
  const alerts = useAsync(loadAlerts);
  const [filter, setFilter] = useState<Filter>("all");
  const [visible, setVisible] = useState(PAGE);

  const items = useMemo<Item[]>(() => {
    const out: Item[] = [];
    for (const run of runs.data ?? []) out.push({ type: "run", id: run.run_id, time: toMs(run.asked_at), run });
    for (const alert of alerts.data ?? [])
      out.push({
        type: "alert",
        id: alert.id,
        time: toMs(alert.start_at),
        alert,
      });
    return out.sort(newestFirst);
  }, [runs.data, alerts.data]);

  const loading = runs.loading || alerts.loading;
  const bothFailed = !!runs.error && !!alerts.error;
  const shown = items.filter((i) => filter === "all" || i.type === filter);
  const page = useMemo(() => shown.slice(0, visible), [shown, visible]);
  const groups = useMemo(() => groupByDay(page), [page]);
  const noRuns = !runs.loading && !runs.error && (runs.data?.length ?? 0) === 0;
  const noAlerts = !alerts.loading && !alerts.error && (alerts.data?.length ?? 0) === 0;
  const counts: Record<Filter, number | null> = {
    all: loading ? null : items.length,
    run: runs.data ? runs.data.length : null,
    alert: alerts.data ? alerts.data.length : null,
  };

  return (
    <div className="page incidents">
      <header className="inc-head">
        <h1>Incidents</h1>
        <p>
          Every investigation saved on this server and every alert the anomaly detector raised, newest first. Times are Africa/Tunis time, as of the moment each
          one is about.
        </p>
      </header>

      <div className="inc-filter">
        <div className="seg is-text" role="group" aria-label="Show">
          {FILTERS.map(([key, label]) => {
            const n = counts[key];
            return (
              <button
                key={key}
                type="button"
                aria-pressed={filter === key}
                onClick={() => {
                  setFilter(key);
                  setVisible(PAGE);
                }}
              >
                {label}
                {n !== null ? <span className="count">{fmtNumber(n)}</span> : null}
              </button>
            );
          })}
        </div>
      </div>

      <div className="inc-body">
        {loading ? (
          <ListSkeleton />
        ) : bothFailed ? (
          <Notice
            role="alert"
            tone="danger"
            title="The incident list could not be loaded"
            action={
              <>
                <button
                  type="button"
                  className="btn"
                  onClick={() => {
                    runs.reload();
                    alerts.reload();
                  }}
                >
                  Try again
                </button>
                <Link href="/how-it-works" className="btn">
                  How it works
                </Link>
              </>
            }
          >
            The server did not answer. It may be starting up: try again in a moment. The page on how the agent works does not need it.
          </Notice>
        ) : (
          <>
            {runs.error && filter !== "alert" ? (
              <Notice
                role="alert"
                tone="warn"
                title="Investigations could not be loaded"
                action={
                  <button type="button" className="btn" onClick={runs.reload}>
                    Try again
                  </button>
                }
              >
                {(alerts.data?.length ?? 0) > 0 ? "The detector alerts are listed below." : "Nothing else could be listed either."}
              </Notice>
            ) : null}
            {alerts.error && filter !== "run" ? (
              <Notice
                role="alert"
                tone="warn"
                title="Detector alerts could not be loaded"
                action={
                  <button type="button" className="btn" onClick={alerts.reload}>
                    Try again
                  </button>
                }
              >
                {(runs.data?.length ?? 0) > 0 ? "The saved investigations are listed below." : "No saved investigations to list."}
              </Notice>
            ) : null}

            {noRuns && noAlerts && filter === "all" ? (
              <Empty title="Nothing here yet" action>
                Investigations asked in live mode are saved and appear here, next to the detector&apos;s alerts. Recorded cases are not saved, because they are
                always available.
              </Empty>
            ) : null}
            {noRuns && noAlerts && filter === "run" ? <Empty title="No investigations yet">Investigations asked in live mode appear here.</Empty> : null}
            {noRuns && !noAlerts && filter === "run" ? (
              <Empty title="No investigations yet" action>
                Investigations asked in live mode are saved and appear here. Recorded cases are not saved, because they are always available.
              </Empty>
            ) : null}
            {noAlerts && filter === "alert" ? <Empty title="No detector alerts">The detector has not raised any alerts.</Empty> : null}
            {noRuns && !noAlerts && filter === "all" ? (
              <p className="inc-hint">
                No investigations are saved yet. Questions asked in live mode land here; recorded cases are not saved.{" "}
                <Link href="/">Watch a recorded case</Link>
              </p>
            ) : null}

            {groups.map(({ day, items: dayItems }) => (
              <section key={day.key} className="day" aria-labelledby={`day-${day.key}`}>
                <h2 id={`day-${day.key}`} className="day-label">
                  <span className="day-date">{day.date}</span>
                  <span className="day-weekday">{day.weekday}</span>
                </h2>
                <ul className="rows">
                  {dayItems.map((item) =>
                    item.type === "run" ? <RunRow key={`run-${item.id}`} run={item.run} /> : <AlertRow key={`alert-${item.id}`} alert={item.alert} />,
                  )}
                </ul>
              </section>
            ))}

            {shown.length > page.length ? (
              <div className="inc-more">
                <p role="status">
                  Showing {fmtNumber(page.length)} of {fmtNumber(shown.length)}
                </p>
                <button type="button" className="btn" onClick={() => setVisible((v) => v + PAGE)}>
                  Show {Math.min(PAGE, shown.length - page.length)} more
                </button>
              </div>
            ) : null}
          </>
        )}
      </div>
    </div>
  );
}

function Empty({ title, children, action }: { title: string; children: ReactNode; action?: boolean }) {
  return (
    <div className="inc-empty">
      <h2>{title}</h2>
      <p>{children}</p>
      {action ? (
        <Link href="/" className="btn is-primary">
          Run a recorded case
        </Link>
      ) : null}
    </div>
  );
}

const SKELETON_KINDS = ["run", "alert", "alert", "run", "alert", "alert"] as const;

function ListSkeleton() {
  return (
    <div role="status" aria-busy="true">
      <span className="sr-only">Loading incidents</span>
      <div className="day" aria-hidden>
        <div className="day-label">
          <Skeleton className="h-4 w-14" />
          <Skeleton className="mt-2 h-3.5 w-20" />
        </div>
        <ul className="rows">
          {SKELETON_KINDS.map((kind, i) => (
            <li key={i} className="row row-skeleton">
              <Skeleton className="row-time h-3.5 w-10" />
              <span className="row-main">
                {kind === "run" ? (
                  <>
                    <Skeleton className="h-6 w-4/5" />
                    <Skeleton className="mt-3 h-4 w-3/5" />
                  </>
                ) : (
                  <>
                    <Skeleton className="h-4 w-full max-w-xl" />
                    <Skeleton className="mt-2 h-4 w-2/5" />
                  </>
                )}
              </span>
              <Skeleton className="row-aside h-3.5 w-24" />
            </li>
          ))}
        </ul>
      </div>
      <SlowNote />
    </div>
  );
}
