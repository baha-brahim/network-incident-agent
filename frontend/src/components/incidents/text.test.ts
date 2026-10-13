import { describe, expect, it } from "vitest";
import { alertSpan, clock, counted, firstNames, humanize, scoreText, secondsText, sentenceCase } from "./text";

const at = (iso: string) => Date.parse(iso);

describe("humanize", () => {
  it("turns a server word into plain words", () => {
    expect(humanize("alien_cause")).toBe("alien cause");
    expect(humanize("  a__b  ")).toBe("a b");
    expect(sentenceCase("alien cause")).toBe("Alien cause");
    expect(sentenceCase("")).toBe("");
  });
});

describe("clock", () => {
  it("shows a placeholder, never NaN, for a date that cannot be read", () => {
    expect(clock(Number.NaN)).toBe("--:--");
    expect(clock(at("2026-09-30T19:59:00Z"))).toBe("20:59");
  });
});

describe("secondsText", () => {
  it("covers the very short and the very long", () => {
    expect(secondsText(0)).toBe("under 0.1 s");
    expect(secondsText(0.004)).toBe("under 0.1 s");
    expect(secondsText(12.34)).toBe("12.3 s");
    expect(secondsText(86_400)).toBe("24 h");
    expect(secondsText(Number.NaN)).toBe("");
    expect(secondsText(-1)).toBe("");
  });
});

describe("alertSpan", () => {
  const start = at("2026-09-30T19:15:00Z");
  it("gives the end and the length", () => {
    expect(alertSpan(start, at("2026-09-30T22:00:00Z"))).toBe("until 23:00 · 2 h 45 min");
  });
  it("names the day when the alert crosses midnight, and counts days for a long one", () => {
    expect(alertSpan(start, at("2026-10-01T05:00:00Z"))).toBe("until 1 Oct, 06:00 · 9 h 45 min");
    expect(alertSpan(start, at("2026-10-09T19:15:00Z"))).toBe("until 9 Oct, 20:15 · 9 days");
  });
  it("is plain about an end before the start or a date that cannot be read", () => {
    expect(alertSpan(start, at("2026-09-21T19:00:00Z"))).toBe("ends before it starts");
    expect(alertSpan(start, Number.NaN)).toBe("window unclear");
  });
});

describe("small helpers", () => {
  it("cuts a long list and says how many were left out", () => {
    expect(firstNames(["a", "b", "c", "d"], 3)).toEqual({
      shown: ["a", "b", "c"],
      more: 1,
    });
    expect(firstNames(["a"], 3)).toEqual({ shown: ["a"], more: 0 });
  });
  it("uses the right plural", () => {
    expect(counted(1, "anomaly", "anomalies")).toBe("1 anomaly");
    expect(counted(0, "anomaly", "anomalies")).toBe("0 anomalies");
    expect(counted(1200, "anomaly", "anomalies")).toBe("1,200 anomalies");
  });
  it("groups the thousands of a score", () => {
    expect(scoreText(9.21)).toBe("9.2");
    expect(scoreText(1_000_000)).toBe("1,000,000.0");
    expect(scoreText(Number.NaN)).toBe("unknown");
  });
});
