# Agent versions

The investigation agent went through three versions. Each one is a git tag (`agent-v1`, `agent-v2`, `agent-v3`), and each was measured with the same harness, on the same worlds, before the next change was made. The full evaluation of the final version is in [`evaluation.md`](evaluation.md); this page explains what changed between versions and what each change did.

"Right" below means verdict, cause category and root node all correct (root cause, lenient). "Confident and wrong" means a wrong answer given with high confidence.

## What changed

| version | change |
|---|---|
| v1 | The agent as first built: a case file instead of a chat history, citations checked in code, a completeness gate, confidence caps. |
| v2 | Report reliability: a larger output budget, a compact report, one retry on a malformed report, recovery of a cut-off one; smaller tool definitions (1,965 to 1,182 tokens). Prompt rules for changes and parent nodes. |
| v3 | Look-alike checks in the verify step: the report is checked against the records the run fetched (maintenance window coverage, venue sites of an event, change timing, the shared parent of a link failure, outages inside a window). A contradiction gets one repair call; if it remains, confidence is set to low. |

## Results by version

The hard world with seed 101 is where v2 and v3 were developed, so its numbers are development numbers. Seeds 7, 8 and 202 are held out.

| run | world | version | right | gave up | confident and wrong | tokens p50 |
|---|---|---|---|---|---|---|
| `baseline-test` | seed 7, held out | v1 | 30/34 | 3 | 1 | 27.9k |
| `v3-test` | seed 7, held out | v3 | 34/34 | 0 | 0 | 25.5k |
| `final` | seed 8, held out | v3 | 34/34 | 0 | 0 | 23.3k |
| `hard-baseline` | hard seed 101, development | v1 | 26/34 | 5 | 2 | 29.6k |
| `hard-v2` | hard seed 101, development | v2 | 24/34 | 1 | 5 | 25.6k |
| `hard-v3` | hard seed 101, development | v3 | 31/34 | 2 | 0 | 26.5k |
| `hard-final` | hard seed 202, held out | v3 | 27/34 | 0 | 2 | 26.5k |

## What each change did

- **v1 to v2.** Most v1 misses were reports cut off at the output limit, which ended as "inconclusive". v2 removed those. On the hard world it gave up less often (5 to 1) but was wrong with confidence more often (2 to 5): the new prompt rules did not improve the reasoning on the traps, and with fewer cut-off reports the agent committed to wrong answers.
- **v2 to v3.** Moving the look-alike reasoning from the prompt into code checks fixed most of those confident errors. Each v3 run also keeps the report as it stood before the checks, so the effect is measured on the same investigations:

| run | checks fired | became right | became wrong | right before -> after | confident and wrong before -> after |
|---|---|---|---|---|---|
| `hard-v3` (development) | 9 | 7 | 0 | 24 -> 31 | 5 -> 0 |
| `hard-final` (held out) | 7 | 4 | 0 | 23 -> 27 | 6 -> 2 |
| `final` (held out) | 2 | 2 | 0 | 32 -> 34 | 0 -> 0 |
| `v3-test` (held out) | 0 | 0 | 0 | 34 -> 34 | 0 -> 0 |

On the held-out hard world the checks are weaker than on the world they were developed on (4 of 7 fixed instead of 7 of 9), and they never turned a right answer into a wrong one.

## The completeness gate, measured again

The gate nudges the model once when it wants to stop without checking the maintenance calendar, the change log and external events. On v1, turning it off looked better (seed 7: 32/34 against 30/34), but that comparison was dominated by cut-off reports. Measured again with v3 on the held-out hard world:

| run | gate | right | gave up | tokens p50 |
|---|---|---|---|---|
| `hard-final` | on | 27/34 | 0 | 26.5k |
| `hard-final-nogate` | off | 22/34 | 4 | 20.6k |

The gate costs about 6k tokens per investigation and is worth five cases out of 34 on a world built around look-alikes.

## Caveats

- 34 cases per run: one case is about 3 points, and the intervals are wide (see `evaluation.md`).
- One run per case. The model answers are cached per prompt, so a later version that keeps the same prompts replays the earlier answers; only what changed is asked again. That keeps comparisons paired, but run-to-run variation of the model is not measured.
- The traps of the hard profile come from the same simulator as the rest of the data.
