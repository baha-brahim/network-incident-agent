import type { ResultRow } from "@/lib/results";

export interface RowBar {
  k: number;
  n: number;
  interval?: { low: number; high: number };
}

const COUNTS = /^(\d[\d,]*) of (\d[\d,]*)/;
const INTERVAL = /95% interval (\d+(?:\.\d+)?)% to (\d+(?:\.\d+)?)%/;

const whole = (text: string) => Number(text.replace(/,/g, ""));

/**
 * Reads "x of n" from the value and a "95% interval a% to b%" from the note, so the chart never holds
 * figures of its own. A value that is not a count, an empty or impossible one ("0 of 0", "5 of 2"), gets no
 * bar rather than a wrong one. An interval that is out of order or outside 0 to 100 is left out.
 */
export function rowBar(row: Pick<ResultRow, "value" | "note">): RowBar | null {
  const counts = COUNTS.exec(row.value);
  if (!counts) return null;
  const k = whole(counts[1]);
  const n = whole(counts[2]);
  if (!(n > 0) || k > n) return null;
  const span = row.note ? INTERVAL.exec(row.note) : null;
  const low = span ? Number(span[1]) : NaN;
  const high = span ? Number(span[2]) : NaN;
  const interval = span && low <= high && high <= 100 ? { low, high } : undefined;
  return { k, n, interval };
}
