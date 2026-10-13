import { describe, expect, it } from "vitest";
import fiberCut from "./__fixtures__/fiber-cut.json";
import stadiumEvent from "./__fixtures__/stadium-event.json";
import { buildBoard, HOUR, isoToMs, lanesFromPhrase, localToMs, makeTicks, type LaneId } from "./board";
import { emptyView, reduceEvents } from "./investigation";
import type { Recording } from "./types";

const fiber = fiberCut as unknown as Recording;
const stadium = stadiumEvent as unknown as Recording;

function viewAfter(recording: Recording, count: number) {
  return reduceEvents(recording.events.slice(0, count));
}

/** The view just after the tool call with this reference has been sent, and before its result. */
function indexOf(recording: Recording, type: string, ref: string): number {
  return recording.events.findIndex((e) => e.type === type && (e.data as { ref?: string }).ref === ref);
}

function lane(view: ReturnType<typeof reduceEvents>, id: LaneId) {
  return buildBoard(view).lanes.find((l) => l.def.id === id)!;
}

describe("localToMs", () => {
  it("reads a Tunis local time as UTC minus one hour", () => {
    expect(localToMs("2026-09-21 16:50")).toBe(Date.UTC(2026, 8, 21, 15, 50));
    expect(localToMs("2026-09-22T00:29")).toBe(Date.UTC(2026, 8, 21, 23, 29));
  });

  it("crosses midnight and month ends", () => {
    expect(localToMs("2026-10-01 00:30")).toBe(Date.UTC(2026, 8, 30, 23, 30));
  });

  it("returns null for anything that is not a local time", () => {
    expect(localToMs(null)).toBeNull();
    expect(localToMs("yesterday")).toBeNull();
    expect(localToMs(12)).toBeNull();
  });

  it("agrees with an ISO instant that is one hour earlier in UTC", () => {
    expect(localToMs("2026-09-21 16:50")).toBe(isoToMs("2026-09-21T15:50:00+00:00"));
    expect(HOUR).toBe(3_600_000);
  });
});

describe("lane states over a run", () => {
  it("starts with every lane blank", () => {
    const board = buildBoard(emptyView);
    expect(board.lanes.map((l) => l.state)).toEqual(Array(6).fill("idle"));
    expect(board.domain).toBeNull();
  });

  it("marks a lane as checking while its call is running, then as found", () => {
    const sent = indexOf(fiber, "tool_call", "T1") + 1;
    expect(lane(viewAfter(fiber, sent), "alerts").state).toBe("checking");
    const answered = indexOf(fiber, "tool_result", "T1") + 1;
    expect(lane(viewAfter(fiber, answered), "alerts").state).toBe("found");
    expect(lane(viewAfter(fiber, answered), "alarms").state).toBe("idle");
  });

  it("marks a lane that was checked and had nothing as clear", () => {
    const view = reduceEvents(fiber.events);
    expect(lane(view, "maintenance").state).toBe("clear");
    expect(lane(view, "maintenance").spans.length).toBeGreaterThan(0);
    expect(lane(view, "events").state).toBe("clear");
  });

  it("finds alarms and changes in the fibre cut", () => {
    const view = reduceEvents(fiber.events);
    expect(lane(view, "alarms").state).toBe("found");
    expect(lane(view, "alarms").marks.length).toBeGreaterThan(0);
    expect(["found", "clear"]).toContain(lane(view, "changes").state);
  });

  it("points at the lanes the completeness check named while they are still blank", () => {
    const gate = fiber.events.findIndex((e) => e.type === "gate");
    const board = buildBoard(viewAfter(fiber, gate + 1));
    expect(board.missing.has("events")).toBe(true);
    const done = buildBoard(reduceEvents(fiber.events));
    expect(done.missing.has("events")).toBe(false);
  });
});

