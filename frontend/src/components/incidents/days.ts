/** Grouping of the list by calendar day in the network's local time (UTC+1, no daylight saving). */

const OFFSET_MS = 3_600_000;
const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
const WEEKDAYS = ["Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"];

export interface Day {
  /** Sortable, unique per day: "2026-10-01". */
  key: string;
  /** "1 Oct" */
  date: string;
  /** "Thursday" */
  weekday: string;
}

export const UNKNOWN_DAY: Day = {
  key: "unknown",
  date: "Date unknown",
  weekday: "",
};

export function dayOf(ms: number): Day {
  if (!Number.isFinite(ms)) return UNKNOWN_DAY;
  const d = new Date(ms + OFFSET_MS);
  const y = d.getUTCFullYear();
  const m = d.getUTCMonth();
  const day = d.getUTCDate();
  return {
    key: `${y}-${String(m + 1).padStart(2, "0")}-${String(day).padStart(2, "0")}`,
    date: `${day} ${MONTHS[m]}`,
    weekday: WEEKDAYS[d.getUTCDay()],
  };
}

export function groupByDay<T extends { time: number }>(items: readonly T[]): Array<{ day: Day; items: T[] }> {
  const groups: Array<{ day: Day; items: T[] }> = [];
  for (const item of items) {
    const day = dayOf(item.time);
    const last = groups[groups.length - 1];
    if (last && last.day.key === day.key) last.items.push(item);
    else groups.push({ day, items: [item] });
  }
  return groups;
}

/** Newest first; anything whose time could not be read goes last instead of breaking the order. */
export function newestFirst(a: { time: number }, b: { time: number }): number {
  const x = Number.isFinite(a.time);
  const y = Number.isFinite(b.time);
  if (x && y) return b.time - a.time;
  return x === y ? 0 : x ? -1 : 1;
}
