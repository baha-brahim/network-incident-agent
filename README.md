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

### Alert-triggered investigations

A detector alert can start an investigation on its own. The question is built from what the detector had seen one hour into the alert, and the run is stored like a live one, so it appears on the Incidents screen with the alert's id.

- Webhook: `POST /api/alerts/{alert_id}/investigate` with `Authorization: Bearer <ALERT_WEBHOOK_TOKEN>`. It runs the whole investigation inside the request and answers `{"created": bool, "run": {...}}`; an alert that already has a finished run, or one started in the last 15 minutes, is not investigated again (`created` is false). Without `ALERT_WEBHOOK_TOKEN` the endpoint answers 503. `ALERT_DAILY_LIMIT` (default 10) caps new runs per UTC day.
- Command line, for a scheduler: `uv run python -m incident_agent.api.autopilot pending` lists alerts without a run, `run ALR-0019` investigates one, `sweep --limit 3` investigates the newest pending ones and stops at the daily limit. `pending` and `--dry-run` never call a model.

## Use the tools from an MCP client

The nine read-only investigation tools are also served over MCP (stdio), for any MCP client. From `backend/`, with the database up:

```
uv run python -m incident_agent.mcp_server                            # data up to the dataset's now
uv run python -m incident_agent.mcp_server --asked-at "2026-09-22 08:38"   # Africa/Tunis local time
```

Every tool sees data only up to that time, as it does for the agent. Example client configuration (adjust the path to this repository):

```json
{
  "mcpServers": {
    "network-incident-agent": {
      "command": "uv",
      "args": [
        "--directory", "/path/to/network-incident-agent/backend",
        "run", "python", "-m", "incident_agent.mcp_server"
      ]
    }
  }
}
```

To try it interactively, use the MCP Inspector: `npx @modelcontextprotocol/inspector uv --directory backend run python -m incident_agent.mcp_server`.

## Run the web interface

With the API running (see above), from `frontend/` (Node 22):

```
cd frontend
npm install
npm run dev          # http://localhost:3000
```

It reads the API at `NEXT_PUBLIC_API_URL` (default `http://localhost:8000`); set `NEXT_PUBLIC_REPO_URL` to show a link to this repository. To explore it without ever calling a model, start the API with `LLM_CACHE_MODE=replay`: recorded replays never call one. Checks: `npm run lint`, `npm run typecheck`, `npm test`, `npm run build`. More in [`frontend/README.md`](frontend/README.md).
