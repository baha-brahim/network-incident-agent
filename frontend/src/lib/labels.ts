/**
 * The one place that turns the agent's internal names into plain words.
 * Each entry has a short label and a definition for a tooltip.
 */
import type { Category, Classification, Confidence, EvidenceKind } from "./types";

export interface Term {
  label: string;
  definition: string;
}

export type Tone = "danger" | "warn" | "event" | "ok" | "neutral";

export const CLASSIFICATIONS: Record<Classification, Term & { tone: Tone; sentence: string }> = {
  incident: {
    label: "Incident",
    tone: "danger",
    sentence: "A real fault is affecting the network.",
    definition: "Something is broken and customers are affected.",
  },
  planned_maintenance: {
    label: "Planned maintenance",
    tone: "warn",
    sentence: "The change in traffic matches scheduled work.",
    definition: "Engineers scheduled this work in advance, so the drop is expected and not a fault.",
  },
  expected_event: {
    label: "Expected event",
    tone: "event",
    sentence: "The change in traffic matches a known event.",
    definition: "A public event or holiday explains the unusual traffic. The network is behaving normally.",
  },
  no_impact: {
    label: "No impact",
    tone: "ok",
    sentence: "Noisy signals, but customers are not affected.",
    definition: "Alarms or anomalies exist, but service quality did not change.",
  },
  inconclusive: {
    label: "Inconclusive",
    tone: "neutral",
    sentence: "The evidence does not settle the question.",
    definition: "The agent could not tell what happened with the evidence it could reach.",
  },
};

export const CATEGORIES: Record<Category, Term> = {
  transport_failure: {
    label: "Transport link failure",
    definition:
      "A fibre or microwave link that carries traffic from several sites to the core network stopped working, so every site behind it went down together.",
  },
  power_failure: {
    label: "Site power failure",
    definition: "A site lost mains power and then its backup battery, so it stopped serving customers.",
  },
  bad_change: {
    label: "Faulty configuration change",
    definition: "A change pushed to the network (a configuration or parameter update) made service worse.",
  },
  core_degradation: {
    label: "Core service degradation",
    definition:
      "A shared core service, such as DNS, slowed down. Every region feels it because all sites depend on it.",
  },
  capacity: {
    label: "Radio capacity congestion",
    definition: "A site's radio resources are almost fully used at busy hours, so speeds fall and latency rises.",
  },
  transport_degradation: {
    label: "Degraded transport link",
    definition:
      "A link still works but performs badly, for example a microwave link in heavy rain. Latency rises on the sites behind it.",
  },
  planned_maintenance: {
    label: "Planned maintenance",
    definition: "Scheduled work by the network team.",
  },
  expected_event: {
    label: "Expected event",
    definition: "A known external event, such as a match or a public holiday.",
  },
  no_impact: {
    label: "No customer impact",
    definition: "Nothing changed for customers.",
  },
  unknown: {
    label: "Cause unknown",
    definition: "The agent did not find a cause it could support with evidence.",
  },
};

export const CONFIDENCE: Record<Confidence, Term & { tone: Tone; level: number }> = {
  high: {
    label: "High confidence",
    tone: "ok",
    level: 3,
    definition: "Direct evidence from more than one kind of source, and the look-alike causes were ruled out.",
  },
  medium: {
    label: "Medium confidence",
    tone: "warn",
    level: 2,
    definition: "The evidence points one way, but some of it is indirect or a check is missing.",
  },
  low: {
    label: "Low confidence",
    tone: "danger",
    level: 1,
    definition: "The evidence is thin or conflicting. Treat the conclusion as a lead, not a finding.",
  },
};

export const VERDICTS: Record<string, Term & { tone: Tone }> = {
  confirmed: { label: "Confirmed", tone: "ok", definition: "The evidence supports this explanation." },
  rejected: { label: "Rejected", tone: "neutral", definition: "The evidence rules this explanation out." },
  unresolved: { label: "Unresolved", tone: "warn", definition: "The evidence could neither support nor rule this out." },
};

