# Evaluation of the investigation agent

This page measures whether the agent finds the *right* cause of a network incident. The synthetic network contains planted incidents and red herrings with known labels, so everything below that can be scored in code is scored in code, from those labels. A grader model is used only for one thing code cannot judge: whether each claim in a report is supported by the evidence it cites.

Two worlds are used. **Seed 42 is the dev world**: the prompts were written while looking at it, so its numbers are optimistic. **Seed 7 is the test world**: never looked at and never tuned on. Headline numbers come from the test world.

> **No test-world run is included yet.** Every number here comes from the dev world and is optimistic.

## Runs

| run | world | variant | model | cases scored | infrastructure errors | other model answered a step |
|---|---|---|---|---|---|---|
| baseline-dev | seed 42 (dev) | default | `gemini:gemini-3.5-flash-lite` | 34 of 34 | 0 | 1 |

A case is one scenario with its first question. An *infrastructure error* (quota, outage, crash) is not a wrong answer: it is left out of every figure and retried on a later run. A run uses the primary model only, with no fallback chain; where the saved response of a step shows a different model answered, the case is flagged above.

## Headline

- `baseline-dev`: dev world: the prompts were developed on it, so these numbers are optimistic.

| metric | baseline-dev (dev) |
|---|---|
| cases scored | 34 |
| verdict correct | 34/34 (100%) [90% to 100%] |
| category correct | 34/34 (100%) [90% to 100%] |
| category in top 3 | 34/34 (100%) [90% to 100%] |
| node exact | 31/34 (91%) [77% to 97%] |
| **root cause, strict** | 31/34 (91%) [77% to 97%] |
| **root cause, lenient** | 34/34 (100%) [90% to 100%] |
| abstained | 0/34 (0%) [0% to 10%] |
| high confidence and wrong | 0/34 (0%) [0% to 10%] |

Each cell is successes/cases (share) and a 95% Wilson interval. With few cases the intervals are wide: 11 of 11 correct is compatible with a true rate as low as 74%.

## What the metrics mean

| metric | definition |
|---|---|
| verdict correct | The report's classification equals the planted one: `incident`, or for the red herrings `planned_maintenance`, `expected_event`, `no_impact`. `inconclusive` is never correct. |
| category correct | `root_cause_category` equals the planted category. |
| category in top 3 | The planted category is the stated root cause or among the first three ranked hypotheses. |
| node exact / acceptable / related / wrong | How the stated root-cause node compares with the label. `exact`: the same node. `acceptable`: a peer the label could equally have named (rules below). `related`: an ancestor or descendant of the labelled node. `wrong`: anything else, including no node. |
| root cause, strict | Verdict, category and node all correct, with node `exact`. |
| root cause, lenient | The same, with node `exact` or `acceptable`. This is the headline accuracy. |
| abstained | The report is `inconclusive`. Counted as wrong for accuracy, and shown separately. |
| high confidence and wrong | The report says `high` confidence and the lenient root cause is not right. The worst failure. |
| impact start / cause time error | Absolute difference in minutes between the reported time and the planted one. Empty when the report gives no time. |
| evidence found / cited | Of the planted evidence rows (alarms, changes, events, maintenance windows) that existed at the time of the question, the share that appeared in a tool result / that the report cites by id. |
| confounder outcome | For cases with a planted harmless look-alike (a change or alarm just before the incident): `dismissed` (listed under dismissed signals), `blamed` (cited by the confirmed hypothesis or named in the root-cause summary), `seen_ignored` (shown by a tool, never addressed), `not_seen`. |
| tool precision / recall | Distinct tools the model chose to call (the code-driven first lookups are excluded) against the tools expected for the scenario. |
| citation issues / repaired | Problems the verification step found in the first draft (unknown references, bad times, wrong node ids), and whether a repair call was needed. |
| faithfulness | Share of the report's claims that the cited evidence supports, judged by a grader model (see below). |

### Which node counts as the right one

