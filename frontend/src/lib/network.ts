/**
 * The part of the network an investigation has learned about, folded from its steps in order:
 * which nodes exist, how they connect, and what is known about each.
 */
import { dayTimeOf, fmtIso, timeOf, toMs } from "./format";
import type { RunView, ToolStep } from "./investigation";
import { NODE_ID_PATTERN } from "./labels";
import type { Classification, EvidenceEntry, ScopeData } from "./types";

/** Core, aggregation router, transport link, site: the rows of the diagram from top to bottom. */
export type Layer = 0 | 1 | 2 | 3;

export interface NetAlarm {
  id: string;
  type: string;
  severity: string;
  raisedAt: string | null;
  clearedAt: string | null;
  count: number;
}

export type MarkerKind = "change" | "maintenance" | "event";

export interface NetMarker {
  id: string;
  kind: MarkerKind;
  label: string;
  at: string | null;
  until: string | null;
  description: string;
}

export interface NetNode {
  id: string;
  layer: Layer;
  region: string | null;
  parent: string | null;
  discoveredSeq: number;
  alarms: NetAlarm[];
  markers: NetMarker[];
  /** Sequence numbers of the tool calls that asked about this node. */
  probes: number[];
  /** Ids of every step that named this node. */
  touchedBy: string[];
  flags: { root: boolean; affected: boolean; detector: boolean };
}

export interface NetEdge {
  child: string;
  parent: string;
  seq: number;
}

export interface Network {
  nodes: NetNode[];
  edges: NetEdge[];
  byId: Map<string, NetNode>;
  scope: ScopeData | null;
  rootId: string | null;
  concluded: boolean;
  /** How the report classified the run; sets the colour and wording of the conclusion. */
  verdict: Classification | null;
  /** What the mark on the root-cause node says. */
  rootLabel: string;
  /** Regions that hold at least one node below the core. */
  regionsInUse: string[];
}

const ROOT_LABELS: Record<Classification, string> = {
  incident: "Root cause",
  planned_maintenance: "Planned work",
  expected_event: "Expected event",
  no_impact: "No customer impact",
  inconclusive: "Most likely cause",
};

export function layerOf(id: string): Layer | null {
  if (/^CORE-/.test(id)) return 0;
  if (/^AGG-/.test(id)) return 1;
  if (/^LNK-/.test(id)) return 2;
  if (/^S-[A-Z]{3}-\d+/.test(id)) return 3;
  return null;
}

export function regionOfId(id: string): string | null {
  const m = /^(?:S|AGG|LNK)-([A-Z]{3})-/.exec(id);
  return m ? m[1] : null;
}

const SEVERITY_RANK: Record<string, number> = { critical: 4, major: 3, minor: 2, warning: 1 };
export const severityRank = (s: string): number => SEVERITY_RANK[s] ?? 0;

export function worstAlarm(node: NetNode): NetAlarm | null {
  let worst: NetAlarm | null = null;
  for (const a of node.alarms) if (!worst || severityRank(a.severity) > severityRank(worst.severity)) worst = a;
  return worst;
}

export function alarmTotal(node: NetNode): number {
  return node.alarms.reduce((sum, a) => sum + a.count, 0);
}

export function humanize(text: string): string {
  const s = text.replace(/_/g, " ").trim();
  return s ? s[0].toUpperCase() + s.slice(1) : s;
}

type Row = Record<string, unknown>;
const asRows = (data: unknown): Row[] => {
  const rows = (data as { rows?: unknown } | null)?.rows;
  return Array.isArray(rows) ? (rows.filter((r) => r && typeof r === "object") as Row[]) : [];
};
const str = (v: unknown): string | null => (typeof v === "string" && v ? v : null);

/** The node ids a tool call was asked about. */
export function argNodeIds(args: Record<string, unknown>): string[] {
  const out: string[] = [];
  for (const key of ["node_ids", "entity_ids"]) {
    const v = args[key];
    if (Array.isArray(v)) for (const x of v) if (typeof x === "string") out.push(x);
  }
  for (const key of ["node_id", "entity_id"]) {
    const v = str(args[key]);
    if (v) out.push(v);
  }
  return out.filter((id) => layerOf(id) !== null);
}

