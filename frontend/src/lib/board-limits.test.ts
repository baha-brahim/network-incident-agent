import { describe, expect, it } from "vitest";
import fiberCut from "./__fixtures__/fiber-cut.json";
import { buildBoard, capMarks, LABEL_MAX, layoutPins, markLabelWidth, MAX_PIN_ROWS, PIN_SIZE, type Mark, type Pin } from "./board";
import { reduceEvents } from "./investigation";
import type { Recording } from "./types";

const fiber = fiberCut as unknown as Recording;

function mark(id: string, tone: Mark["tone"], start = 0, open = false): Mark {
  return { id, lane: "alarms", refs: [id], origin: "T1", start, end: null, open, label: id, kindLabel: "Alarm", tone, rows: [], count: 1 };
}

describe("capMarks", () => {
  it("leaves a lane alone while it fits", () => {
    const marks = [mark("a", "minor"), mark("b", "crit")];
    expect(capMarks(marks, 12)).toEqual({ shown: marks, hidden: 0 });
  });

  it("keeps the most severe marks, in time order, and counts the rest", () => {
    const marks = [mark("m1", "minor", 1), mark("c1", "crit", 2), mark("m2", "minor", 3), mark("j1", "major", 4), mark("c2", "crit", 5), mark("m3", "minor", 6)];
    const { shown, hidden } = capMarks(marks, 3);
    expect(shown.map((m) => m.id)).toEqual(["c1", "j1", "c2"]);
    expect(hidden).toBe(3);
  });

  it("prefers marks that were never cleared among equals", () => {
    const marks = [mark("a", "minor", 1), mark("b", "minor", 2, true), mark("c", "minor", 3)];
    expect(capMarks(marks, 1).shown.map((m) => m.id)).toEqual(["b"]);
  });

  it("never drops the mark that is selected", () => {
    const marks = [mark("a", "crit", 1), mark("b", "crit", 2), mark("c", "minor", 3)];
    const { shown, hidden } = capMarks(marks, 2, "c");
    expect(shown.map((m) => m.id)).toContain("c");
    expect(shown).toHaveLength(2);
    expect(hidden).toBe(1);
  });
});

describe("markLabelWidth", () => {
  it("cuts a very long label and never asks for more than the board", () => {
    expect(markLabelWidth("x".repeat(400), 1200)).toBe(LABEL_MAX);
    expect(markLabelWidth("x".repeat(400), 200)).toBe(184);
    expect(markLabelWidth("Site down · S-TUN-012", 1200)).toBeLessThan(LABEL_MAX);
  });
});

describe("layoutPins", () => {
  const pin = (n: number, ms: number): Pin => ({ n, ms, time: "", event: "", refs: [] });
  const x = (ms: number) => ms / 1000;
  const noOverlap = (placed: ReturnType<typeof layoutPins>["placed"]) => {
    for (const row of [0, 1, 2]) {
      const xs = placed
        .filter((p) => p.row === row)
        .map((p) => p.px)
        .sort((a, b) => a - b);
      for (let i = 1; i < xs.length; i++) expect(xs[i] - xs[i - 1]).toBeGreaterThanOrEqual(PIN_SIZE);
    }
  };

  it("keeps a few pins on one line, pulled back from the edge", () => {
    const pins = [pin(1, 100_000), pin(2, 298_000), pin(3, 299_000), pin(4, 300_000)];
    const { placed, hidden, rows } = layoutPins(pins, x, 300);
    expect(rows).toBe(1);
    expect(hidden).toBe(0);
    expect(Math.max(...placed.map((p) => p.px))).toBeLessThanOrEqual(300 - PIN_SIZE / 2);
    noOverlap(placed);
  });

  it("wraps 25 pins at the same minute onto lines that stay inside a narrow board", () => {
    const pins = Array.from({ length: 25 }, (_, i) => pin(i + 1, 150_000));
    const { placed, hidden, rows } = layoutPins(pins, x, 300);
    expect(placed).toHaveLength(25);
    expect(hidden).toBe(0);
    expect(rows).toBeGreaterThan(1);
    expect(rows).toBeLessThanOrEqual(MAX_PIN_ROWS);
    for (const p of placed) {
      expect(p.px - PIN_SIZE / 2).toBeGreaterThanOrEqual(0);
      expect(p.px + PIN_SIZE / 2).toBeLessThanOrEqual(300);
    }
    noOverlap(placed);
  });

  it("counts the pins that do not fit on three lines instead of drawing them off the board", () => {
    const pins = Array.from({ length: 60 }, (_, i) => pin(i + 1, 10_000 + i));
    const { placed, hidden } = layoutPins(pins, x, 200);
    expect(placed.length + hidden).toBe(60);
    expect(hidden).toBeGreaterThan(0);
    for (const p of placed) expect(p.px + PIN_SIZE / 2).toBeLessThanOrEqual(200);
  });
});

describe("the cause flag", () => {
  it("does not say 'Cause: Cause unknown' when the agent found no cause", () => {
    const events = fiber.events.map((e) =>
      e.type === "report" || e.type === "run_finished"
        ? { ...e, data: { ...e.data, report: { ...(e.data as { report: object }).report, root_cause_category: "unknown", root_cause_node_id: null } } }
        : e,
    );
    const board = buildBoard(reduceEvents(events as Recording["events"]));
    expect(board.cause?.label).toBe("Cause unknown");
  });
});

describe("a KPI series with no values", () => {
  it("still gets a row, so the board can say there is no data", () => {
    const scope = fiber.events.findIndex((e) => e.type === "scope");
    const extra = [
      { seq: 90, run_id: "r", t_ms: 1, type: "tool_call", data: { ref: "T9", tool: "query_kpis", args: {}, node: "n", iteration: 0 } },
      {
        seq: 91,
        run_id: "r",
        t_ms: 2,
        type: "tool_result",
        data: {
          ref: "T9",
          tool: "query_kpis",
          headline: "x",
          error: null,
          n_refs: 0,
          truncated: false,
          wall_ms: 1,
          data: {
            chart: [
              {
                entity_type: "site",
                entity_id: "S-TUN-001",
                metric: "dl_volume_mb",
                unit: "MB",
                start: "2026-09-21T14:00:00Z",
                end: "2026-09-21T15:00:00Z",
                step_minutes: 15,
                values: [null, null, null, null],
                baseline: [null, null, null, null],
                baseline_available: false,
                deviation: null,
                clamped_to_now: false,
                note: null,
              },
            ],
          },
        },
      },
    ];
    const view = reduceEvents([...fiber.events.slice(0, scope + 1), ...extra] as Recording["events"]);
    const kpis = buildBoard(view).lanes.find((l) => l.def.id === "kpis")!.kpis;
    expect(kpis).toHaveLength(1);
    expect(kpis[0].series.values.every((v) => v === null)).toBe(true);
  });
});
