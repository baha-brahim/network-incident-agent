import { fmtNumber } from "@/lib/format";
import type { DemoSummary } from "@/lib/types";

/** "under 1 s", "about 12 s", "about 60 min": a recording's length in the unit that reads best. */
export function aboutSeconds(demo: Pick<DemoSummary, "duration_ms">): string {
  const seconds = demo.duration_ms / 1000;
  if (!(seconds >= 1)) return "under 1 s";
  if (seconds < 120) return `about ${Math.round(seconds)} s`;
  const minutes = Math.round(seconds / 60);
  if (minutes < 120) return `about ${minutes} min`;
  return `about ${Math.round(minutes / 60)} h`;
}

export function toolCalls(n: number): string {
  return `${fmtNumber(n)} tool ${n === 1 ? "call" : "calls"}`;
}

export function demoMeta(demo: DemoSummary): string {
  return `${toolCalls(demo.counts.tool_calls)} · ${aboutSeconds(demo)}`;
}
