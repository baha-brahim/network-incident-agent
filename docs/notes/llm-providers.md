# LLM providers: free-tier limits, tests and role assignment

Checked on **2026-10-10** with the project's real API keys. Everything marked "measured" came from our own calls. Everything marked "reported" comes from docs or third-party pages and was not verified.

## Summary

| Role | Recommended | Why |
|---|---|---|
| agent | `gemini:gemini-3.5-flash-lite` | Only Gemini model with a usable free quota (15 RPM measured, 500 RPD reported). Passed every test, about 1 s per call. |
| fallback | `gemini:gemini-3.1-flash-lite`, then `groq:openai/gpt-oss-120b`, then `ollama:qwen3:4b` | A second Gemini model has its own separate quota. Groq only works for short prompts (8K tokens per request). Ollama never runs out. |
| grader | `groq:qwen/qwen3.8-27b` (keep the plan default) | Different family from Gemini and from gpt-oss. Passed all tests, strict JSON schema works, about 1 s per call. |

The plan's default agent, `gemini:gemini-flash-latest`, does **not** work on the free tier: it currently resolves to `gemini-3.8-flash`, which allows **20 requests per day**. That is one investigation. We used the whole day's quota in testing and then got a 429.

## 1. Free-tier limits

| Model | RPM | RPD | TPM | TPD | Source / status |
|---|---|---|---|---|---|
| `gemini-flash-latest` (alias, now serves `gemini-3.8-flash`) | not seen | **20** | not seen | none | RPD measured (429 message: `limit: 20, model: gemini-3.8-flash`, metric `GenerateRequestsPerDayPerProjectPerModel-FreeTier`) |
| `gemini-3.8-flash` | not seen | **20** | not seen | none | measured, same as above. Alias and model share one counter. |
| `gemini-3.5-flash` (silently served as `gemini-3.6-flash`) | **5** | 20 (reported) | not seen | none | RPM measured (429: `limit: 5, model: gemini-3.6-flash`). RPD from scriptbyai.com. |
| `gemini-3.5-flash-lite` | **15** | 500 (reported) | not seen | none | RPM measured (429: `limit: 15`). RPD from the Google AI forum thread and scriptbyai.com. |
| `gemini-3.1-flash-lite` | not seen | 500 (reported) | not seen | none | RPD reported only. Passed our tests. |
| `gemini-2.5-flash` | n/a | n/a | n/a | n/a | **404: "no longer available to new users"** with this key. |
| `openai/gpt-oss-120b` (Groq) | 30 | 1,000 | **8,000** | 200,000 | Docs table, Free Plan tab. RPD and TPM confirmed by `x-ratelimit-*` response headers. |
| `openai/gpt-oss-20b` (Groq) | 30 | 1,000 | 8,000 | 200,000 | same |
| `qwen/qwen3.8-27b` (Groq) | 30 | 1,000 | 8,000 | 200,000 | same |

Notes:

- Gemini quotas are **per project, per model**, and RPD resets at midnight Pacific time. Each model has its own counter, so several Gemini models give several daily quotas.
- Google does not publish free-tier numbers in its docs. The rate-limits page only says "view your active limits in AI Studio". We read the real numbers from 429 error bodies. TPM was never hit, so it is unknown. Pro models are not free any more (reported).
- Groq limits are per **organization**, not per API key. Extra keys do not add quota.
- **Groq's 8,000 TPM is also a per-request cap.** A single request with about 19k tokens came back as HTTP 413 ("Request too large ... Limit 8000, Requested 19116"). Input plus the requested completion budget has to stay under 8K. Reasoning tokens of gpt-oss and qwen count as output.
- Gemini returns intermittent 503 "high demand" errors on the flash models (seen on `gemini-flash-latest` and `gemini-3.8-flash`). The fallback chain should treat 503 like 429.

Sources:

- https://ai.google.dev/gemini-api/docs/rate-limits (no free-tier table; points to AI Studio)
- https://ai.google.dev/gemini-api/docs/pricing (free tier available for all flash models; training column below)
- https://console.groq.com/docs/rate-limits (Free Plan tab)
- https://discuss.ai.google.dev/t/gemini-3-8-flash-free-tier-20-rpd-is-too-limited-for-practical-evaluation/180609 (20 RPD for 3.8 Flash, 500 RPD for Flash-Lite, Sept 2026)
- https://www.scriptbyai.com/gemini-api-free-tier-limits/ (per-model RPD, "September 2026")
- https://ai.google.dev/gemini-api/terms (unpaid services)

