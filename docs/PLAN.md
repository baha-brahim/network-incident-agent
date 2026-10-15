# Network Incident Agent: Plan

This is the source of truth for scope, architecture and milestones.

## 1. What we are building

An AI agent that investigates incidents in a telecom network. A user asks "why did traffic drop in region North last night?", or an anomaly alert fires on its own. The agent then:

1. pulls KPI time series from Postgres,
2. reads the anomaly detector's output,
3. checks the topology, alarms, change log and maintenance calendar,
4. searches runbooks (RAG over pgvector),
5. forms competing hypotheses, tests each one against evidence, ranks them,
6. writes an incident report where every claim cites its source.

What makes it more than a tutorial: the synthetic network contains **planted incidents with known root causes**, plus red herrings. So we can measure whether the agent finds the *right* cause, not only whether its report sounds good.

Background for the README: the author built PYXIS, an unsupervised anomaly-detection system for telecom data, at a consulting company. PYXIS was hard to evaluate without ground truth. This project does not copy PYXIS. It builds ground truth in by design.

## 2. Hard constraints

- **Zero budget.** Every service must be free, both while we build and while the demo runs.
  - LLMs: Gemini API free tier, Groq free tier, and Ollama locally (`qwen3:4b` on an RTX 3060 6 GB).
  - Embeddings run locally (fastembed / bge-small, 384 dims), never through a paid API.
  - Never add a dependency on a paid service without flagging it first.
- **Provider-agnostic LLM layer.** Models are configured by role (`agent`, `grader`, `fallback`) as `provider:model` strings. Switching provider is a config change, not a code change.
- **The grader model must come from a different family than the agent model.**
- **Secrets** live only in `.env` (gitignored). `.env.example` lists the variable names.
- **Dev OS is Windows 11.** Scripts and docs must work there: use uv, Docker Desktop, and avoid bash-only tooling in core workflows. CI runs on Linux.

## 3. Architecture

```
                    ┌──────────────────────────┐
  Next.js UI ──SSE──▶  FastAPI (Lambda)        │◀── alert webhook (detector)
  (Vercel)          │   └─ LangGraph agent     │
  MCP clients ─────▶│   └─ tools ──────────────┼──▶ Postgres + pgvector (Neon)
                    └──────────┬───────────────┘      kpis, topology, alarms,
                               │                      changes, maintenance,
                               ▼                      anomalies, runbook chunks,
                    Gemini / Groq / Ollama            reports, eval results
```

### Repo layout

```
backend/                     Python package (uv project)
  pyproject.toml
  src/incident_agent/
    config.py                pydantic-settings, reads .env
    llm/                     provider factory + fallback chain
    db/                      engine/session, schema, migrations
    simulator/               M2: synthetic network + incident injection
    detector/                M3: anomaly detector
    rag/                     M3: runbook ingestion + retrieval
    agent/                   M4: LangGraph graph, nodes, tools, prompts
    evals/                   M5: eval harness, graders, metrics
    api/                     M6: FastAPI app, SSE streaming
    mcp_server/              M7: MCP server exposing the tools
  tests/
frontend/                    M6: Next.js app
infra/terraform/             M8: AWS Lambda, ECR, IAM, etc.
docs/                        plan, milestone notes, design notes
runbooks/                    M3: markdown runbooks (source documents for RAG)
docker-compose.yml           local Postgres + pgvector
.github/workflows/           CI (lint, types, tests, evals), CD (deploy)
```

### Tech choices

| Concern | Choice |
|---|---|
| Python | 3.12, managed by uv |
| Agent framework | LangGraph |
| LLM clients | langchain-google-genai, langchain-groq, langchain-ollama |
| DB | Postgres 17 + pgvector (Docker locally, Neon in prod), SQLAlchemy 2 + psycopg 3, Alembic |
| Embeddings | fastembed `BAAI/bge-small-en-v1.5` (local, 384 dims) |
| API | FastAPI with Server-Sent Events, on AWS Lambda with response streaming (Lambda Web Adapter) |
| Frontend | Next.js (App Router) + TypeScript + Tailwind, on Vercel |
| Infra | Terraform |
| Quality | ruff (lint + format), mypy, pytest |
| Tracing | LangSmith free tier or Langfuse (decided in M4) |

