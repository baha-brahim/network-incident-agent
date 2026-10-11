"use client";

import { CloudOff } from "lucide-react";
import { Notice, buttonStyles } from "@/components/ui/notice";
import type { Failure } from "@/hooks/use-run-player";
import { minutesText } from "@/lib/format";

/** What went wrong with the connection, in plain words, and what to do next. */
export function describeFailure(f: Failure): { title: string; body: string; tone: "warn" | "danger" | "neutral" } {
  switch (f.kind) {
    case "limit":
      return {
        title: "Today's live runs are used up",
        body: `Live investigations use a free model tier, so the number per day is limited${f.limit ? ` (${f.limit})` : ""}. The count resets at midnight UTC${f.retryAfter ? `, in about ${minutesText(f.retryAfter / 60)}` : ""}. A recorded replay shows the same thing and costs nothing.`,
        tone: "warn",
      };
    case "disabled":
      return {
        title: "Live mode is switched off",
        body: "The server is not running live investigations right now. Recorded replays are still available.",
        tone: "neutral",
      };
    case "invalid":
      return { title: "That question was not accepted", body: f.message, tone: "warn" };
    case "not_found":
      return { title: "Not found", body: "The server has no record of that investigation.", tone: "warn" };
    case "dropped":
      return {
        title: "The connection was lost",
        body: "The stream ended before the investigation finished. What arrived is shown below; run it again to see the rest.",
        tone: "warn",
      };
    case "unreachable":
      return {
        title: "The server could not be reached",
        body: "Check your connection and try again. If you are running this locally, make sure the API is started.",
        tone: "danger",
      };
    default:
      return { title: "Something went wrong", body: f.message, tone: "danger" };
  }
}

export function FailureNotice({ failure, actions }: { failure: Failure; actions?: React.ReactNode }) {
  const d = describeFailure(failure);
  return (
    <Notice role="alert" tone={d.tone} title={d.title} action={actions}>
      {d.body}
    </Notice>
  );
}

/** Shown instead of the investigation when nothing arrived at all. */
export function FailureScreen({
  failure,
  onBack,
  onWatchReplay,
  onRetry,
}: {
  failure: Failure;
  onBack(): void;
  onWatchReplay(): void;
  onRetry?: () => void;
}) {
  const d = describeFailure(failure);
  const replayHelps = failure.kind === "limit" || failure.kind === "disabled";
  return (
    <div className="mx-auto w-full max-w-xl px-4 py-16 text-center sm:py-24">
      <span className="mx-auto mb-4 grid size-12 place-items-center rounded-full bg-surface-2 text-muted">
        <CloudOff aria-hidden className="size-6" />
      </span>
      <h1 className="text-xl font-semibold tracking-tight">{d.title}</h1>
      <p className="mt-2 text-muted">{d.body}</p>
      <div className="mt-6 flex flex-wrap justify-center gap-2">
        {replayHelps ? (
          <button type="button" className={buttonStyles.primary} onClick={onWatchReplay}>
            Watch a recorded replay
          </button>
        ) : onRetry ? (
          <button type="button" className={buttonStyles.primary} onClick={onRetry}>
            Try again
          </button>
        ) : null}
        <button type="button" className={buttonStyles.secondary} onClick={onBack}>
          Back to the cases
        </button>
      </div>
    </div>
  );
}