export function deriveNetwork(view: RunView): Network {
  const byId = new Map<string, NetNode>();
  const nodes: NetNode[] = [];
  const edges: NetEdge[] = [];
  const edgeKeys = new Set<string>();
  const alarmIds = new Set<string>();
  const markerIds = new Set<string>();
  let scope: ScopeData | null = null;

  function ensure(id: unknown, seq: number, stepId: string, probe = false): NetNode | null {
    if (typeof id !== "string") return null;
    const layer = layerOf(id);
    if (layer === null) return null;
    let node = byId.get(id);
    if (!node) {
      node = {
        id,
        layer,
        region: regionOfId(id),
        parent: null,
        discoveredSeq: seq,
        alarms: [],
        markers: [],
        probes: [],
        touchedBy: [],
        flags: { root: false, affected: false, detector: false },
      };
      byId.set(id, node);
      nodes.push(node);
    }
    if (!node.touchedBy.includes(stepId)) node.touchedBy.push(stepId);
    if (probe && !node.probes.includes(seq)) node.probes.push(seq);
    return node;
  }

  function link(childId: string, parentId: string, seq: number, stepId: string) {
    const child = ensure(childId, seq, stepId);
    const parent = ensure(parentId, seq, stepId);
    if (!child || !parent || child.id === parent.id) return;
    const key = `${child.id}>${parent.id}`;
    if (edgeKeys.has(key) || child.parent) return;
    edgeKeys.add(key);
    child.parent = parent.id;
    edges.push({ child: child.id, parent: parent.id, seq });
  }

  function ingestTool(step: ToolStep) {
    const { seq, id } = step;
    for (const nid of argNodeIds(step.args)) ensure(nid, seq, id, true);
    const data = step.result?.data as Record<string, unknown> | null | undefined;
    if (!data || step.status === "error") return;

    switch (step.tool) {
      case "get_anomalies": {
        const alerts = Array.isArray(data.alerts) ? (data.alerts as Row[]) : [];
        for (const alert of alerts) {
          const entities = Array.isArray(alert.entities) ? alert.entities : [];
          for (const e of entities) {
            const n = ensure(e, seq, id);
            if (n) n.flags.detector = true;
          }
        }
        break;
      }
      case "get_topology": {
        const self = str(data.node_id);
        const ancestors = Array.isArray(data.ancestors)
          ? (data.ancestors as unknown[]).filter((a): a is string => typeof a === "string")
          : [];
        if (self) {
          ensure(self, seq, id);
          let child = self;
          for (const a of ancestors) {
            link(child, a, seq, id);
            child = a;
          }
          const siblings = Array.isArray(data.siblings) ? (data.siblings as unknown[]) : [];
          if (ancestors[0]) for (const s of siblings) if (typeof s === "string") link(s, ancestors[0], seq, id);
        }
        break;
      }
      case "get_alarms":
        for (const row of asRows(data)) {
          const node = ensure(row.node_id, seq, id);
          const alarmId = str(row.alarm_id);
          if (!node || !alarmId || alarmIds.has(alarmId)) continue;
          alarmIds.add(alarmId);
          node.alarms.push({
            id: alarmId,
            type: str(row.alarm_type) ?? "ALARM",
            severity: str(row.severity) ?? "minor",
            raisedAt: str(row.raised_at),
            clearedAt: str(row.cleared_at),
            count: typeof row.count === "number" ? row.count : 1,
          });
        }
        break;
      case "get_changes":
      case "get_maintenance":
      case "get_external_events":
        for (const row of asRows(data)) {
          const node = ensure(row.node_id, seq, id);
          const mid = str(row.change_id) ?? str(row.mw_id) ?? str(row.event_id);
          if (!node || !mid || markerIds.has(mid)) continue;
          markerIds.add(mid);
          const kind: MarkerKind = step.tool === "get_changes" ? "change" : step.tool === "get_maintenance" ? "maintenance" : "event";
          node.markers.push({
            id: mid,
            kind,
            label: kind === "maintenance" ? "Maintenance" : humanize(str(row.change_type) ?? str(row.event_type) ?? kind),
            at: str(row.executed_at) ?? str(row.start_at),
            until: str(row.end_at),
            description: str(row.description) ?? "",
          });
        }
        break;
      default:
        break;
    }
  }

  for (const step of view.steps) {
    if (step.kind === "scope") {
      scope ??= step.data;
      for (const nid of step.data.node_ids ?? []) ensure(nid, step.seq, step.id);
    } else if (step.kind === "tool") {
      ingestTool(step);
    }
  }

  const report = view.report;
  let rootId: string | null = null;
  if (report) {
    const root = ensure(report.root_cause_node_id, view.lastSeq, "report");
    if (root) {
      root.flags.root = true;
      rootId = root.id;
    }
    for (const nid of report.affected_node_ids ?? []) {
      const n = ensure(nid, view.lastSeq, "report");
      if (n) n.flags.affected = true;
    }
  }

  const regionsInUse = [...new Set(nodes.filter((n) => n.layer > 0 && n.region).map((n) => n.region as string))];
  const verdict = report?.classification ?? null;
  return {
    nodes,
    edges,
    byId,
    scope,
    rootId,
    concluded: !!report,
    verdict,
    rootLabel: verdict ? (ROOT_LABELS[verdict] ?? ROOT_LABELS.incident) : ROOT_LABELS.incident,
    regionsInUse,
  };
}

