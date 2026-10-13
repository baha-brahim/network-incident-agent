import { describe, expect, it } from "vitest";
import { aboutSeconds, demoMeta, toolCalls } from "./demo-text";
import type { DemoSummary } from "@/lib/types";

const ms = (duration_ms: number) => ({ duration_ms });

describe("aboutSeconds", () => {
  it("says under a second for zero and for anything shorter than a second", () => {
    expect(aboutSeconds(ms(0))).toBe("under 1 s");
    expect(aboutSeconds(ms(400))).toBe("under 1 s");
    expect(aboutSeconds(ms(Number.NaN))).toBe("under 1 s");
  });

  it("rounds seconds, then switches to minutes and hours", () => {
    expect(aboutSeconds(ms(1499))).toBe("about 1 s");
    expect(aboutSeconds(ms(12_326))).toBe("about 12 s");
    expect(aboutSeconds(ms(119_000))).toBe("about 119 s");
    expect(aboutSeconds(ms(3_600_000))).toBe("about 60 min");
    expect(aboutSeconds(ms(10_800_000))).toBe("about 3 h");
  });
});

describe("toolCalls", () => {
  it("uses the right plural and groups thousands", () => {
    expect(toolCalls(0)).toBe("0 tool calls");
    expect(toolCalls(1)).toBe("1 tool call");
    expect(toolCalls(9999)).toBe("9,999 tool calls");
  });
});

describe("demoMeta", () => {
  it("joins the call count and the length", () => {
    const demo = {
      duration_ms: 12_326,
      counts: { events: 28, llm_calls: 7, tool_calls: 7 },
    } as DemoSummary;
    expect(demoMeta(demo)).toBe("7 tool calls · about 12 s");
  });
});