- Peers (`acceptable`) exist only for `config_push`, `congestion`, `stadium_event`: a cause that hits several equal nodes (the sites of a pushed group, two congested sites, the sites around a venue), where the label names one of them. Any other affected node counts. A configuration push to a router is labelled with the router, so its sites are not peers.
- Every other kind has a single labelled node (the link of a fibre cut or microwave degradation, the site of a power outage or alarm storm, the DNS node, the node a maintenance window concerns): only that node is `exact`.
- The public holiday has no node. A report with no node is `exact`; naming a node is `wrong`.
- `related` means the named node is an ancestor or descendant of the label in the dependency tree (site, link, router, core). It is not counted as correct.

## Breakdown: baseline-dev (dev)

(dev world: the prompts were developed on it, so these numbers are optimistic.)

**By scenario kind**

| group | cases | verdict | category | root cause, strict | root cause, lenient | abstained |
|---|---|---|---|---|---|---|
| alarm_storm | 3 | 3/3 (100%) | 3/3 (100%) | 3/3 (100%) | 3/3 (100%) | 0/3 (0%) |
| config_push | 5 | 5/5 (100%) | 5/5 (100%) | 4/5 (80%) | 5/5 (100%) | 0/5 (0%) |
| congestion | 4 | 4/4 (100%) | 4/4 (100%) | 4/4 (100%) | 4/4 (100%) | 0/4 (0%) |
| dns_degradation | 3 | 3/3 (100%) | 3/3 (100%) | 3/3 (100%) | 3/3 (100%) | 0/3 (0%) |
| fiber_cut | 4 | 4/4 (100%) | 4/4 (100%) | 4/4 (100%) | 4/4 (100%) | 0/4 (0%) |
| link_degradation | 4 | 4/4 (100%) | 4/4 (100%) | 4/4 (100%) | 4/4 (100%) | 0/4 (0%) |
| planned_maintenance | 3 | 3/3 (100%) | 3/3 (100%) | 3/3 (100%) | 3/3 (100%) | 0/3 (0%) |
| power_outage | 4 | 4/4 (100%) | 4/4 (100%) | 4/4 (100%) | 4/4 (100%) | 0/4 (0%) |
| public_holiday | 1 | 1/1 (100%) | 1/1 (100%) | 1/1 (100%) | 1/1 (100%) | 0/1 (0%) |
| stadium_event | 3 | 3/3 (100%) | 3/3 (100%) | 1/3 (33%) | 3/3 (100%) | 0/3 (0%) |

**By difficulty**

| group | cases | verdict | category | root cause, strict | root cause, lenient | abstained |
|---|---|---|---|---|---|---|
| easy | 14 | 14/14 (100%) | 14/14 (100%) | 12/14 (86%) | 14/14 (100%) | 0/14 (0%) |
| hard | 7 | 7/7 (100%) | 7/7 (100%) | 7/7 (100%) | 7/7 (100%) | 0/7 (0%) |
| medium | 13 | 13/13 (100%) | 13/13 (100%) | 12/13 (92%) | 13/13 (100%) | 0/13 (0%) |

**Real incidents and red herrings**

| group | cases | verdict | category | root cause, strict | root cause, lenient | abstained |
|---|---|---|---|---|---|---|
| real incident | 24 | 24/24 (100%) | 24/24 (100%) | 23/24 (96%) | 24/24 (100%) | 0/24 (0%) |
| red herring | 10 | 10/10 (100%) | 10/10 (100%) | 8/10 (80%) | 10/10 (100%) | 0/10 (0%) |

![Root-cause accuracy by scenario kind](evaluation-accuracy-by-kind.png)

## Confidence and calibration

A report states `low`, `medium` or `high` confidence. If the stated confidence means anything, accuracy should rise with it. Code also lowers some confidences after the fact (for example `high` needs two kinds of evidence and the look-alike checks), so the level is partly mechanical.

| run | low | medium | high | high confidence and wrong |
|---|---|---|---|---|
| baseline-dev | - | 8/8 (100%) | 26/26 (100%) | 0/26 (0%) [0% to 13%] |

