"use client";

import { ArrowLeft } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useMemo, useRef } from "react";
import { RunScreen } from "@/components/run/run-screen";
import { Skeleton, SlowNote } from "@/components/ui/notice";
import { useAsync } from "@/hooks/use-async";
import { api, ApiError } from "@/lib/api";
import { fmtIso, toMs } from "@/lib/format";
import { emptyView, reduceEvents, type RunView } from "@/lib/investigation";
import type { InvestigationDetail } from "@/lib/types";
import "./incidents.css";

function toView(detail: InvestigationDetail): RunView {
  if (detail.events.length > 0) return reduceEvents(detail.events);
  // A run saved without its steps still has a report to show.
  return {
    ...emptyView,
    runId: detail.run_id,
    question: detail.question,
    askedAt: detail.asked_at,
    trigger: detail.trigger,
    phase: detail.status === "error" ? "error" : "finished",
    report: detail.report ?? null,
    issues: detail.issues ?? [],
  };
}

export function StoredRun({ runId }: { runId: string }) {
  const router = useRouter();
  const load = useCallback((signal: AbortSignal) => api.investigation(runId, signal), [runId]);
  const run = useAsync(load);
  const view = useMemo(() => (run.data ? toView(run.data) : null), [run.data]);

  if (run.loading) return <RunSkeleton />;

  if (run.error || !view || !run.data) {
    const kind = run.error instanceof ApiError ? run.error.kind : "unreachable";
    return <RunProblem kind={kind} onRetry={run.reload} />;
  }

  return (
    <RunScreen
      view={view}
      animate={false}
      source={`Saved run · ${run.data.run_id}`}
      note={Number.isNaN(toMs(run.data.asked_at)) ? undefined : `Asked as of ${fmtIso(run.data.asked_at)} (Tunis time)`}
      backLabel="All incidents"
      onBack={() => router.push("/incidents")}
    />
  );
}

function RunProblem({ kind, onRetry }: { kind: string; onRetry(): void }) {
  const notFound = kind === "not_found";
  const heading = useRef<HTMLHeadingElement>(null);
  // The page was a loading state a moment ago; focus moves to the news so it is read out.
  useEffect(() => heading.current?.focus({ preventScroll: true }), []);
  return (
    <div className="page run-state">
      <BackLink />
      <h1 ref={heading} tabIndex={-1}>
        {notFound ? "That investigation does not exist" : "The investigation could not be loaded"}
      </h1>
      <p>
        {notFound
          ? "It may have been removed, or the link is wrong."
          : kind === "unreachable"
            ? "The server did not answer. It may be starting up: try again in a moment."
            : "The server could not read it. Try again, or open another one from the list."}
      </p>
      <div className="run-state-actions">
        {notFound ? null : (
          <button type="button" className="btn is-primary" onClick={onRetry}>
            Try again
          </button>
        )}
        <Link href="/incidents" className="btn">
          See all incidents
        </Link>
      </div>
    </div>
  );
}

function BackLink() {
  return (
    <Link href="/incidents" className="run-back">
      <ArrowLeft aria-hidden size={16} />
      All incidents
    </Link>
  );
}

function RunSkeleton() {
  return (
    <div className="page run-skeleton" role="status" aria-busy="true">
      <span className="sr-only">Loading the saved investigation</span>
      <div aria-hidden>
        <Skeleton className="h-4 w-36" />
        <Skeleton className="mt-5 h-10 w-full max-w-xl" />
        <Skeleton className="mt-3 h-10 w-2/3 max-w-md" />
        <div className="run-skeleton-controls">
          <Skeleton className="h-4 w-48" />
          <Skeleton className="h-9 w-28" />
        </div>
        <div className="run-skeleton-board">
          {[0, 1, 2, 3, 4].map((i) => (
            <div key={i} className="run-skeleton-lane">
              <Skeleton className="h-4 w-28" />
              <Skeleton className="h-3 w-1/2" />
            </div>
          ))}
        </div>
      </div>
      <SlowNote />
    </div>
  );
}
