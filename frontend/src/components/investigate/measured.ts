import { rowBar } from "@/components/about/bars";
import type { ResultBlock } from "@/lib/results";

export interface Measured {
  /** "34 of 34" */
  verdict: string;
  /** "31 of 34" */
  cause: string;
}

/**
 * The first two rows of the agent's result block, as short counts for the home page. Nothing is returned
 * unless both rows hold a usable count, so the sentence is never built from a half-read figure.
 */
export function measured(results: readonly ResultBlock[]): Measured | null {
  const rows = results.find((block) => block.id === "agent")?.rows ?? [];
  const verdict = rows[0] ? rowBar(rows[0]) : null;
  const cause = rows[1] ? rowBar(rows[1]) : null;
  if (!verdict || !cause) return null;
  return {
    verdict: `${verdict.k} of ${verdict.n}`,
    cause: `${cause.k} of ${cause.n}`,
  };
}