export const BASIS: Record<string, Term> = {
  observed: { label: "Observed", definition: "A cited tool result shows this directly." },
  inferred: { label: "Inferred", definition: "The agent's reasoning from the cited evidence. Not shown directly by any one result." },
};

export const EVIDENCE_KINDS: Record<EvidenceKind, Term> = {
  alert: { label: "Detector alert", definition: "A group of related anomalies raised by the anomaly detector." },
  anomaly: { label: "Anomaly", definition: "One KPI that moved far away from its normal level." },
  alarm: { label: "Alarm", definition: "A message raised by network equipment." },
  change: { label: "Change", definition: "An entry in the change log." },
  maintenance: { label: "Maintenance window", definition: "A scheduled piece of work in the maintenance calendar." },
  event: { label: "External event", definition: "A public event or holiday that affects traffic." },
  runbook: { label: "Runbook", definition: "An excerpt from the operations runbooks." },
  node: { label: "Network node", definition: "A site, link or router and where it sits in the network." },
  call: { label: "Tool call", definition: "The result of one query the agent ran." },
};

export const TOOLS: Record<string, Term & { verb: string }> = {
  get_anomalies: {
    label: "Detector alerts",
    verb: "Checking the anomaly detector",
    definition: "Reads the alerts the anomaly detector raised in the time window.",
  },
  get_alarms: {
    label: "Alarms",
    verb: "Reading alarms",
    definition: "Lists equipment alarms on the nodes in question, grouped when they repeat.",
  },
  get_topology: {
    label: "Topology",
    verb: "Looking up the topology",
    definition: "Shows what a node depends on and which nodes share its links.",
  },
  query_kpis: {
    label: "KPI series",
    verb: "Querying KPIs",
    definition: "Compares measured KPIs with their usual level at the same time of day.",
  },
  get_maintenance: {
    label: "Maintenance calendar",
    verb: "Checking the maintenance calendar",
    definition: "Looks for scheduled work on the nodes and the nodes above them.",
  },
  get_changes: {
    label: "Change log",
    verb: "Checking the change log",
    definition: "Looks for configuration pushes and upgrades on the nodes and the nodes above them.",
  },
  get_external_events: {
    label: "External events",
    verb: "Checking external events",
    definition: "Looks for public events and holidays in the region.",
  },
  search_runbooks: {
    label: "Runbook search",
    verb: "Searching the runbooks",
    definition: "Finds the passages of the operations runbooks that match a description.",
  },
  run_sql: {
    label: "SQL query",
    verb: "Running a read-only query",
    definition: "A read-only SELECT on the network database, limited by allow-lists.",
  },
};

export const ALARM_TYPES: Record<string, Term> = {
  SITE_DOWN: { label: "Site down", definition: "The site stopped reporting and is unreachable." },
  LINK_LOS: { label: "Loss of signal", definition: "A transport link stopped receiving signal. Usually a cut fibre or failed equipment." },
  LINK_DEGRADED: { label: "Link degraded", definition: "A transport link works but with errors or reduced capacity." },
  VSWR_HIGH: { label: "High antenna reflection", definition: "The antenna feed reflects too much power (VSWR, voltage standing wave ratio). Common and often harmless on its own." },
  TEMP_HIGH: { label: "High temperature", definition: "The equipment cabinet is too hot." },
  HIGH_PRB: { label: "High radio load", definition: "Almost all radio resource blocks (PRB) of a cell are in use." },
  MAINS_FAILURE: { label: "Mains power lost", definition: "The site lost its mains power supply and runs on battery." },
  BATTERY_LOW: { label: "Battery low", definition: "The backup battery is nearly empty." },
  DNS_TIMEOUT_RATE: { label: "DNS timeouts", definition: "Many DNS look-ups time out." },
  RRC_FAILURE_RATE_HIGH: { label: "Connection setup failures", definition: "Many phones fail to set up a radio connection (RRC) with the cell." },
  CPU_HIGH: { label: "High CPU", definition: "The processor of the equipment is overloaded." },
  DOOR_OPEN: { label: "Cabinet door open", definition: "The cabinet door sensor reports open." },
  FAN_FAILURE: { label: "Fan failure", definition: "A cooling fan stopped." },
  RECTIFIER_FAULT: { label: "Rectifier fault", definition: "The power rectifier of the site reports a fault." },
};

