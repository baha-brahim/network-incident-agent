"use client";

import { useRouter } from "next/navigation";
import { useCallback, useMemo } from "react";
import { StaticBar } from "@/components/run/run-bar";
import { RunPanel } from "@/components/run/run-panel";
import { Notice, Skeleton, buttonStyles } from "@/components/ui/notice";
import { useAsync } from "@/hooks/use-async";
import { api, ApiError } from "@/lib/api";
import { fmtIso } from "@/lib/format";
import { emptyView, reduceEvents, type RunView } from "@/lib/investigation";
import type { InvestigationDetail } from "@/lib/types";
import Link from "next/link";

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

  if (run.loading) {
    return (
      <div aria-busy className="mx-auto w-full max-w-[88rem] px-4 pt-8 sm:px-6">
        <Skeleton className="h-4 w-40" />
        <Skeleton className="mt-4 h-8 w-2/3" />
        <div className="mt-8 grid gap-5 lg:grid-cols-[23rem_1fr]">
          <Skeleton className="h-96 w-full rounded-xl" />
          <Skeleton className="h-96 w-full rounded-xl" />
        </div>
      </div>
    );
  }
  if (run.error || !view || !run.data) {
    const notFound = run.error instanceof ApiError && run.error.kind === "not_found";
    return (
      <div className="mx-auto w-full max-w-xl px-4 py-16">
        <Notice
          role="alert"
          tone={notFound ? "warn" : "danger"}
          title={notFound ? "That investigation does not exist" : "The investigation could not be loaded"}
          action={
            <>
              {notFound ? null : (
                <button type="button" className={buttonStyles.secondary} onClick={run.reload}>
                  Try again
                </button>
              )}
              <Link href="/incidents" className={buttonStyles.secondary}>
                Back to incidents
              </Link>
            </>
          }
        >
          {notFound ? "It may have been removed, or the link is wrong." : "The server did not answer."}
        </Notice>
      </div>
    );
  }

  return (
    <RunPanel
      view={view}
      eyebrow={`Saved run · ${run.data.run_id}`}
      animate={false}
      onBack={() => router.push("/incidents")}
      backLabel="All incidents"
      bar={<StaticBar view={view} note={`Asked as of ${fmtIso(run.data.asked_at)} (Tunis time)`} />}
    />
  );
}
