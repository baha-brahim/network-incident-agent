import { reduce, emptyView, type RunView } from "@/lib/investigation";
import type { RunEvent } from "@/lib/types";

/** The longest pause shown between two steps, whatever the recording says. */
export const MAX_GAP_MS = 2500;
/** How long the empty board shows before the first step of each pass. */
export const INTRO_MS = 900;

export interface PreviewFrame {
  view: RunView;
  /** Time to wait before this frame replaces the one before it. */
  delay: number;
}

const ENDING: ReadonlySet<RunEvent["type"]> = new Set(["report", "run_finished"]);

/**
 * The frames of a preview that stops before the answer: up to and including the first completeness
 * check, or, without one, up to the event before the report. The report is never applied.
 */
export function previewFrames(events: readonly RunEvent[]): PreviewFrame[] {
  const firstEnding = events.findIndex((e) => ENDING.has(e.type));
  const limit = firstEnding === -1 ? events.length : firstEnding;
  const gate = events.slice(0, limit).findIndex((e) => e.type === "gate");
  const end = gate === -1 ? limit : gate + 1;

  const frames: PreviewFrame[] = [];
  let view = emptyView;
  let previous = 0;
  for (const event of events.slice(0, end)) {
    view = reduce(view, event);
    const gap = Math.min(MAX_GAP_MS, Math.max(0, event.t_ms - previous));
    frames.push({ view, delay: frames.length === 0 ? INTRO_MS : gap });
    previous = event.t_ms;
  }
  return frames;
}
