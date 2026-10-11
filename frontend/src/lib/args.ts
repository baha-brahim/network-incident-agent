import { ARG_LABELS, metricLabel } from "./labels";

export interface ArgRow {
  key: string;
  label: string;
  /** One value, or a list shown as chips. */
  value: string | string[];
  kind: "text" | "list" | "time" | "flag" | "code";
}

const TIME = /^\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}/;

/** Arguments the tools take, in a readable order and with empty ones left out. */
export function argRows(args: Record<string, unknown>): ArgRow[] {
  const order = ["start", "end"];
  const keys = Object.keys(args).sort((a, b) => {
    const ia = order.indexOf(a);
    const ib = order.indexOf(b);
    if (ia !== -1 || ib !== -1) return (ia === -1 ? 99 : ia) - (ib === -1 ? 99 : ib);
    return 0;
  });
  const rows: ArgRow[] = [];
  for (const key of keys) {
    const raw = args[key];
    if (raw === null || raw === undefined || raw === "") continue;
    if (Array.isArray(raw) && raw.length === 0) continue;
    const label = ARG_LABELS[key] ?? key.replace(/_/g, " ");
    if (typeof raw === "boolean") {
      rows.push({ key, label, value: raw ? "yes" : "no", kind: "flag" });
    } else if (Array.isArray(raw)) {
      rows.push({
        key,
        label,
        value: raw.map((v) => (key === "metrics" ? String(v) : String(v))),
        kind: "list",
      });
    } else if (typeof raw === "string" && TIME.test(raw)) {
      rows.push({ key, label, value: raw.slice(0, 16).replace("T", " "), kind: "time" });
    } else if (key === "sql") {
      rows.push({ key, label, value: String(raw), kind: "code" });
    } else {
      rows.push({ key, label, value: typeof raw === "object" ? JSON.stringify(raw) : String(raw), kind: "text" });
    }
  }
  return rows;
}

export function listValueLabel(key: string, value: string): string {
  return key === "metrics" ? metricLabel(value) : value;
}

/** A short line about what a call looks at, for the timeline. */
export function argSummary(args: Record<string, unknown>): string {
  const parts: string[] = [];
  const ids = (args.node_ids ?? args.entity_ids) as unknown;
  if (Array.isArray(ids) && ids.length) parts.push(ids.slice(0, 3).join(", ") + (ids.length > 3 ? ` +${ids.length - 3}` : ""));
  else if (typeof args.node_id === "string") parts.push(args.node_id);
  else if (typeof args.entity_id === "string") parts.push(args.entity_id);
  else if (typeof args.region_id === "string") parts.push(args.region_id);
  else if (typeof args.query === "string") parts.push(`“${args.query}”`);
  return parts.join(" · ");
}