describe("the conclusion", () => {
  it("puts the fibre alarm and the report's cause on the same instant", () => {
    const view = reduceEvents(fiber.events);
    const board = buildBoard(view);
    expect(board.cause).not.toBeNull();
    const raised = lane(view, "alarms").marks.map((m) => m.start);
    expect(raised).toContain(board.cause!.ms);
    expect(board.cause!.ms).toBe(Date.UTC(2026, 8, 21, 15, 50));
  });

  it("holds the impact window and one pin per timeline entry", () => {
    const view = reduceEvents(fiber.events);
    const board = buildBoard(view);
    expect(board.impact).toEqual({ a: localToMs("2026-09-21 16:50"), b: localToMs("2026-09-22 00:29") });
    expect(board.pins.map((p) => p.n)).toEqual(view.report!.timeline.map((_, i) => i + 1));
    expect(board.verdict).toBe("incident");
  });

  it("keeps the axis around everything that is shown", () => {
    const board = buildBoard(reduceEvents(fiber.events));
    const { domain, impact, cause } = board;
    expect(domain!.a).toBeLessThan(impact!.a);
    expect(domain!.b).toBeGreaterThan(impact!.b);
    expect(cause!.ms).toBeGreaterThan(domain!.a);
  });

  it("words the conclusion by the verdict", () => {
    const board = buildBoard(reduceEvents(stadium.events));
    expect(board.verdict).toBe("expected_event");
    expect(board.cause!.label.startsWith("Explained by")).toBe(true);
    expect(board.legend.cause).toBe("Explained by");
  });
});

describe("the KPI lane", () => {
  it("has a row for every series the agent queried, deviating series first", () => {
    const view = reduceEvents(stadium.events);
    const kpis = lane(view, "kpis");
    expect(kpis.state).toBe("found");
    expect(kpis.kpis.length).toBeGreaterThan(0);
    const flags = kpis.kpis.map((k) => Boolean(k.series.deviation));
    expect(flags).toEqual([...flags].sort((a, b) => Number(b) - Number(a)));
    expect(kpis.spans.length).toBeGreaterThan(0);
  });

  it("gives topology and runbook searches a context row instead of a lane", () => {
    const board = buildBoard(reduceEvents(stadium.events));
    expect(board.context.map((c) => c.kind)).toEqual(expect.arrayContaining(["topology", "runbooks"]));
  });
});

describe("lanesFromPhrase", () => {
  it("maps the words of a completeness check to lanes", () => {
    expect(lanesFromPhrase("the external events calendar")).toEqual(["events"]);
    expect(lanesFromPhrase("the change log")).toEqual(["changes"]);
    expect(lanesFromPhrase("maintenance windows")).toEqual(["maintenance"]);
    expect(lanesFromPhrase("active alarms")).toEqual(["alarms"]);
    expect(lanesFromPhrase("detector anomalies")).toEqual(["alerts"]);
    expect(lanesFromPhrase("KPI trends")).toEqual(["kpis"]);
  });

  it("returns nothing for words it does not know", () => {
    expect(lanesFromPhrase("the weather")).toEqual([]);
  });
});

describe("makeTicks", () => {
  const day = { a: Date.UTC(2026, 8, 21, 9, 0), b: Date.UTC(2026, 8, 21, 20, 0) };

  it("never places ticks closer than the minimum gap", () => {
    for (const width of [200, 320, 520, 760, 1060]) {
      for (const gap of [52, 64, 70]) {
        const ticks = makeTicks(day, width, gap);
        for (let i = 1; i < ticks.length; i++) {
          const px = ((ticks[i].ms - ticks[i - 1].ms) / (day.b - day.a)) * width;
          expect(px).toBeGreaterThanOrEqual(gap);
        }
      }
    }
  });

  it("puts ticks on whole local hours and prints the date on the first one", () => {
    const ticks = makeTicks(day, 760, 70);
    expect(ticks[0].label).toMatch(/^\d{2}:00$/);
    expect(ticks[0].date).toBe("21 Sep");
    expect(ticks.slice(1).every((t) => t.date === null)).toBe(true);
  });

  it("prints the new date at midnight", () => {
    const span = { a: Date.UTC(2026, 8, 21, 21, 0), b: Date.UTC(2026, 8, 22, 3, 0) };
    const ticks = makeTicks(span, 760, 70);
    const midnight = ticks.find((t) => t.label === "00:00");
    expect(midnight?.date).toBe("22 Sep");
  });
});
