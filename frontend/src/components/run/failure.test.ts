import { describe, expect, it } from "vitest";
import { describeFailure, resetsIn } from "./failure";

describe("resetsIn", () => {
  it("says nothing when the wait is unknown", () => {
    expect(resetsIn(undefined)).toBe("");
    expect(resetsIn(0)).toBe("");
    expect(resetsIn(Number.NaN)).toBe("");
  });

  it("never says zero minutes", () => {
    expect(resetsIn(3)).toBe(", in under a minute");
    expect(resetsIn(59)).toBe(", in under a minute");
    expect(resetsIn(60)).toBe(", in about 1 min");
  });

  it("uses hours for a long wait", () => {
    expect(resetsIn(86_400)).toBe(", in about 24 h");
  });
});

describe("describeFailure", () => {
  it("groups the limit and the wait", () => {
    const d = describeFailure({
      kind: "limit",
      message: "",
      limit: 1_000_000,
      retryAfter: 3,
    });
    expect(d.body).toContain("(1,000,000)");
    expect(d.body).toContain("in under a minute");
    expect(d.body).not.toContain("0 min");
  });

  it("explains each kind in plain words", () => {
    for (const kind of ["unreachable", "limit", "disabled", "invalid", "not_found", "server", "dropped"] as const) {
      const d = describeFailure({ kind, message: "The reason." });
      expect(d.title.length).toBeGreaterThan(0);
      expect(d.body).not.toMatch(/undefined|null|NaN/);
    }
  });
});
