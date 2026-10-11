# Network Incident Agent

An AI agent that investigates network incidents. Ask "why did traffic drop in region X last night?" and it queries a metrics database, searches runbooks, checks the anomaly detector's output, and writes an incident report with sources.

Stack: LangGraph, Gemini / Groq free tiers (Ollama as local fallback), Postgres + pgvector, FastAPI, Docker, GCP Cloud Run or AWS, GitHub Actions. Optional: tools exposed as an MCP server.

The scope, architecture and milestones are in [`docs/PLAN.md`](docs/PLAN.md).

## Quick start

Requires [uv](https://docs.astral.sh/uv/), Docker Desktop and (optionally) [Ollama](https://ollama.com) with `qwen3:4b` pulled.

```
# 1. secrets: copy the template and fill in GEMINI_API_KEY and GROQ_API_KEY
cp .env.example .env            # PowerShell: Copy-Item .env.example .env

# 2. Postgres + pgvector on localhost:5433
docker compose up -d

# 3. Python environment and database migrations
cd backend
uv sync
uv run alembic upgrade head

# 4. Check the database and every configured model
uv run python -m incident_agent.scripts.smoke
```

Quality checks (from `backend/`): `uv run ruff check . && uv run ruff format --check . && uv run mypy src && uv run pytest`. Add `-m db` or `-m llm` to run the tests that need Postgres or live models.

## Run the API

From `backend/`, with the database up and migrated (`docker compose up -d`, `uv run alembic upgrade head`):

```
uv run uvicorn incident_agent.api.app:app --reload     # http://localhost:8000, docs at /docs
```

- Investigations are streamed as Server-Sent Events: `POST /api/investigations/stream` runs one live, `POST /api/demos/{id}/stream?speed=1` replays a recording (no model call). Recordings live in `backend/src/incident_agent/api/demos/`; `GET /api/demos` lists them.
- Live runs call the model, so they are limited per day (`LIVE_DAILY_LIMIT`, default 20) and can be switched off (`LIVE_ENABLED=false`). `CORS_ORIGINS` is a JSON list of allowed web origins.
- To re-record the demos from cached model responses, with no provider call: `LLM_CACHE_MODE=replay uv run python -m incident_agent.api.record --all`.
- The contract is `docs/api/openapi.json`. After changing an endpoint or a model, regenerate it with `uv run python -m incident_agent.api.openapi`; a test fails when it is out of date.
