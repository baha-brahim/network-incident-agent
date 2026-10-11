import { describe, expect, it } from "vitest";
import stadium from "./__fixtures__/stadium-event.json";
import { chartAlt, chartCaption, extractChart, extractDeviationPct, layoutChart, niceTicks } from "./chart";
import type { Recording } from "./types";

const events = (stadium as unknown as Recording).events;
const kpi = events.find((e) => e.type === "tool_result" && e.data.tool === "query_kpis");
const data = kpi && kpi.type === "tool_result" ? kpi.data.data : null;

describe("charts from a recorded KPI query", () => {
  const series = extractChart(data);

  it("finds the series and rejects malformed input", () => {
    expect(series.length).toBeGreaterThan(3);
    expect(extractChart(null)).toEqual([]);
    expect(extractChart({ chart: [{ nope: 1 }] })).toEqual([]);
  });

  it("lays out lines, ticks in local time and the deviation marks", () => {
    const first = series[0];
    const layout = layoutChart(first, 480, 160);
    expect(layout.actualPath.startsWith("M")).toBe(true);
    expect(layout.baselinePath.startsWith("M")).toBe(true);
    expect(layout.xTicks.length).toBeGreaterThanOrEqual(2);
    // The series starts at 17:00 UTC, which is 18:00 in Tunis.
    expect(layout.xTicks[0].label).toBe("18:00");
    expect(layout.deviation).not.toBeNull();
    const dev = layout.deviation!;
    expect(dev.onsetLabel).toContain("18:15");
    expect(dev.recoveryLabel).toContain("21:45");
    expect(dev.x1).toBeLessThan(dev.x2);
    for (const t of layout.yTicks) expect(t.y).toBeGreaterThanOrEqual(layout.plot.y - 0.5);
  });

  it("describes the chart in words", () => {
    const pct = extractDeviationPct(data).get(`${series[0].entity_id}|${series[0].metric}`);
    expect(pct).toBeGreaterThan(0);
    expect(chartCaption(series[0], pct)).toMatch(/Above its usual level from 18:15 until 21:45 \(\+\d+% on average\)/);
    const alt = chartAlt(series[0], pct);
    expect(alt).toContain(series[0].entity_id);
    expect(alt).toContain("Tunis time");
    expect(alt).toContain("dashed line is the baseline");
  });

  it("breaks the line where values are missing", () => {
    const gap = { ...series[0], values: series[0].values.map((v, i) => (i === 5 ? null : v)) };
    expect(layoutChart(gap, 480, 160).actualPath.match(/M/g)).toHaveLength(2);
  });
});

describe("niceTicks", () => {
  it("returns round values inside the range", () => {
    expect(niceTicks(0, 100, 3)).toEqual([0, 50, 100]);
    expect(niceTicks(0.4, 2.6, 3)).toEqual([1, 2]);
  });
});
