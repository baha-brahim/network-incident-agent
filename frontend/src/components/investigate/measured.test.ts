import { describe, expect, it } from "vitest";
import { RESULTS, type ResultBlock } from "@/lib/results";
import { measured } from "./measured";

const block = (...values: string[]): ResultBlock[] => [
  {
    id: "agent",
    title: "t",
    dataset: "d",
    datasetTone: "caution",
    caveats: [],
    rows: values.map((value, i) => ({ metric: `m${i}`, value })),
  },
];

describe("measured", () => {
  it("reads the two counts of the shipped results", () => {
    const m = measured(RESULTS);
    expect(m).not.toBeNull();
    expect(m?.verdict).toMatch(/^\d+ of \d+$/);
    expect(m?.cause).toMatch(/^\d+ of \d+$/);
  });

  it("keeps each count's own total", () => {
    expect(measured(block("34 of 34", "31 of 33 (94%)"))).toEqual({
      verdict: "34 of 34",
      cause: "31 of 33",
    });
  });

  it("returns nothing when a row is missing, empty or impossible", () => {
    expect(measured([])).toBeNull();
    expect(measured(block("34 of 34"))).toBeNull();
    expect(measured(block("0 of 0", "1 of 2"))).toBeNull();
    expect(measured(block("5 of 2", "1 of 2"))).toBeNull();
    expect(measured(block("fine", "1 of 2"))).toBeNull();
  });
});