### Privacy note for the README

On the Gemini API free tier, Google uses prompts and responses to improve its products and models, and human reviewers may read them (pricing page: "Used to improve our products: Yes" for free, "No" for paid; terms: "Do not submit sensitive, confidential, or personal information to the Unpaid Services"). This project only sends synthetic data and public-style runbooks, so that is acceptable. The README should say that nobody should point the free-tier setup at real network data. (We did not research Groq's data policy.)

## 2. Test results

Same tests for every model, with the real keys, raw HTTP. Tools: `get_alarms(site_id, start, end)` and `query_kpis(region, kpi, start, end)`. Pass means the right tool was called exactly once with exactly the right arguments (kpi had to be the enum value `drop_rate`, times had to be the ones in the question).

- **simple**: reply with "pong".
- **tool_alarm / tool_kpi**: one question that needs one specific tool.
- **roundtrip**: send a fake tool result back and get a text answer that uses it (for Gemini this includes passing the model's own tool-call message back unchanged).
- **json**: JSON-schema structured output (`root_cause`, `confidence`, `evidence[]`).

| Model | simple | tool_alarm | tool_kpi | roundtrip | json schema | Latency per call |
|---|---|---|---|---|---|---|
| `gemini-flash-latest` (= 3.8 flash) | pass | pass | pass (retry; first try was a 503) | pass | pass | 4 to 16 s, one 39 s outlier |
| `gemini-3.8-flash` | pass | pass | pass | pass | pass | 6 to 31 s |
| `gemini-3.5-flash` (= 3.6 flash) | pass | pass | pass | pass | pass | 2 s typical, one 34 s outlier |
| `gemini-3.5-flash-lite` | pass | pass | pass | pass | pass | **1.0 to 1.3 s** (two full runs) |
| `gemini-3.1-flash-lite` | pass | pass | pass | pass | pass | 5 to 9 s |
| `gemini-2.5-flash` | fail (404) | fail | fail | n/a | fail | n/a |
| Groq `openai/gpt-oss-120b` | pass | pass | pass | pass | pass (strict `json_schema`) | 0.9 to 1.4 s |
| Groq `openai/gpt-oss-20b` | pass | pass | pass | pass | pass | 0.9 to 1.4 s |
| Groq `qwen/qwen3.8-27b` | pass | pass | pass | pass | pass (strict `json_schema`) | 0.7 to 1.3 s |
| Ollama `qwen3:4b`, `think=false` | n/a | pass | pass | not run | pass | 16 s (first call 69 s incl. 38 s model load) |
| Ollama `qwen3:4b`, `think=true` | n/a | pass | pass | not run | pass | 9 to 12 s tool calls, 39 s for JSON |

Ollama on the RTX 3060 6 GB: **about 75 to 84 tokens/s** generation. A one-tool-call turn costs 440 to 740 output tokens even with `think=false` (the model still produces reasoning-like text), so a tool-call turn takes roughly 6 to 10 s once warm. Context was 8,192 tokens in the test.

What the tests do not show: all of these are easy single-step prompts. They show that tool-call format and JSON output are reliable. They say nothing about multi-step reasoning quality. M4 and M5 will need a real comparison on planted incidents.

Things that were surprising:

1. Alias behavior. `gemini-flash-latest` serves `gemini-3.8-flash`. `gemini-3.7-flash` also serves 3.8. `gemini-3.5-flash` serves **3.6**. The `modelVersion` field in the response shows what really ran, and quota is counted against the real model.
2. `gemini-2.5-flash` returns 404 for this key (new keys cannot use it).
3. No model failed tool calling. Even `qwen3:4b` called both tools correctly.
4. Gemini 3.x flash models spend thinking tokens even on "reply pong" (about 50 tokens), and the bigger ones take 4 to 30 s per call. `gemini-3.5-flash-lite` has no visible thinking and is the fastest.

## 3. Budget estimate

Assumptions: one investigation is 20 LLM calls and 60k input tokens (3k per call on average, growing toward 6 to 10k late in the run). An eval run is 30 scenarios, each one investigation plus 5 grader calls (about 3.5k tokens each, my guess).

**Agent model, calls per day and what that means**

| Model | Binding limit | Investigations per day | Full eval run (600 agent calls) |
|---|---|---|---|
| `gemini-flash-latest` / `3.8-flash` | 20 RPD | **1** | 30 days |
| `gemini-3.6-flash` | 20 RPD, 5 RPM | 1 | 30 days |
| `gemini-3.5-flash-lite` | 500 RPD, 15 RPM | **25** (reported RPD) | 1.2 days |
| `gemini-3.5-flash-lite` + `3.1-flash-lite` (separate quotas) | 1,000 RPD | 50 | fits in 1 day |
| Groq gpt-oss-120b as agent | 200K TPD, 8K per request | about 3 (60k tokens each), and only while each prompt stays under 8K | 10 days |
| Ollama `qwen3:4b` | none | unlimited, but about 5 to 10 s per call, so 2 to 4 min per investigation | about 1.5 to 2 hours |

At 15 RPM, a 20-call investigation needs at least 80 seconds of quota time, so rate limiting is not a problem for a single run. Parallel eval workers are: run at most 2 to 3 at a time.

**Grader (Groq, one model, 200K TPD, 8K TPM)**

- 5 grader calls per scenario is about 17.5k tokens per scenario, so 30 scenarios is about 525k tokens. That is 2.6 days on one model.
- With 1 grader call per scenario (all rubric items in one structured output), 30 scenarios is about 105k tokens, which fits in one day, in about 15 minutes of wall time (8K TPM is roughly 2 calls per minute).
- Each grader prompt must stay below about 6k tokens.

### Recommended strategy

1. **Dev and evals: `gemini-3.5-flash-lite`**, with `gemini-3.1-flash-lite` as the automatic first fallback. 600 agent calls fit in about one day across both. Pin exact model names, never `-latest`.
2. **Grader: one grader call per scenario**, structured output with all rubric items. Run it right after each investigation so the grader never needs more than about 105k tokens/day. Do not mix grader models inside one eval run (scores would not be comparable). If a run needs more, continue the next day.
3. **Cache every LLM response during evals**, keyed on model, prompt and tools. Re-running grading or metrics must not call the agent again. Save the full agent trace (tool calls, report) per scenario so grading can be redone without re-investigating.
4. **Demo:** pre-record a few investigations (replayable through SSE) and offer live runs on `gemini-3.5-flash-lite`. A live run costs 20 of 500 daily calls, so a handful of visitors per day is fine. A public demo with real traffic will exhaust it, so add a per-IP or global daily cap in the API and show "demo quota used up, replay a recorded run".
5. **Optional quality step:** use `gemini-3.8-flash` (20 RPD) only for the final report-writing call, 1 to 2 calls per investigation, so about 10 to 20 investigations a day could use it. Needs a separate `report_model` role in config; only worth it if M5 shows the lite model writes weak reports.
6. **Fallback chain behavior:** treat 429 and 503 as "switch model". Skip the Groq step when the prompt is over about 6k tokens (it would return 413 anyway) and go straight to Ollama.

### Suggested config strings

```
agent_model     = "gemini:gemini-3.5-flash-lite"
fallback_models = ["gemini:gemini-3.1-flash-lite", "groq:openai/gpt-oss-120b", "ollama:qwen3:4b"]
grader_model    = "groq:qwen/qwen3.8-27b"
```

## 4. Caveats

- **Quotas change without notice.** The 20 RPD on Flash is a recent cut (a May 2026 forum thread complains about a 92% reduction). Re-check by reading the 429 body or https://ai.dev/rate-limit before every big eval run.
- **RPD for the lite models (500) is reported, not measured.** We only measured RPM (15). Count our own calls and confirm.
- **Preview and "latest" models move or disappear.** `gemini-flash-latest` changed target while we tested other names; `gemini-2.5-flash` is already closed to new users. Pin exact names in config and log `modelVersion` from each response in the trace.
- **Alias quota trap:** `gemini-3.5-flash` is counted as `gemini-3.6-flash`. Quota math should use the model that actually answers.
- **Groq's free plan is tight.** 8K tokens per request means long tool outputs (KPI series) must be summarized or truncated before they reach a Groq model. Groq can fall out of the fallback chain entirely if prompts grow.
- **Quality is untested.** Latency and format reliability are measured. Reasoning quality of a lite model on multi-step root-cause analysis is not. Treat the agent choice as provisional until M5.
- **Test scripts** are in the session scratchpad, not in the repo. Keys were read from `.env` and never printed.
