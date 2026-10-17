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
    dataset: "Two held-out worlds (seeds 7 and 8): 68 planted scenarios, one run each. Neither world was looked at while the agent was written.",
    datasetTone: "held-out",
    rows: [
      { metric: "Right verdict (incident, maintenance, event or no impact)", value: "68 of 68", note: "95% interval 95% to 100%" },
      { metric: "Right cause and right node, exact", value: "63 of 68 (93%)", note: "95% interval 84% to 97%" },
      { metric: "Right cause, a peer node accepted", value: "68 of 68 (100%)", note: "Several equal sites share some causes; the label names one" },
      { metric: "High confidence and wrong", value: "0 of 68", note: "39 reports said high confidence; all were right" },
      { metric: "Claims supported by the evidence they cite", value: "0.91 and 0.92", note: "Faithfulness on seeds 7 and 8, judged claim by claim by a grader model" },
      { metric: "Tokens per investigation, median", value: "24,160", note: "95th percentile 34,177" },
      { metric: "Model and tool time, median", value: "33.8 s", note: "95th percentile 90.6 s, without the free-tier pauses between calls" },
    ],
    caveats: [
      "34 scenarios per world is a small sample: one case moves a rate by about 3 points, and the intervals are wide.",
      "Each case was run once; the variation between runs of the same case is not measured.",
      "The grader model was checked against a second model, not against a person.",
      "The network, incidents and runbooks are synthetic, from the same simulator. Planted effects are large compared with the noise.",
    ],
  },
  {
    id: "agent-hard",
    title: "And when the evidence is built to mislead?",
    dataset: "A held-out hard world (seed 202): 34 scenarios built around look-alikes, such as a maintenance window that only nearly covers an outage, a match day next to an unrelated congestion, or a harmless change on the failing node.",
    datasetTone: "held-out",
    rows: [
      { metric: "Right verdict", value: "33 of 34", note: "95% interval 85% to 99%" },
      { metric: "Right cause, a peer node accepted", value: "27 of 34 (79%)", note: "95% interval 63% to 90%" },
      { metric: "High confidence and wrong", value: "2 of 34", note: "6 of 34 before the look-alike checks of the verify step" },
      { metric: "Right before the look-alike checks", value: "23 of 34", note: "The checks fired on 7 cases: 4 became right, none became wrong" },
      { metric: "Right with the completeness gate off", value: "22 of 34", note: "The gate costs about 6,000 tokens per investigation" },
      { metric: "Claims supported by the evidence they cite", value: "0.88" },
    ],
    caveats: [
      "The look-alike checks were developed on another hard world (seed 101), where they fixed 7 of 9 flagged cases; on this one they fixed 4 of 7.",
      "Of the 7 wrong answers, 4 were never flagged by a check, and 3 were flagged but corrected to another wrong cause.",
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
