import { CLASSIFICATIONS, REGIONS, toolLabel } from "./labels";
import { fmtIso, plural } from "./format";
import type { RunView, Step } from "./investigation";

export function plainText(text: string): string {
  return text.replace(/`/g, "");
}

export function joinWords(items: readonly string[]): string {
  if (items.length <= 1) return items.join("");
  return `${items.slice(0, -1).join(", ")} and ${items.at(-1)}`;
}

export function regionNames(ids: readonly string[]): string[] {
  return ids.map((id) => REGIONS[id] ?? id);
}

/** The text a screen reader hears when a step finishes or arrives. */
export function announce(step: Step | undefined, view: RunView): string {
  if (!step) return "";
  switch (step.kind) {
    case "tool":
      if (step.status === "running") return "";
      if (step.status === "skipped") return `${toolLabel(step.tool)} skipped: repeated call.`;
      return `${toolLabel(step.tool)} ${step.status === "error" ? "failed" : "finished"}: ${plainText(step.result?.error ?? step.result?.headline ?? "")}`;
    case "error":
      return `Error: ${step.message}`;
    case "scope":
      return `Scope understood: ${step.data.symptom}.`;
    default:
      if (view.phase === "finished") return "Investigation finished. The report is ready.";
      return "";
  }
}

export function reportRowText(view: RunView): string {
  const r = view.report;
  if (!r) return "";
  return `${CLASSIFICATIONS[r.classification].label} · ${r.confidence} confidence`;
}

export function windowText(start: string, end: string): string {
  return `${fmtIso(start)} to ${fmtIso(end)}`;
}

export function missingSentence(missing: readonly string[]): string {
  return missing.length ? joinWords(missing) : "what it had skipped";
}

export function countText(n: number, one: string): string {
  return plural(n, one);
}
