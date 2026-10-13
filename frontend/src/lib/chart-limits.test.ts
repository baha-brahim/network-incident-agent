import { describe, expect, it } from "vitest";
import { chartCaption, pctText } from "./chart";
import type { KpiSeries } from "./types";

describe("pctText", () => {
  it("signs the value and rounds it", () => {
    expect(pctText(92.9)).toBe("+93%");
    expect(pctText(-42.4)).toBe("-42%");
    expect(pctText(0)).toBe("0%");
  });

  it("caps values that would overrun a label and drops values that are not numbers", () => {
    expect(pctText(1_000_000)).toBe("over +999%");
    expect(pctText(-5000)).toBe("under -999%");
    expect(pctText(Number.NaN)).toBe("");
  });
});

describe("chartCaption with an extreme deviation", () => {
  it("uses the capped wording", () => {
    const series = {
      entity_type: "site",
      entity_id: "S-TUN-001",
      metric: "dl_volume_mb",
      unit: "MB",
      start: "2026-09-21T14:00:00Z",
      end: "2026-09-21T15:00:00Z",
      step_minutes: 15,
      values: [1, 2],
      baseline: [1, 1],
      baseline_available: true,
      deviation: { direction: "above", onset: "2026-09-21T14:15:00Z", recovery: null, ongoing: true, began_before_window: false },
      clamped_to_now: false,
      note: null,
    } as unknown as KpiSeries;
    expect(chartCaption(series, 2_500_000)).toContain("over +999% on average");
  });
});
