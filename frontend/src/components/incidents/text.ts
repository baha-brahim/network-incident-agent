import { dayTimeOf, minutesText, timeOf } from "@/lib/format";
import { dayOf } from "./days";

const valid = (ms: number) => Number.isFinite(ms);

/** A server value the page has no word for, in plain lower-case words: "alien_cause" becomes "alien cause". */
export function humanize(raw: string): string {
  return raw.replace(/[_\s]+/g, " ").trim();
}

export function sentenceCase(text: string): string {
  return text.charAt(0).toUpperCase() + text.slice(1);
}

/** "20:59", or "--:--" when the date could not be read. */
export function clock(ms: number): string {
  return valid(ms) ? timeOf(ms) : "--:--";
}

/** How long a run took: "under 0.1 s", "12.3 s", "24 h". */
export function secondsText(seconds: number): string {
  if (!Number.isFinite(seconds) || seconds < 0) return "";
  if (seconds < 0.1) return "under 0.1 s";
  if (seconds < 100) return `${seconds.toFixed(1)} s`;
  return minutesText(seconds / 60);
}

/** "until 22:00 · 2 h 45 min". An end before the start, or a date that cannot be read, is said plainly. */
export function alertSpan(startMs: number, endMs: number): string {
  if (!valid(startMs) || !valid(endMs)) return "window unclear";
  if (endMs < startMs) return "ends before it starts";
  const until = dayOf(startMs).key === dayOf(endMs).key ? timeOf(endMs) : dayTimeOf(endMs);
  return `until ${until} · ${minutesText((endMs - startMs) / 60_000)}`;
}

/** At most `max` names, then how many more there are. */
export function firstNames(names: readonly string[], max: number): { shown: string[]; more: number } {
  return { shown: names.slice(0, max), more: Math.max(0, names.length - max) };
}

/** A count with a singular and a plural: "1 anomaly", "0 anomalies". */
export function counted(n: number, one: string, many: string): string {
  return `${new Intl.NumberFormat("en-US").format(n)} ${n === 1 ? one : many}`;
}

/** 1 decimal, grouped thousands: "9.2", "1,000,000.0". */
export function scoreText(score: number): string {
  return Number.isFinite(score)
    ? new Intl.NumberFormat("en-US", {
        minimumFractionDigits: 1,
        maximumFractionDigits: 1,
      }).format(score)
    : "unknown";
}
