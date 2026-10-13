"use client";

import { ArrowLeft, FastForward, Pause, Play, RotateCcw } from "lucide-react";
import { SPEEDS, type RunPlayer } from "@/hooks/use-run-player";
import { fmtSeconds, plural } from "@/lib/format";
import type { RunView } from "@/lib/investigation";

interface ControlsProps {
  view: RunView;
  player?: RunPlayer;
  note?: string;
  onBack(): void;
  backLabel: string;
}

function statusWord(view: RunView, player?: RunPlayer): string {
  if (!player) return view.phase === "error" ? "Ended in error" : view.phase === "finished" ? "Finished" : "Did not finish";
  switch (player.status) {
    case "connecting":
      return "Connecting";
    case "playing":
      return "Investigating";
    case "paused":
      return "Paused";
    case "failed":
      return "Stopped";
    default:
      return view.phase === "error" ? "Ended in error" : "Finished";
  }
}

export function runCounts(view: RunView): string {
  const tools = view.steps.filter((s) => s.kind === "tool").length;
  return `${view.lastTMs > 0 ? `${fmtSeconds(view.lastTMs)} · ` : ""}${plural(tools, "tool call")}`;
}

/** Back, status and the playback controls. Without a player only the status and the counts are shown. */
export function RunControls({ view, player, note, onBack, backLabel }: ControlsProps) {
  const status = player?.status;
  const active = status === "connecting" || status === "playing" || status === "paused";
  const isDemo = player?.source?.kind === "demo";

  return (
    <div className="run-controls">
      <button type="button" className="btn" onClick={onBack}>
        <ArrowLeft aria-hidden size={16} />
        <span className="lbl">{backLabel}</span>
      </button>

      <p className="run-status">
        <span className={status === "playing" ? "here" : undefined}>{statusWord(view, player)}</span>
        <span className="mono run-counts">{runCounts(view)}</span>
        {note ? <span className="run-note">{note}</span> : null}
      </p>

      {player ? (
        <div className="run-actions">
          {status === "playing" || status === "paused" || status === "connecting" ? (
            <button type="button" className="btn" disabled={status === "connecting"} onClick={status === "paused" ? player.resume : player.pause}>
              {status === "paused" ? <Play aria-hidden size={16} /> : <Pause aria-hidden size={16} />}
              <span className="lbl">{status === "paused" ? "Resume" : "Pause"}</span>
            </button>
          ) : null}
          {isDemo && active ? (
            <>
              <div className="seg run-speed" role="group" aria-label="Playback speed">
                {SPEEDS.map((s) => (
                  <button key={s} type="button" aria-pressed={player.speed === s} onClick={() => player.setSpeed(s)}>
                    {s}×
                  </button>
                ))}
              </div>
              {/* Narrow screens have no room for three buttons: one button steps through the speeds. */}
              <button
                type="button"
                className="btn run-speed-step"
                aria-label={`Playback speed ${player.speed}×. Change speed`}
                onClick={() => player.setSpeed(SPEEDS[(SPEEDS.indexOf(player.speed) + 1) % SPEEDS.length])}
              >
                <span className="mono">{player.speed}×</span>
              </button>
            </>
          ) : null}
          {active ? (
            <button type="button" className="btn is-primary" onClick={player.skip}>
              <FastForward aria-hidden size={16} className="skip-ico" />
              <span>
                Skip<span className="lbl"> to report</span>
              </span>
            </button>
          ) : null}
          {isDemo ? (
            <button type="button" className="btn" onClick={player.restart}>
              <RotateCcw aria-hidden size={16} />
              <span className="lbl">Restart</span>
            </button>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}
