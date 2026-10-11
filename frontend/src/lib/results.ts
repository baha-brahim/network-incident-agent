/**
 * Measured results shown on the "How it works" page. Every figure is copied from the evaluation and
 * detector result pages of the repository; when those are regenerated, update this file with them.
 */

export interface ResultRow {
  metric: string;
  value: string;
  note?: string;
}

export interface ResultBlock {
  id: string;
  title: string;
  dataset: string;
  datasetTone: "caution" | "held-out";
  rows: ResultRow[];
  caveats: string[];
}

export const RESULTS: ResultBlock[] = [
  {
    id: "agent",
    title: "Does the agent find the right cause?",
    dataset: "Development world (seed 42): 34 planted scenarios, one run each. The prompts were written while looking at this world, so these figures are optimistic.",
    datasetTone: "caution",
    rows: [
      { metric: "Right verdict (incident, maintenance, event or no impact)", value: "34 of 34", note: "95% interval 90% to 100%" },
      { metric: "Right cause and right node, exact", value: "31 of 34 (91%)", note: "95% interval 77% to 97%" },
      { metric: "Right cause, a peer node accepted", value: "34 of 34 (100%)", note: "Several equal sites share some causes; the label names one" },
      { metric: "High confidence and wrong", value: "0 of 34", note: "26 reports said high confidence; all were right" },
      { metric: "Planted evidence found", value: "0.85", note: "Share of the planted alarms, changes and events that appeared in a tool result" },
      { metric: "Tokens per investigation, median", value: "28,414", note: "95th percentile 35,399" },
      { metric: "Model and tool time, median", value: "11.2 s", note: "95th percentile 14.1 s; model calls 7, tool calls 8 (medians)" },
    ],
    caveats: [
      "There is no test-world run yet. The held-out world (seed 7) has not been scored, so no figure here is a clean estimate of performance on something new.",
      "34 scenarios is a small sample: one case moves a rate by about 3 points, and the intervals are wide.",
      "Whether each claim is supported by the evidence it cites has not been measured yet.",
      "The network, incidents and runbooks are synthetic, from the same simulator. Planted effects are large compared with the noise.",
    ],
  },
  {
    id: "detector",
    title: "Does the anomaly detector notice them?",
    dataset: "Three held-out worlds (seeds 1, 2 and 3), pooled. The detector's thresholds were chosen on the development world only.",
    datasetTone: "held-out",
    rows: [
      { metric: "Detectable scenarios detected", value: "93 of 93", note: "Including 72 of 72 real incidents" },
      { metric: "Precision, red herrings counted as correct", value: "0.76", note: "0.59 counting only real incidents" },
      { metric: "Alerts per day, whole country", value: "1.4" },
      { metric: "Alert start versus incident start, median", value: "-2 min", note: "90th percentile 16 min" },
    ],
    caveats: [
      "The planted effects are large compared with the simulated noise, so 100% recall says as much about the data as about the detector.",
      "30 alerts matched no scenario; most are single-site latency swings on the busiest sites in the evening.",
      "The baseline is computed from the same 30 days it scores. A live system could not see the future days.",
    ],
  },
];