export interface Metric extends Term {
  unit: string;
}

export const METRICS: Record<string, Metric> = {
  dl_volume_mb: { label: "Downlink traffic", unit: "MB", definition: "Data delivered to users in each 15-minute step." },
  ul_volume_mb: { label: "Uplink traffic", unit: "MB", definition: "Data sent by users in each 15-minute step." },
  active_users: { label: "Active users", unit: "users", definition: "Users with an active connection." },
  availability_pct: { label: "Availability", unit: "%", definition: "Share of time the cells were up and reporting. 100% is normal." },
  rrc_success_pct: { label: "Connection setup success", unit: "%", definition: "Share of radio connection attempts (RRC setups) that succeed." },
  drop_rate_pct: { label: "Call drop rate", unit: "%", definition: "Share of sessions that end abnormally." },
  latency_ms: { label: "Latency", unit: "ms", definition: "Round-trip delay seen by users." },
  prb_util_pct: { label: "Radio load", unit: "%", definition: "Share of radio resource blocks (PRB) in use. Near 100% means the cell is saturated." },
  query_success_pct: { label: "DNS query success", unit: "%", definition: "Share of DNS look-ups that succeed." },
  resolution_ms: { label: "DNS resolution time", unit: "ms", definition: "Time to answer a DNS look-up." },
  attach_success_pct: { label: "Attach success", unit: "%", definition: "Share of phones that register with the core network successfully." },
};

export const REGIONS: Record<string, string> = {
  TUN: "Grand Tunis",
  SAH: "Sahel",
  SFX: "Sfax",
  SUD: "South",
};

export const ARG_LABELS: Record<string, string> = {
  start: "From",
  end: "To",
  node_ids: "Nodes",
  node_id: "Node",
  entity_id: "Entity",
  entity_ids: "Entities",
  entity_type: "Entity type",
  region_id: "Region",
  metrics: "KPIs",
  metric: "KPI",
  include_descendants: "Include nodes below",
  include_ancestors: "Include nodes above",
  min_severity: "Minimum severity",
  alarm_types: "Alarm types",
  include: "Include",
  query: "Search for",
  k: "Passages",
  sql: "Query",
};

export function nodeKind(id: string): string | null {
  if (/^S-[A-Z]{3}-\d+/.test(id)) return "Site";
  if (/^LNK-/.test(id)) return "Transport link";
  if (/^AGG-/.test(id)) return "Aggregation router";
  if (/^CORE-DNS/.test(id)) return "Core DNS";
  if (/^CORE-AMF/.test(id)) return "Core mobility function (AMF)";
  if (/^CORE-UPF/.test(id)) return "Core user-plane function (UPF)";
  if (/^C-[A-Z]{3}-/.test(id)) return "Cell";
  return null;
}

export function toolLabel(tool: string): string {
  return TOOLS[tool]?.label ?? tool.replace(/_/g, " ");
}

export function categoryLabel(category: string | null | undefined): string {
  if (!category) return "Not established";
  return CATEGORIES[category as Category]?.label ?? category.replace(/_/g, " ");
}

export function metricLabel(metric: string): string {
  return METRICS[metric]?.label ?? metric.replace(/_/g, " ");
}

/** Everything the free-text renderer should recognise and explain. */
export function lookupTerm(token: string): Term | null {
  return ALARM_TYPES[token] ?? METRICS[token] ?? CATEGORIES[token as Category] ?? null;
}

export const NODE_ID_PATTERN = /\b(?:S-[A-Z]{3}-\d{3}|LNK-[A-Z]{3}-\d{2}-[A-Z]|AGG-[A-Z]{3}-\d{2}|CORE-(?:DNS|AMF|UPF)-\d{2}|C-[A-Z]{3}-\d{3}-\d)\b/;