### Default model roles (configurable)

| Role | Default | Notes |
|---|---|---|
| agent | `gemini:gemini-3.5-flash-lite` | ~15 RPM / ~500 RPD free; fast (~1 s) |
| fallback | `gemini:gemini-3.1-flash-lite` → `groq:openai/gpt-oss-120b` → `ollama:qwen3:4b` | separate quotas; Groq caps a single request at ~6k tokens, so it only fits compact contexts |
| grader | `groq:qwen/qwen3.8-27b` | different family from the agent; one structured call per scenario (200k tokens/day cap) |

Free-tier limits and test results: `docs/notes/llm-providers.md`. The `*-latest` aliases have only ~20 requests/day and move between versions, so always pin exact model names.

## 4. The synthetic network (M2 design outline)

- **Topology:** 4 regions → aggregation routers → ~60 cell sites (4G/5G). Each site depends on a transport link and an aggregation node, which in turn depend on core nodes (MME/AMF, DNS, PGW/UPF). The structure is a dependency graph, so one failure cascades to everything downstream.
- **KPIs** at 15-minute granularity, per cell, over ~30 days:
  - traffic volume (DL/UL GB), active users, RRC setup success rate, call/session drop rate, average latency, PRB utilisation, availability.
  - Realistic daily and weekly seasonality, plus noise.
- **Event tables:** alarms (with severity, raising node, timestamps), change log (config pushes, software upgrades), maintenance calendar (planned windows), external events (holidays, stadium events).
- **Planted incidents.** Each has a known root cause, start/end time, affected scope and the expected evidence trail. Planned types:
  - fiber cut on a transport link (several sites drop, LOS alarms)
  - faulty config push (KPI regression right after a change-log entry)
  - site power outage (one site down, power alarms)
  - core/DNS degradation (latency up everywhere, traffic down)
  - capacity congestion (PRB utilisation saturated, throughput down)
- **Red herrings:** a planned maintenance window (an expected drop that is not an incident), a stadium event (a traffic spike), a holiday dip, and noisy unrelated alarms.
- **Ground-truth file:** every scenario is written to a labels table/JSON that only evals read. The agent never sees it.

## 5. The agent (M4 design outline)

A LangGraph state machine:

`intake → plan → gather evidence (tool calls, parallel where possible) → hypothesize → test hypotheses (more tool calls) → rank → write report → self-check citations`

- **Tools** are read-only:
  - `query_kpis` (parametrised, not free SQL; covers cell, site, region and core-node KPIs)
  - `run_sql` (guarded: read-only role, SELECT only, row/time limits, table allowlist)
  - `get_anomalies`, `get_topology`, `get_alarms`, `get_changes`, `get_maintenance`, `get_external_events`, `search_runbooks`