Cells: cases with the root cause found / reports at that confidence.

![Accuracy at each confidence level](evaluation-calibration.png)

## Evidence, timing and tools

| run | evidence found | evidence cited | impact start error (min) | cause time error (min) | tool precision | tool recall |
|---|---|---|---|---|---|---|
| baseline-dev | 0.85 [0.74 to 0.94] (n=33) | 0.83 [0.72 to 0.93] (n=33) | median 6, mean 19 (n=34) | median 0, mean 2 (n=34) | 0.54 [0.50 to 0.59] (n=34) | 0.74 [0.68 to 0.80] (n=34) |

Evidence shares are low for scenarios whose planted evidence is dozens of alarms (an alarm storm): the agent sees a summary and a few rows by design. Means carry a bootstrap 95% interval.

| run | confounder outcomes | repaired reports | citation problems per report | node matches |
|---|---|---|---|---|
| baseline-dev | dismissed 3, not_seen 1, seen_ignored 1 | 1/34 (3%) | 0.03 [0.00 to 0.09] (n=34) | acceptable 3, exact 31 |

## Faithfulness

Not yet measured: no grader output exists for these runs.

## Cost and speed

| run | model calls (p50 / p95) | tool calls (p50 / p95) | tokens (p50 / p95) | model + tool seconds (p50 / p95) | list-price cost per case (p50 / p95) |
|---|---|---|---|---|---|
| baseline-dev | 7 / 8 | 8 / 12 | 28,414 / 35,399 | 11.2 / 14.1 | $0.0137 / $0.0176 |

Seconds add the original latency of each model call and the tool time; they leave out the pause the runner inserts between calls to respect free-tier rate limits, and they do not depend on whether a response came from the cache.

Cost uses the list price of `gemini:gemini-3.5-flash-lite`: $0.30 per million input tokens and $2.50 per million output tokens (including thinking), standard paid tier, text input; read from https://ai.google.dev/gemini-api/docs/pricing on 2026-10-10. The runs themselves used the free tier and cost nothing.

Total at list price: baseline-dev $0.4751.

![Tokens per investigation](evaluation-tokens.png)

## Every case

### baseline-dev

