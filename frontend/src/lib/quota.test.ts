import { describe, expect, it } from "vitest";
import { liveQuota } from "./quota";

const counts = (shared: number, personal: number) => ({
  live_remaining: shared,
  live_daily_limit: 20,
  live_client_remaining: personal,
  live_client_limit: 3,
});

describe("liveQuota", () => {
  it("shows the personal allowance when it is the smaller", () => {
    expect(liveQuota(counts(17, 2))).toEqual({ left: 2, limit: 3 });
  });

  it("shows the shared allowance when it is the smaller", () => {
    expect(liveQuota(counts(1, 3))).toEqual({ left: 1, limit: 20 });
  });

  it("is used up when either allowance is", () => {
    expect(liveQuota(counts(0, 3)).left).toBe(0);
    expect(liveQuota(counts(10, 0)).left).toBe(0);
  });

  it("never goes below zero", () => {
    expect(liveQuota(counts(-2, 1))).toEqual({ left: 0, limit: 20 });
  });
});