- **Report:** structured output (summary, root cause, confidence, timeline, evidence list with source IDs, recommended actions). Every claim links to a tool-call result or a runbook chunk ID.
- **Verification:** after the report is written, code checks its citations and whether it contradicts records the run fetched: a maintenance window that does not cover the outage, an event whose venue is not where the symptom is, a change that landed long before the degradation, a parent named without a signal of its own, or an outage that lies inside a window. Such a contradiction is stated to the model, which gets one call to correct the report; if it still fails, confidence is forced to low and the problem is listed. A check fires only when fetched records contradict the verdict, never because a record is missing.
- **Budget:** a cap on tool calls per investigation, plus token and cost tracking per run.
- **Step cap:** about 8–10 agent steps per investigation. Old tool results are trimmed or condensed once used. "Tokens per investigation" is a headline README metric.
- **Provider switching mid-run:** state is kept as LangChain messages, which are provider-neutral. Known trap: Gemini 3 tool calls carry thought signatures that must be passed back, and messages produced by other providers lack them. M4 must include a forced-switch test (Gemini → Groq → Ollama → Gemini in one investigation) and fix whatever breaks. The Ollama tool round trip was never tested in M1; test it in M4.
- **Per-step provenance:** every LLM step records which provider/model actually answered, plus tokens and latency.
- **Context budget:** tools return compact summaries (aggregates, top-N rows, IDs to cite), never raw dumps. Old tool results get condensed in state. The target is under ~6k prompt tokens per call, so the Groq fallback can always take over. This is a deliberate design point: it keeps every call cheap and the context focused.
- **Triggers:** a user question (chat), or an alert webhook from the detector (autonomous run; the report is stored).

## 6. Evaluation (M5)

| Metric | How |
|---|---|
| Root-cause accuracy (top-1, top-3) | report root cause vs ground-truth label (exact category + LLM-judged match on scope) |
| Tool selection | expected tools per scenario vs tools called (precision/recall) |
| Retrieval | recall@k / MRR of runbook chunks against labelled relevant chunks |
| Faithfulness | LLM grader checks each claim against the cited evidence |
| Red-herring handling | does the agent correctly dismiss maintenance/events? |
| Detector quality | precision/recall/F1 of the anomaly detector vs planted incidents |
| Cost and latency | tokens, $ at list price (even though we pay $0), wall time, p50/p95 per query |

- LLM responses are cached on disk, so re-runs are free and deterministic.
- Free tiers allow ~25 investigations/day. So:
  - CI replays recorded LLM responses (cassettes) and gates on the deterministic metrics.
  - Live eval runs are on demand, may span more than one day, and their results are committed.
- Grading uses one structured grader call per scenario, not one per metric.
- **Ground truth first.** Root-cause accuracy, tool selection and red-herring handling are computed in code from the planted labels. The LLM grader is used only for what code can't judge: faithfulness and report quality.
- **Grader calibration.** The user hand-grades 15–20 reports, and we measure grader-vs-human agreement (Cohen's kappa). We use the same set to decide whether the grader's thinking stays off (default off, to save Groq tokens) or on.
- **Clean comparisons.** Runs where a fallback model answered any step are flagged, and excluded from per-model comparisons.
- **Quota timing.** Gemini daily quotas reset at midnight Pacific, which is 08:00–09:00 in Tunisia. Start big live eval runs right after that.
- CI never calls live APIs. Deploy secrets live in GitHub Actions secrets and AWS Secrets Manager / Lambda env, never in the repo.

## 7. Milestones

| # | Milestone | Done when |
|---|---|---|
| M1 | Foundation | repo, uv project, docker compose Postgres+pgvector, config, LLM provider factory with fallback, CI (lint/types/tests) green, smoke test calling each provider |
| M2 | Synthetic network | generator produces topology, KPIs, events, planted incidents and red herrings into Postgres; ground-truth labels; plots for sanity checks |
| M3 | Detector + RAG | anomaly detector writes the anomalies table and is evaluated against labels; runbooks written, chunked, embedded, searchable |
| M4 | Agent | LangGraph agent investigates end-to-end with tools and writes cited reports; tracing |
| M5 | Evaluation | eval harness with all metrics, cached, in CI with a regression gate; results table in docs |
| M6 | API + UI | FastAPI SSE endpoint; Next.js UI streaming agent steps, report view, incident list; replay mode |
| M7 | MCP + autonomy | MCP server exposing tools; alert webhook triggers investigations automatically |
| M8 | Deploy | Terraform for Lambda/ECR/IAM; Neon; Vercel; GitHub Actions CD; rate limiting; README with results, architecture diagram, demo video |