| case | kind | difficulty | planted | reported | node | confidence | right | evidence found / cited | tokens |
|---|---|---|---|---|---|---|---|---|---|
| s42-SCN-001-q0 | public_holiday | medium | expected_event @ - | expected_event/expected_event @ - | exact | high | yes | 1.00 / 1.00 | 31,449 |
| s42-SCN-002-q0 | config_push | easy | bad_change @ S-SFX-001 | incident/bad_change @ S-SFX-001 | exact | medium | yes | 1.00 / 1.00 | 35,524 |
| s42-SCN-003-q0 | alarm_storm | easy | no_impact @ S-SAH-009 | no_impact/no_impact @ S-SAH-009 | exact | high | yes | 0.08 / 0.08 | 28,935 |
| s42-SCN-004-q0 | link_degradation | easy | transport_degradation @ LNK-TUN-01-C | incident/transport_degradation @ LNK-TUN-01-C | exact | high | yes | 1.00 / 1.00 | 29,829 |
| s42-SCN-005-q0 | congestion | hard | capacity @ S-TUN-011 | incident/capacity @ S-TUN-011 | exact | high | yes | 1.00 / 1.00 | 18,816 |
| s42-SCN-006-q0 | planned_maintenance | hard | planned_maintenance @ LNK-TUN-01-A | planned_maintenance/planned_maintenance @ LNK-TUN-01-A | exact | high | yes | 0.80 / 0.80 | 25,032 |
| s42-SCN-007-q0 | power_outage | medium | power_failure @ S-SFX-002 | incident/power_failure @ S-SFX-002 | exact | high | yes | 1.00 / 1.00 | 32,685 |
| s42-SCN-008-q0 | fiber_cut | medium | transport_failure @ LNK-SUD-01-A | incident/transport_failure @ LNK-SUD-01-A | exact | medium | yes | 1.00 / 1.00 | 27,155 |
| s42-SCN-009-q0 | dns_degradation | medium | core_degradation @ CORE-DNS-01 | incident/core_degradation @ CORE-DNS-01 | exact | medium | yes | 1.00 / 1.00 | 32,982 |
| s42-SCN-010-q0 | stadium_event | medium | expected_event @ S-TUN-001 | expected_event/expected_event @ S-TUN-002 | acceptable | high | yes | 0.75 / 0.75 | 24,170 |
| s42-SCN-011-q0 | config_push | hard | bad_change @ S-SAH-002 | incident/bad_change @ S-SAH-002 | exact | medium | yes | 1.00 / 0.50 | 34,370 |
| s42-SCN-012-q0 | planned_maintenance | medium | planned_maintenance @ LNK-SFX-01-A | planned_maintenance/planned_maintenance @ LNK-SFX-01-A | exact | high | yes | 1.00 / 1.00 | 19,201 |
| s42-SCN-013-q0 | congestion | easy | capacity @ S-TUN-007 | incident/capacity @ S-TUN-007 | exact | high | yes | 1.00 / 1.00 | 19,147 |
| s42-SCN-014-q0 | fiber_cut | easy | transport_failure @ LNK-SUD-01-A | incident/transport_failure @ LNK-SUD-01-A | exact | high | yes | 1.00 / 1.00 | 34,390 |
| s42-SCN-015-q0 | power_outage | easy | power_failure @ S-SUD-005 | incident/power_failure @ S-SUD-005 | exact | medium | yes | 1.00 / 1.00 | 22,718 |
| s42-SCN-016-q0 | link_degradation | easy | transport_degradation @ LNK-TUN-02-B | incident/transport_degradation @ LNK-TUN-02-B | exact | medium | yes | 1.00 / 1.00 | 25,214 |
| s42-SCN-017-q0 | alarm_storm | easy | no_impact @ S-SUD-007 | no_impact/no_impact @ S-SUD-007 | exact | high | yes | 0.10 / 0.10 | 27,275 |
| s42-SCN-018-q0 | stadium_event | easy | expected_event @ S-TUN-001 | expected_event/expected_event @ S-TUN-003 | acceptable | high | yes | 0.25 / 0.25 | 26,271 |
| s42-SCN-019-q0 | config_push | easy | bad_change @ S-TUN-008 | incident/bad_change @ S-TUN-017 | acceptable | high | yes | 1.00 / 1.00 | 44,668 |
| s42-SCN-020-q0 | dns_degradation | hard | core_degradation @ CORE-DNS-01 | incident/core_degradation @ CORE-DNS-01 | exact | high | yes | - | 28,247 |
| s42-SCN-021-q0 | fiber_cut | hard | transport_failure @ LNK-TUN-02-C | incident/transport_failure @ LNK-TUN-02-C | exact | high | yes | 1.00 / 1.00 | 30,720 |
| s42-SCN-022-q0 | config_push | medium | bad_change @ AGG-SAH-01 | incident/bad_change @ AGG-SAH-01 | exact | high | yes | 1.00 / 1.00 | 30,667 |
| s42-SCN-023-q0 | link_degradation | medium | transport_degradation @ LNK-SUD-01-B | incident/transport_degradation @ LNK-SUD-01-B | exact | high | yes | 1.00 / 1.00 | 35,332 |
| s42-SCN-024-q0 | planned_maintenance | easy | planned_maintenance @ S-TUN-010 | planned_maintenance/planned_maintenance @ S-TUN-010 | exact | high | yes | 1.00 / 1.00 | 25,445 |
| s42-SCN-025-q0 | power_outage | easy | power_failure @ S-TUN-006 | incident/power_failure @ S-TUN-006 | exact | high | yes | 1.00 / 1.00 | 31,484 |
| s42-SCN-026-q0 | stadium_event | hard | expected_event @ S-TUN-001 | expected_event/expected_event @ S-TUN-001 | exact | high | yes | 0.33 / 0.33 | 28,776 |
| s42-SCN-027-q0 | dns_degradation | easy | core_degradation @ CORE-DNS-01 | incident/core_degradation @ CORE-DNS-01 | exact | high | yes | 1.00 / 1.00 | 29,847 |
| s42-SCN-028-q0 | congestion | medium | capacity @ S-TUN-004 | incident/capacity @ S-TUN-004 | exact | high | yes | 0.50 / 0.50 | 24,604 |
| s42-SCN-029-q0 | link_degradation | medium | transport_degradation @ LNK-SFX-01-B | incident/transport_degradation @ LNK-SFX-01-B | exact | medium | yes | 1.00 / 1.00 | 28,581 |
| s42-SCN-030-q0 | config_push | medium | bad_change @ AGG-TUN-01 | incident/bad_change @ AGG-TUN-01 | exact | high | yes | 1.00 / 1.00 | 19,170 |
| s42-SCN-031-q0 | alarm_storm | medium | no_impact @ S-SAH-004 | no_impact/no_impact @ S-SAH-004 | exact | high | yes | 0.19 / 0.19 | 29,808 |
| s42-SCN-032-q0 | fiber_cut | medium | transport_failure @ LNK-SFX-02-A | incident/transport_failure @ LNK-SFX-02-A | exact | medium | yes | 1.00 / 1.00 | 23,410 |
| s42-SCN-033-q0 | congestion | easy | capacity @ S-TUN-004 | incident/capacity @ S-TUN-004 | exact | high | yes | 1.00 / 1.00 | 23,474 |
| s42-SCN-034-q0 | power_outage | hard | power_failure @ S-SUD-006 | incident/power_failure @ S-SUD-006 | exact | high | yes | 1.00 / 1.00 | 26,479 |

