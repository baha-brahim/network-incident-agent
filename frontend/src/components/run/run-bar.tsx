"use client";

import { AlertTriangle, Check, Pause, Play, RotateCcw, SkipForward } from "lucide-react";
import { SPEEDS, type RunPlayer } from "@/hooks/use-run-player";
import { cx } from "@/lib/cx";
import { toolSteps, type RunView } from "@/lib/investigation";

function elapsed(ms: number): string {
  const s = Math.round(ms / 1000);
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;
}

function Dot() {
  return <span aria-hidden className="relative inline-flex size-2.5 rounded-full bg-accent" />;
}

export function StatusText({ view, connecting, paused, failed }: { view: RunView; connecting?: boolean; paused?: boolean; failed?: boolean }) {
  const tools = toolSteps(view).length;
  if (failed) {
    return (
      <span className="flex items-center gap-2 text-sm font-medium text-danger">
        <AlertTriangle aria-hidden className="size-4" />
        Connection problem
      </span>
    );
  }
  if (view.phase === "finished") {
    return (
      <span className="flex items-center gap-2 text-sm font-medium text-ok">
        <Check aria-hidden className="size-4" />
        Finished
        {view.finished ? <span className="font-normal text-muted">in {view.finished.usage.wall_seconds.toFixed(1)} s</span> : null}
      </span>
    );
  }
  if (view.phase === "error") {
    return (
      <span className="flex items-center gap-2 text-sm font-medium text-warn">
        <AlertTriangle aria-hidden className="size-4" />
        Stopped with an error
      </span>
    );
  }
  if (connecting) {
    return (
      <span className="flex items-center gap-2 text-sm text-muted">
        <span aria-hidden className="spinner inline-block size-3.5 rounded-full border-2 border-accent border-t-transparent" />
        Connecting…
      </span>
    );
  }
  return (
    <span className="flex items-center gap-2 text-sm">
      {paused ? <span aria-hidden className="inline-block size-2.5 rounded-full bg-muted" /> : <Dot />}
      <span className="font-medium">{paused ? "Paused" : "Investigating"}</span>
      <span className="font-mono text-xs text-muted">
        {elapsed(view.lastTMs)} · {tools} tool call{tools === 1 ? "" : "s"}
      </span>
    </span>
  );
}

const btn =
  "press inline-flex min-h-9 items-center justify-center gap-1.5 rounded-lg border border-line-strong bg-surface px-3 text-sm font-medium hover-surface disabled:opacity-45";

export function PlayerBar({ player }: { player: RunPlayer }) {
  const { view, status, source } = player;
  const isDemo = source?.kind === "demo";
  const finished = status === "done" || view.phase === "finished" || view.phase === "error";
  const paused = status === "paused";
  const connecting = status === "connecting";
  const failed = status === "failed";
  const canPause = !finished && !failed && !connecting;

  return (
    <div className="flex flex-wrap items-center gap-x-4 gap-y-2">
      <div className="min-w-0 flex-1 basis-40">
        <StatusText view={view} connecting={connecting} paused={paused} failed={failed} />
      </div>
      <div className="flex flex-wrap items-center gap-2">
        {!finished && !failed ? (
          <button type="button" className={btn} onClick={paused ? player.resume : player.pause} disabled={!canPause} aria-label={paused ? "Resume" : "Pause"}>
            {paused ? <Play aria-hidden className="size-4" /> : <Pause aria-hidden className="size-4" />}
            <span className="max-sm:sr-only">{paused ? "Resume" : "Pause"}</span>
          </button>
        ) : null}
        {isDemo && !finished ? (
          <div role="group" aria-label="Playback speed" className="inline-flex rounded-lg bg-surface-2 p-0.5">
            {SPEEDS.map((s) => (
              <button
                key={s}
                type="button"
                aria-pressed={player.speed === s}
                onClick={() => player.setSpeed(s)}
                className={cx(
                  "press min-h-8 min-w-9 rounded-md px-2 font-mono text-xs font-medium",
                  player.speed === s ? "bg-surface text-fg shadow-sm" : "text-muted hover:text-fg",
                )}
              >
                {s}×
              </button>
            ))}
          </div>
        ) : null}
        {isDemo && !finished && !failed ? (
          <button type="button" className={btn} onClick={player.skip} aria-label="Skip to report">
            <SkipForward aria-hidden className="size-4" />
            <span className="max-sm:sr-only">Skip to report</span>
          </button>
        ) : null}
        {isDemo && (finished || failed) ? (
          <button type="button" className={cx(btn, "border-accent text-accent")} onClick={player.restart}>
            <RotateCcw aria-hidden className="size-4" />
            {failed ? "Try again" : "Replay again"}
          </button>
        ) : null}
        {isDemo && !finished && !failed ? (
          <button type="button" className={btn} onClick={player.restart} aria-label="Restart">
            <RotateCcw aria-hidden className="size-4" />
            <span className="max-sm:sr-only">Restart</span>
          </button>
        ) : null}
      </div>
    </div>
  );
}

export function StaticBar({ view, note }: { view: RunView; note?: string }) {
  return (
    <div className="flex flex-wrap items-center gap-x-4 gap-y-1">
      <StatusText view={view} />
      {note ? <span className="text-xs text-muted">{note}</span> : null}
    </div>
  );
}
