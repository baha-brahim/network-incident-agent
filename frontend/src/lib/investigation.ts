/**
 * The view state of one investigation, built by folding the event list through `reduce`.
 * A replay, a live run and a stored run all go through here, so they render identically.
 */
import type {
  EvidenceEntry,
  EvidenceItem,
  GateData,
  LlmCallData,
  Report,
  RunEvent,
  RunFinishedData,
  ScopeData,
  ToolResultData,
} from "./types";

interface StepBase {
  id: string;
  seq: number;
  tMs: number;
}

export interface ScopeStep extends StepBase {
  kind: "scope";
  data: ScopeData;
}

/** A tool result with the fields the API fills in by default made explicit. */
export type ToolResult = ToolResultData & {
  args: Record<string, unknown>;
  body: string;
  refs: EvidenceItem[];
  data_truncated: boolean;
};

export type ToolStatus = "running" | "done" | "error" | "skipped";

export interface ToolStep extends StepBase {
  kind: "tool";
  tool: string;
  args: Record<string, unknown>;
  status: ToolStatus;
  result: ToolResult | null;
  resolvedMs: number | null;
}

export interface NoteStep extends StepBase {
  kind: "note";
  text: string;
  iteration: number;
}

export interface GateStep extends StepBase {
  kind: "gate";
  data: GateData;
}

export interface ModelStep extends StepBase {
  kind: "model";
  data: LlmCallData;
}

export interface ErrorStep extends StepBase {
  kind: "error";
  message: string;
  where: string | null;
}

export type Step = ScopeStep | ToolStep | NoteStep | GateStep | ModelStep | ErrorStep;

export type RunPhase = "empty" | "running" | "finished" | "error";

export interface RunView {
  runId: string | null;
  question: string;
  askedAt: string | null;
  trigger: string | null;
  phase: RunPhase;
  steps: Step[];
  report: Report | null;
  issues: string[];
  finished: RunFinishedData | null;
  /** Evidence by reference: grows with each tool result, completed by `run_finished`. */
  evidence: Record<string, EvidenceEntry>;
  /** The step that first produced each reference (a tool call's own `T<n>` maps to itself). */
  origins: Record<string, string>;
  lastSeq: number;
  lastTMs: number;
}

export const emptyView: RunView = {
  runId: null,
  question: "",
  askedAt: null,
  trigger: null,
  phase: "empty",
  steps: [],
  report: null,
  issues: [],
  finished: null,
  evidence: {},
  origins: {},
  lastSeq: -1,
  lastTMs: 0,
};

/** A view that already shows the question while the first event is on its way. */
export function startingView(question: string): RunView {
  return { ...emptyView, question, phase: "running" };
}

export function reduce(view: RunView, event: RunEvent): RunView {
  if (event.seq <= view.lastSeq) return view;
  const base: RunView = {
    ...view,
    runId: view.runId ?? event.run_id,
    lastSeq: event.seq,
    lastTMs: event.t_ms,
  };
  const at = { seq: event.seq, tMs: event.t_ms };

  switch (event.type) {
    case "run_started":
      return {
        ...base,
        phase: "running",
        question: event.data.question,
        askedAt: event.data.asked_at,
        trigger: event.data.trigger,
      };

    case "scope":
      return { ...base, steps: [...base.steps, { kind: "scope", id: `scope-${event.seq}`, ...at, data: event.data }] };

    case "llm_call":
      return { ...base, steps: [...base.steps, { kind: "model", id: `model-${event.seq}`, ...at, data: event.data }] };

    case "tool_call": {
      const d = event.data;
      const step: ToolStep = {
        kind: "tool",
        id: d.ref,
        ...at,
        tool: d.tool,
        args: d.args,
        status: "running",
        result: null,
        resolvedMs: null,
      };
      return {
        ...base,
        steps: [...base.steps, step],
        origins: { ...base.origins, [d.ref]: d.ref },
      };
    }

    case "tool_result": {
      const d: ToolResult = {
        ...event.data,
        args: event.data.args ?? {},
        body: event.data.body ?? "",
        refs: event.data.refs ?? [],
        data_truncated: event.data.data_truncated ?? false,
      };
      const status: ToolStatus = d.duplicate_of ? "skipped" : d.error ? "error" : "done";
      const index = base.steps.findIndex((s) => s.kind === "tool" && s.id === d.ref);
      const existing = index >= 0 ? (base.steps[index] as ToolStep) : null;
      const resolved: ToolStep = {
        kind: "tool",
        id: d.ref,
        seq: existing?.seq ?? event.seq,
        tMs: existing?.tMs ?? event.t_ms,
        tool: d.tool,
        args: Object.keys(d.args).length > 0 ? d.args : (existing?.args ?? {}),
        status,
        result: d,
        resolvedMs: event.t_ms,
      };
      const steps = existing
        ? base.steps.map((s, i) => (i === index ? resolved : s))
        : [...base.steps, resolved];
      const evidence = { ...base.evidence };
      const origins = { ...base.origins, [d.ref]: d.ref };
      evidence[d.ref] ??= { kind: "call", summary: d.headline };
      for (const item of d.refs) {
        evidence[item.ref] = { kind: item.kind, summary: item.summary };
        origins[item.ref] ??= d.ref;
      }
      return { ...base, steps, evidence, origins };
    }

    case "note":
      return {
        ...base,
        steps: [
          ...base.steps,
          { kind: "note", id: `note-${event.seq}`, ...at, text: event.data.text, iteration: event.data.iteration },
        ],
      };

    case "gate":
      return { ...base, steps: [...base.steps, { kind: "gate", id: `gate-${event.seq}`, ...at, data: event.data }] };

    case "report":
      return { ...base, report: event.data.report, issues: event.data.issues };

    case "error":
      return {
        ...base,
        steps: [
          ...base.steps,
          { kind: "error", id: `error-${event.seq}`, ...at, message: event.data.message, where: event.data.where ?? null },
        ],
      };

    case "run_finished": {
      const d = event.data;
      return {
        ...base,
        phase: d.status === "error" ? "error" : "finished",
        finished: d,
        report: d.report,
        issues: d.issues,
        evidence: { ...base.evidence, ...d.evidence },
      };
    }

    default:
      return base;
  }
}

export function reduceEvents(events: readonly RunEvent[], from: RunView = emptyView): RunView {
  return events.reduce(reduce, from);
}

export function toolSteps(view: RunView): ToolStep[] {
  return view.steps.filter((s): s is ToolStep => s.kind === "tool");
}

/** Steps a person can select: everything except the quiet model-call lines. */
export function isSelectable(step: Step): boolean {
  return step.kind !== "model";
}

export function findStep(view: RunView, id: string | null): Step | null {
  return id ? (view.steps.find((s) => s.id === id) ?? null) : null;
}

export function evidenceFor(view: RunView, ref: string): EvidenceEntry | null {
  return view.evidence[ref] ?? null;
}

/** True when the report is a placeholder written because the run could not conclude. */
export function isPartialReport(view: RunView): boolean {
  const r = view.report;
  if (!r) return false;
  return view.phase === "error" || (r.classification === "inconclusive" && r.title === "Investigation incomplete");
}