## What the agent gets wrong

No scored case was wrong in the runs included here.

Cases counted as correct that still had something to note:

baseline-dev:

- `s42-SCN-001-q0` (public_holiday, medium): impact start off by 435 min.
- `s42-SCN-005-q0` (congestion, hard): saw the confounder but neither dismissed nor blamed it; a step was answered by another model than the configured one.
- `s42-SCN-009-q0` (dns_degradation, medium): needed a repair call (1 verification problem(s)).
- `s42-SCN-010-q0` (stadium_event, medium): named S-TUN-002, a peer of the labelled node S-TUN-001.
- `s42-SCN-018-q0` (stadium_event, easy): named S-TUN-003, a peer of the labelled node S-TUN-001.
- `s42-SCN-019-q0` (config_push, easy): named S-TUN-017, a peer of the labelled node S-TUN-008.

## Limitations

- **The dev world is optimistic.** The prompts and checks were adjusted while looking at seed 42. Only the test world says how the agent does on something new.
- **Small samples.** There are about 34 scenarios per world, so one case moves a rate by about 3 points and the intervals are wide. Breakdowns by kind or difficulty have only a handful of cases each.
- **One run per case.** The model is run once per case; run-to-run variation is not measured.
- **Synthetic data.** The network, the incidents and the runbooks come from the same simulator. Planted effects are large compared with the noise, and there are no real operator logs.
- **Labels are conventions in places.** Where several equal nodes share a cause, the label names one; `acceptable` accepts the others, `strict` does not.
- **Evidence shares are approximate.** Evidence is matched by row id in tool results and in cited references, and an agent can reach the right conclusion from other rows.
- **Faithfulness is not truth.** The grader judges whether cited evidence supports a claim, not whether the claim is true.
- **Cost is an estimate at list price** for runs that cost nothing, and is shown only where a list price was read from the provider.

## Reproduce

```
cd backend
uv run python -m incident_agent.evals prepare --seed 7
uv run python -m incident_agent.evals run --name baseline-test --seed 7
uv run python -m incident_agent.evals score --run baseline-test
uv run python -m incident_agent.evals report --runs baseline-dev
```
