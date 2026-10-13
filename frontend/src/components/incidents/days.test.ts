import { describe, expect, it } from "vitest";
import { UNKNOWN_DAY, dayOf, groupByDay, newestFirst } from "./days";

const at = (iso: string) => Date.parse(iso);

describe("dayOf", () => {
  it("reads the day in network time, which is one hour ahead of UTC", () => {
    expect(dayOf(at("2026-09-30T23:30:00Z")).key).toBe("2026-10-01");
    expect(dayOf(at("2026-09-30T22:30:00Z")).key).toBe("2026-09-30");
  });

  it("has a day for a time that could not be read", () => {
    expect(dayOf(Number.NaN)).toBe(UNKNOWN_DAY);
    expect(UNKNOWN_DAY.date).not.toMatch(/NaN|undefined/);
  });
});

describe("newestFirst", () => {
  it("sorts by time, newest first, and puts unreadable times last", () => {
    const items = [{ time: Number.NaN }, { time: 1 }, { time: 3 }, { time: Number.NaN }, { time: 2 }];
    expect(items.sort(newestFirst).map((i) => i.time)).toEqual([3, 2, 1, Number.NaN, Number.NaN]);
  });
});

describe("groupByDay", () => {
  it("makes one group per day, so no day appears twice", () => {
    const items = [
      { time: at("2026-09-30T10:00:00Z") },
      { time: Number.NaN },
      { time: at("2026-09-29T10:00:00Z") },
      { time: at("2026-09-30T09:00:00Z") },
      { time: Number.NaN },
    ].sort(newestFirst);
    const keys = groupByDay(items).map((g) => g.day.key);
    expect(keys).toEqual(["2026-09-30", "2026-09-29", "unknown"]);
    expect(new Set(keys).size).toBe(keys.length);
  });
});
