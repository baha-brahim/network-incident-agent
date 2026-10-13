import { describe, expect, it } from "vitest";
import { RESULTS } from "@/lib/results";
import { rowBar } from "./bars";

describe("rowBar", () => {
  it("reads a count and its interval", () => {
    expect(rowBar({ value: "31 of 34 (91%)", note: "95% interval 77% to 97%" })).toEqual({ k: 31, n: 34, interval: { low: 77, high: 97 } });
  });

  it("accepts a count that fills the whole bar", () => {
    expect(rowBar({ value: "134 of 134 (100%)" })).toEqual({ k: 134, n: 134, interval: undefined });
    expect(rowBar({ value: "0 of 34" })).toEqual({ k: 0, n: 34, interval: undefined });
  });

  it("accepts the widest interval", () => {
    expect(rowBar({ value: "1 of 2", note: "95% interval 0% to 100%" })?.interval).toEqual({ low: 0, high: 100 });
  });

  it("reads thousands separators", () => {
    expect(rowBar({ value: "1,200 of 1,500" })).toMatchObject({ k: 1200, n: 1500 });
  });

  it("draws no bar for an empty or impossible count", () => {
    expect(rowBar({ value: "0 of 0" })).toBeNull();
    expect(rowBar({ value: "5 of 2" })).toBeNull();
  });

  it("draws no bar for a value that is not a count", () => {
    expect(rowBar({ value: "0.85" })).toBeNull();
    expect(rowBar({ value: "28,414" })).toBeNull();
    expect(rowBar({ value: "A result that is thirty chars" })).toBeNull();
    expect(rowBar({ value: "" })).toBeNull();
  });

  it("leaves out a missing, reversed or out-of-range interval but keeps the bar", () => {
    expect(rowBar({ value: "3 of 4" })?.interval).toBeUndefined();
    expect(rowBar({ value: "3 of 4", note: "no interval here" })?.interval).toBeUndefined();
    expect(rowBar({ value: "3 of 4", note: "95% interval 80% to 20%" })?.interval).toBeUndefined();
    expect(rowBar({ value: "3 of 4", note: "95% interval 10% to 140%" })?.interval).toBeUndefined();
  });
});

describe("the published results", () => {
  const rows = RESULTS.flatMap((block) => block.rows);

  it("give every count a bar, and every interval named in a note is drawn", () => {
    for (const row of rows) {
      if (/^\d+ of \d+/.test(row.value)) {
        const bar = rowBar(row);
        expect(bar, row.metric).not.toBeNull();
        if (row.note?.includes("95% interval")) expect(bar?.interval, row.metric).toBeDefined();
      }
    }
  });

  it("have a title, a dataset, at least one row and no empty cells", () => {
    for (const block of RESULTS) {
      expect(block.title.length).toBeGreaterThan(0);
      expect(block.dataset.length).toBeGreaterThan(0);
      expect(block.rows.length).toBeGreaterThan(0);
      for (const row of block.rows) {
        expect(row.metric.trim()).not.toBe("");
        expect(row.value.trim()).not.toBe("");
      }
    }
  });
});
