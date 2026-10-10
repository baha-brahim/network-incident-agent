# Agent smoke check

This is a small smoke check of the investigation agent on 11 of the 34 planted scenarios of the seed-42 dataset. It is **not the evaluation**: each scenario was run once, the prompts were adjusted while looking at some of these same scenarios (see "What changed during the check"), and 11 runs say little about accuracy. The proper evaluation (more runs, ground-truth metrics computed in code, a grader for report quality) comes later.

Model: `gemini-3.5-flash-lite` (temperature fixed by the provider, minimal thinking), with the runner's fallback chain `gemini-3.1-flash-lite`, `groq:openai/gpt-oss-120b`, `ollama:qwen3:4b`. Responses came from the live free-tier APIs; the LLM cache was on, so a repeated step was free.

## How a run works

`intake` (model) resolves the question into a scope, `orient` (code) fetches the detector alerts and the topology of named nodes, `investigate` (model with tools, up to 6 turns and 14 tool calls) gathers evidence, `conclude` (model) writes a structured report, `verify` (code) checks every cited reference, node, time and the classification against the evidence the run gathered and lowers over-confident reports, `render` writes markdown. Every model call is built from scratch from a rendered "case file" (question, scope, one line per tool call, the newest results in full, the model's own notes), so any provider can answer any step.

## Columns

| Column | Meaning |
|---|---|
| scenario, kind, difficulty | The planted scenario and its label in the dataset |
| classification | The report's `classification` equals the planted one (incident, planned_maintenance, expected_event, no_impact) |
| category | The report's `root_cause_category` equals the planted root-cause category |
| root node | The report's `root_cause_node_id` equals the planted root node exactly (for red herrings it is the node the window, event or alarms concern; for the holiday it is none) |
| confidence | The confidence the report states |
| LLM calls | Model calls in the run, including a repair call if one was needed |
| tool calls | Tool calls, including the two made by `orient`; calls that repeat an earlier one are not run and not counted |
| tokens | Input plus output tokens as the provider reported them |
| seconds | Wall time of the live run (the tools take 10 to 200 ms each; the rest is model latency and the 4.5 s minimum interval between Gemini calls) |
| models | Models that answered the steps |

## Results

| scenario | kind | difficulty | classification | category | root node | confidence | LLM calls | tool calls | tokens | seconds | models |
|---|---|---|---|---|---|---|---|---|---|---|---|
| SCN-001 | public_holiday | medium | yes | yes | yes | high | 6 | 5 | 21,166 | 28 | gemini-3.5-flash-lite |
| SCN-002 | config_push | easy | yes | yes | yes | medium | 8 | 12 | 35,524 | 37 | gemini-3.5-flash-lite |
| SCN-003 | alarm_storm | easy | yes | yes | yes | high | 7 | 8 | 28,935 | 31 | gemini-3.5-flash-lite |
| SCN-005 | congestion | hard | yes | yes | yes | high | 5 | 7 | 18,816 | 31 | gemini-3.5-flash-lite, gemini-3.1-flash-lite (report step) |
| SCN-006 | planned_maintenance | hard | yes | yes | yes | high | 6 | 6 | 25,032 | 27 | gemini-3.5-flash-lite |
| SCN-009 | dns_degradation | medium | yes | yes | yes | medium | 8 | 9 | 32,982 | 35 | gemini-3.5-flash-lite |
| SCN-011 | config_push | hard | yes | yes | yes | medium | 8 | 12 | 34,370 | 36 | gemini-3.5-flash-lite |
| SCN-015 | power_outage | easy | yes | yes | yes | medium | 6 | 7 | 22,718 | 27 | gemini-3.5-flash-lite |
| SCN-016 | link_degradation | easy | yes | yes | yes | medium | 7 | 8 | 29,996 | 31 | gemini-3.5-flash-lite |
| SCN-021 | fiber_cut | hard | yes | yes | yes | high | 7 | 7 | 30,720 | 31 | gemini-3.5-flash-lite |
| SCN-026 | stadium_event | hard | yes | yes | yes | high | 7 | 7 | 28,776 | 31 | gemini-3.5-flash-lite |

The first question of each scenario was used. All ten kinds of scenario are covered (fiber cut, power outage, config push, link degradation, congestion, DNS degradation, planned maintenance, stadium event, public holiday, alarm storm).

Cost over these 11 runs: 5 to 8 model calls per run (median 7), 16.8k to 32.9k input tokens (mean 25.5k, plus about 2.6k output tokens). Per call: investigate turns take a median 1.3 s (p95 2.0 s) and 4.8k input tokens (max 6.1k, of which about 2k are the tool definitions); the report call takes a median 4.2 s (p95 7.5 s) and writes about 1.5k tokens. SCN-002 and SCN-011 are above 34k tokens because they used 12 tool calls.

Timing of the reported impact: in all runs the stated start is within 45 minutes of the planted one except SCN-001 (a nationwide holiday; the report starts at the first visible deviation, 07:15, not at midnight).

## What changed during the check

The first pass (earlier prompts) got every classification and category right on the first 11 scenarios but several root nodes wrong; extra scenarios run during the check turned up one case that was badly wrong. Changes made in response, all general (no scenario-specific text):

1. **Root node convention.** Reports named the shared router for a two-site congestion (SCN-005), no node for a three-site config batch (SCN-011), and no node for noise or events (SCN-003, SCN-026, SCN-018). The report prompt now says which node each cause type refers to (link or router for transport causes, the site for power and capacity, the changed node for a change, the core node for core causes, the node a window, event or alarms concern for red herrings) and to name the most affected or earliest node when peers share a cause.
2. **A missed symptom was reported as "no impact" with high confidence (SCN-015, easy).** Intake had read "last night" as the whole previous day, so the agent looked at the wrong hours, found nothing and said the premise was wrong. Fixes: the intake prompt defines relative words and receives yesterday's date; `orient` now looks for alerts up to "now" instead of the end of the guessed window; the investigate prompt says to widen the window before concluding that a symptom is absent; the report prompt says an absent symptom is `inconclusive`; and code lowers a `no_impact` report to low confidence unless it cites something that positively explains the question (alarms, an alert, a record). After the change the same run found the mains failure and was correct.
3. **A claimed check that was never made.** After the completeness gate asked for external events, one run wrote that they "do not apply" and the report then said they were ruled out. The gate message now says a note is not a check, the report prompt receives a `NOT CHECKED` line built from the tool-call log, and code lowers `high` confidence to `medium` when a look-alike check is missing. This is why several correct reports state `medium`.
4. **Impact end.** Reports said "ongoing" when they had not established the end. The prompt now asks for the end (recovery, rollback, alarm clear) or null if unknown, and the markdown prints "not established or ongoing" for null.
5. **Size.** The case file limit went from 10,000 to 7,500 characters and the full-result blocks lost their repeated argument list, to keep every call under about 6.2k real input tokens.

Each prompt change invalidates the cache of the steps it touches, so the table above comes from a complete re-run with the final prompts (SCN-015 was run once with the final prompts, then replayed from the cache).

## What still fails or is fragile

- **The peer-node choice is a convention, not evidence.** When one cause hits several equal nodes (a change batch on three sites, congestion on two sites), the planted label names one of them. The agent names the most affected or earliest one, which matched in the final runs but did so after the rule was added while looking at these very scenarios. Expect misses on other multi-node scenarios (SCN-028 and SCN-033 are untested).
- **Impact end is limited by what was queried.** SCN-011's rollback came the next morning at 05:53; the report's end time was 12:00, the end of the window the agent had looked at. The comparison helper checks only the start time, so this was found by reading the report.
- **Confidence is conservative and partly mechanical.** `medium` appears on five correct reports mostly because the model did not call the external-events tool even after being nudged once. That is the design (the gate nudges, the model chooses), but it costs calibration signal.
- **Hypotheses are thin.** Several reports list a single hypothesis although the prompt asks for competing ones; the rejected alternatives often appear only under "ruled out".
- **Report size is close to the output cap.** The report call writes 1.5k tokens on average and up to 2.0k against a 2,048-token cap; one report was cut off, failed validation on the primary model and was written by the second Gemini model instead. A compact-report instruction was not added, to stay inside the live budget.
- **Small models are not a real fallback for late steps.** Prompts reach 4.8k to 6.1k real input tokens (about 2k are tool definitions), so Groq (8k per request) is skipped for the later turns and the report call. Ollama `qwen3:4b` answers tool-call turns correctly but slowly (40 to 95 s) and cannot finish structured output (it spends its output budget thinking and the JSON is cut off: intake and the report failed in a run that used only Ollama).
- **Only the first question of each scenario was asked, once, and all runs are on one dataset.** Run-to-run variation is not measured.

## Provider switching and quota

- The forced-switch test (`tests/test_agent_live.py`) runs one investigation whose consecutive steps go to Gemini (intake), Groq (turn 1), Ollama (turn 2), Gemini (turn 3), Ollama (turn 4) and Gemini (report). In its last run every step was answered by the planned provider and the report was valid and correct. In two earlier runs of the same test one Ollama tool call came back as invalid JSON (the step was answered by the next model in the chain), and a Gemini 503 ("high demand") on the report step was answered by Groq.
- No 429 was seen. Live Gemini requests used: about 242 of the 250 budget (231 logged steps in the dev runs, one rejected structured output, about 10 for the live tests).
