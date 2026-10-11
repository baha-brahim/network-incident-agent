import { describe, expect, it } from "vitest";
import fiberCut from "./__fixtures__/fiber-cut.json";
import {
  emptyView,
  findStep,
  isPartialReport,
  reduce,
  reduceEvents,
  toolSteps,
} from "./investigation";
import type { Recording, RunEvent } from "./types";

const recording = fiberCut as unknown as Recording;
const events = recording.events;

function event(type: RunEvent["type"], data: object, seq: number): RunEvent {
  return { seq, type, run_id: "RUN-test", t_ms: seq * 100, data } as RunEvent;
}

const started = reduce(
  emptyView,
  event("run_started", { question: "Why?", asked_at: "2026-09-22T07:38:00+00:00", trigger: "user" }, 0),
);

const call = (ref: string, seq: number) =>
  event("tool_call", { ref, tool: "get_alarms", args: { a: 1 }, node: "investigate", iteration: 1 }, seq);

const result = (ref: string, seq: number, extra: object = {}) =>
  event(
    "tool_result",
    {
      ref,
      tool: "get_alarms",
      headline: "h",
      error: null,
      n_refs: 0,
      truncated: false,
      wall_ms: 3,
      args: {},
      body: "",
      refs: [],
      data: null,
      data_truncated: false,
      duplicate_of: null,
      ...extra,
    },
    seq,
  );

describe("reduce over a recorded run", () => {
  const view = reduceEvents(events);

  it("finishes with a report and the cited evidence", () => {
    expect(view.phase).toBe("finished");
    expect(view.report?.classification).toBe("incident");
    expect(view.report?.root_cause_node_id).toBe("LNK-TUN-02-C");
    expect(view.question).toMatch(/Grand Tunis/);
    expect(view.evidence["ALR-0022"]?.kind).toBe("alert");
  });

  it("keeps the order of the events, with one step per tool call", () => {
    const tools = toolSteps(view);
    expect(tools.map((t) => t.id)).toEqual(["T1", "T2", "T3", "T4", "T5", "T6", "T7"]);
    expect(tools.every((t) => t.status === "done")).toBe(true);
    expect(view.steps.filter((s) => s.kind === "scope")).toHaveLength(1);
    expect(view.steps.filter((s) => s.kind === "gate")).toHaveLength(1);
    expect(view.steps.filter((s) => s.kind === "note")).toHaveLength(2);
    expect(view.steps.filter((s) => s.kind === "model")).toHaveLength(7);
    const seqs = view.steps.map((s) => s.seq);
    expect(seqs).toEqual([...seqs].sort((a, b) => a - b));
  });

  it("maps every reference the report cites to the step that produced it", () => {
    const cited = new Set<string>();
    for (const f of view.report!.findings) f.refs.forEach((r) => cited.add(r));
    for (const t of view.report!.timeline) t.refs.forEach((r) => cited.add(r));
    expect(cited.size).toBeGreaterThan(5);
    for (const ref of cited) {
      const origin = view.origins[ref];
      expect(origin, ref).toBeDefined();
      expect(findStep(view, origin)?.kind).toBe("tool");
    }
  });

  it("shows a call as running between tool_call and tool_result", () => {
    const callIndex = events.findIndex((e) => e.type === "tool_call");
    const running = reduceEvents(events.slice(0, callIndex + 1));
    const step = toolSteps(running)[0];
    expect(running.phase).toBe("running");
    expect(step.status).toBe("running");
    expect(step.result).toBeNull();
    expect(step.args).toBeTruthy();

    const resolved = reduce(running, events[callIndex + 1]);
    const done = toolSteps(resolved)[0];
    expect(done.status).toBe("done");
    expect(done.result?.headline).toBeTruthy();
    expect(done.seq).toBe(step.seq);
    expect(resolved.steps).toHaveLength(running.steps.length);
  });

  it("ignores an event it has already seen", () => {
    const partial = reduceEvents(events.slice(0, 8));
    expect(reduce(partial, events[3])).toBe(partial);
    expect(reduceEvents(events, partial).steps).toHaveLength(view.steps.length);
  });

  it("does not mutate earlier views", () => {
    const before = reduceEvents(events.slice(0, 5));
    const stepsBefore = before.steps;
    reduce(before, events[5]);
    expect(before.steps).toBe(stepsBefore);
  });
});

describe("reduce edge cases", () => {
  it("marks a repeated call as skipped and a failed call as an error", () => {
    const view = reduceEvents(
      [
        call("T1", 1),
        result("T1", 2),
        call("T2", 3),
        result("T2", 4, { duplicate_of: "T1" }),
        call("T3", 5),
        result("T3", 6, { error: "Invalid arguments" }),
      ],
      started,
    );
    const [t1, t2, t3] = toolSteps(view);
    expect([t1.status, t2.status, t3.status]).toEqual(["done", "skipped", "error"]);
    expect(t1.args).toEqual({ a: 1 });
  });

  it("shows a result whose call was never seen", () => {
    const view = reduce(started, result("T9", 1, { tool: "run_sql", args: { sql: "select 1" } }));
    expect(toolSteps(view)).toHaveLength(1);
    expect(toolSteps(view)[0].args).toEqual({ sql: "select 1" });
  });

  it("ends in the error phase with a placeholder report", () => {
    const report = {
      title: "Investigation incomplete",
      classification: "inconclusive",
      root_cause_category: "unknown",
      root_cause_node_id: null,
      root_cause_summary: "No conclusion could be written: boom",
      confidence: "low",
      confidence_reason: "-",
      impact_summary: "Unknown.",
      impact_start: null,
      impact_end: null,
      root_cause_time: null,
      affected_node_ids: [],
      timeline: [],
      findings: [],
      hypotheses: [],
      dismissed_signals: [],
      recommended_actions: [],
    };
    const view = reduceEvents(
      [
        event("error", { message: "provider failed", where: "investigate" }, 1),
        event(
          "run_finished",
          {
            status: "error",
            usage: { llm_calls: 1, cached_calls: 0, tool_calls: 0, input_tokens: 10, output_tokens: 2, wall_seconds: 1 },
            models_used: [],
            fell_back: false,
            issues: ["no report"],
            report,
            markdown: "",
            evidence: {},
          },
          2,
        ),
      ],
      started,
    );
    expect(view.phase).toBe("error");
    expect(view.steps.at(-1)).toMatchObject({ kind: "error", message: "provider failed" });
    expect(view.issues).toEqual(["no report"]);
    expect(isPartialReport(view)).toBe(true);
  });
});
