import { describe, expect, it } from "vitest";
import fiberCut from "@/lib/__fixtures__/fiber-cut.json";
import { buildBoard } from "@/lib/board";
import { emptyView } from "@/lib/investigation";
import type { Recording, RunEvent } from "@/lib/types";
import { INTRO_MS, MAX_GAP_MS, previewFrames } from "./preview-frames";
import { IDLE_LINE, previewLine } from "./preview-line";

const events = (fiberCut as unknown as Recording).events;

describe("previewFrames", () => {
  it("stops at the first completeness check and never applies the answer", () => {
    const frames = previewFrames(events);
    const gate = events.findIndex((e) => e.type === "gate");
    expect(frames).toHaveLength(gate + 1);
    const last = frames.at(-1)!.view;
    expect(last.steps.at(-1)?.kind).toBe("gate");
    expect(last.report).toBeNull();
    expect(last.phase).toBe("running");
  });

  it("stops before the report when there is no completeness check", () => {
    const withoutGate = events.filter((e) => e.type !== "gate");
    const frames = previewFrames(withoutGate);
    const report = withoutGate.findIndex((e) => e.type === "report");
    expect(frames).toHaveLength(report);
    expect(frames.every((f) => f.view.report === null)).toBe(true);
  });

  it("uses the recorded gaps, capped, with a fixed first pause", () => {
    const slow: RunEvent[] = events.map((e, i) => ({ ...e, t_ms: i * 10_000 }));
    const frames = previewFrames(slow);
    expect(frames[0].delay).toBe(INTRO_MS);
    expect(frames.slice(1).every((f) => f.delay === MAX_GAP_MS)).toBe(true);
  });

  it("gives nothing for an empty recording", () => {
    expect(previewFrames([])).toEqual([]);
  });
});

describe("previewLine", () => {
  it("describes the blank board, then what each step found", () => {
    expect(previewLine(emptyView, buildBoard(emptyView))).toBe(IDLE_LINE);
    const lines = previewFrames(events).map((f) => previewLine(f.view, buildBoard(f.view)));
    expect(lines).toContain("Nothing in the change log.");
    expect(lines.at(-1)).toBe("Not yet checked: external events. The agent is sent back.");
  });
});
