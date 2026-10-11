/** Formatting helpers. Every time shown to a person is in the network's local time. */

export const TIMEZONE = "Africa/Tunis";
/** Africa/Tunis has no daylight saving time: it is UTC+1 all year. */
const OFFSET_MS = 3_600_000;

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
const pad = (n: number) => String(n).padStart(2, "0");

/** A date that reads its fields as Tunis local time, from a UTC instant. */
function tunisParts(ms: number) {
  const d = new Date(ms + OFFSET_MS);
  return {
    year: d.getUTCFullYear(),
    month: d.getUTCMonth(),
    day: d.getUTCDate(),
    hour: d.getUTCHours(),
    minute: d.getUTCMinutes(),
  };
}

export function toMs(iso: string): number {
  return new Date(iso).getTime();
}

/** "18:15" */
export function timeOf(ms: number): string {
  const p = tunisParts(ms);
  return `${pad(p.hour)}:${pad(p.minute)}`;
}

/** "25 Sep, 18:15" */
export function dayTimeOf(ms: number): string {
  const p = tunisParts(ms);
  return `${p.day} ${MONTHS[p.month]}, ${pad(p.hour)}:${pad(p.minute)}`;
}

export function fmtIso(iso: string | null | undefined): string {
  if (!iso) return "unknown";
  const ms = toMs(iso);
  return Number.isNaN(ms) ? iso : dayTimeOf(ms);
}

const LOCAL = /^(\d{4})-(\d{2})-(\d{2})[ T](\d{2}):(\d{2})/;

/** Reads "YYYY-MM-DD HH:MM" (already local) as a plain number of minutes since the epoch. */
function localMinutes(s: string): number | null {
  const m = LOCAL.exec(s);
  if (!m) return null;
  return Date.UTC(+m[1], +m[2] - 1, +m[3], +m[4], +m[5]) / 60_000;
}

/** "21 Sep, 16:50" from a local "YYYY-MM-DD HH:MM" string; anything else is returned as given. */
export function fmtLocal(s: string | null | undefined): string {
  if (!s) return "unknown";
  const m = LOCAL.exec(s);
  if (!m) return s;
  return `${+m[3]} ${MONTHS[+m[2] - 1]}, ${m[4]}:${m[5]}`;
}

/** "16:50" from a local string. */
export function localClock(s: string): string {
  const m = LOCAL.exec(s);
  return m ? `${m[4]}:${m[5]}` : s;
}

export function localDay(s: string): string | null {
  const m = LOCAL.exec(s);
  return m ? `${+m[3]} ${MONTHS[+m[2] - 1]}` : null;
}

export function durationBetween(start: string | null, end: string | null): string | null {
  if (!start || !end) return null;
  const a = localMinutes(start);
  const b = localMinutes(end);
  if (a === null || b === null || b < a) return null;
  return minutesText(b - a);
}

export function minutesText(total: number): string {
  const minutes = Math.round(total);
  if (minutes < 60) return `${minutes} min`;
  const h = Math.floor(minutes / 60);
  const m = minutes % 60;
  if (h >= 48) return `${Math.round(minutes / 1440)} days`;
  return m === 0 ? `${h} h` : `${h} h ${m} min`;
}

export function fmtNumber(n: number): string {
  return new Intl.NumberFormat("en-US").format(Math.round(n));
}

/** Compact for chart axes: 1,200 becomes 1.2k. */
export function compact(n: number): string {
  const abs = Math.abs(n);
  if (abs >= 1_000_000) return `${trim(n / 1_000_000)}M`;
  if (abs >= 10_000) return `${trim(n / 1000)}k`;
  if (abs >= 1000) return `${trim(n / 1000)}k`;
  if (abs >= 100) return String(Math.round(n));
  if (abs >= 10) return trim(n);
  return trim(n, 2);
}

function trim(n: number, digits = 1): string {
  return String(Number(n.toFixed(digits)));
}

export function fmtSeconds(ms: number): string {
  return `${(ms / 1000).toFixed(1)} s`;
}

export function fmtTokens(n: number): string {
  return fmtNumber(n);
}

/** "3 min ago" style text is avoided on purpose: data is synthetic and fixed in time. */
export function plural(n: number, one: string, many = `${one}s`): string {
  return `${n} ${n === 1 ? one : many}`;
}