/** Ids of the nodes a step named or revealed. */
export function nodesTouchedBy(net: Network, stepId: string): string[] {
  return net.nodes.filter((n) => n.touchedBy.includes(stepId)).map((n) => n.id);
}

const NODE_IDS = new RegExp(NODE_ID_PATTERN.source, "g");

/** Ids of the nodes a piece of evidence (an alarm, a change, a detector alert, a tool call) is about. */
export function nodesForRef(view: RunView, net: Network, ref: string): string[] {
  const out = new Set<string>();
  if (net.byId.has(ref)) out.add(ref);
  const isCall = /^T\d+$/.test(ref);
  for (const n of net.nodes) {
    if (n.alarms.some((a) => a.id === ref) || n.markers.some((m) => m.id === ref)) out.add(n.id);
    if (isCall && n.touchedBy.includes(ref)) out.add(n.id);
  }
  const entry = view.evidence[ref];
  if (entry && !isCall) for (const m of entry.summary.matchAll(NODE_IDS)) if (net.byId.has(m[0])) out.add(m[0]);
  return [...out];
}

/** The evidence entries that mention a node, in the order they were found. */
export function nodeEvidence(view: RunView, id: string): Array<[string, EvidenceEntry]> {
  return Object.entries(view.evidence).filter(([ref, e]) => e.kind !== "call" && (ref === id || e.summary.includes(id)));
}

/** The nodes above this one, nearest first. */
export function chainOf(net: Network, id: string): string[] {
  const out: string[] = [];
  let cur = net.byId.get(id)?.parent ?? null;
  while (cur && out.length < 6 && !out.includes(cur)) {
    out.push(cur);
    cur = net.byId.get(cur)?.parent ?? null;
  }
  return out;
}

/** "21 Sep, 12:00 to 18:00" for a window inside one day, both ends in full otherwise. */
export function windowText(scope: ScopeData | null): string | null {
  if (!scope) return null;
  const a = toMs(scope.window_start);
  const b = toMs(scope.window_end);
  if (Number.isNaN(a) || Number.isNaN(b)) return `${fmtIso(scope.window_start)} to ${fmtIso(scope.window_end)}`;
  const sameDay = dayTimeOf(a).split(",")[0] === dayTimeOf(b).split(",")[0];
  return `${dayTimeOf(a)} to ${sameDay ? timeOf(b) : dayTimeOf(b)}`;
}

export function kindWord(layer: Layer): string {
  return ["core node", "aggregation router", "transport link", "site"][layer];
}

/** What the stage says about the diagram, for assistive technology. */
export function networkSummary(net: Network, where: string): string {
  const count = (layer: Layer) => net.nodes.filter((n) => n.layer === layer).length;
  const parts = (
    [
      [count(3), "sites"],
      [count(2), "transport links"],
      [count(1), "aggregation routers"],
      [count(0), "core nodes"],
    ] as const
  )
    .filter(([n]) => n > 0)
    .map(([n, label]) => `${n} ${label}`);
  const base = net.nodes.length ? `Network diagram for ${where}: ${parts.join(", ")}.` : `Network diagram for ${where}: no nodes named yet.`;
  const alarmed = net.nodes.filter((n) => n.alarms.length > 0).length;
  const alarmText = alarmed ? ` ${alarmed} with alarms.` : "";
  const root = net.rootId ? ` ${net.rootLabel}: ${net.rootId}.` : "";
  const affected = net.nodes.filter((n) => n.flags.affected).length;
  return `${base}${alarmText}${root}${affected ? ` ${affected} nodes affected.` : ""}`;
}
