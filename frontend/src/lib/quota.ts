import type { Meta } from "./types";

type Counts = Pick<Meta, "live_remaining" | "live_daily_limit" | "live_client_remaining" | "live_client_limit">;

/** Live runs this visitor can still start today: the smaller of the shared and the personal allowance. */
export function liveQuota(meta: Counts): { left: number; limit: number } {
  const shared = Math.max(0, meta.live_remaining);
  const personal = Math.max(0, meta.live_client_remaining);
  return personal <= shared
    ? { left: personal, limit: meta.live_client_limit }
    : { left: shared, limit: meta.live_daily_limit };
}
