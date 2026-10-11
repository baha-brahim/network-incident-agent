# Web interface

A Next.js (App Router) app that shows the incident-investigation agent at work: a live timeline of tool calls and notes, a detail panel with arguments, output and KPI charts, and the final cited report. It talks only to the API in `../backend`.

Screens: **Investigate** (recorded replays and live mode), **Incidents** (saved runs and detector alerts), **How it works**.

## Run it

Start the API first (from the repository root and `backend/`, see the root README), then:

```
cd frontend
npm install
npm run dev          # http://localhost:3000
```

To use only recorded replays, with no model call at all, start the API with `LLM_CACHE_MODE=replay`.

## Environment

| Variable | Default | Purpose |
|---|---|---|
| `NEXT_PUBLIC_API_URL` | `http://localhost:8000` | Base URL of the API. Set it when deploying. |
| `NEXT_PUBLIC_REPO_URL` | unset | Link to the repository. The link is hidden when unset. |

Copy `.env.example` to `.env.local` to change them. Nothing secret belongs here: both values are public by design.

## Checks

```
npm run lint
npm run typecheck
npm test
npm run build
```

`npm test` includes a contract test that checks recorded runs (`src/lib/__fixtures__/`) against `../docs/api/openapi.json`.

## API types

Types come from the API contract. After the contract changes, regenerate them:

```
npm run gen:api
```

## Layout of `src/`

- `lib/sse.ts`: parser for the event stream (fetch-based, so it can POST).
- `lib/investigation.ts`: the reducer that turns a list of events into view state. Replays, live runs and stored runs all use it.
- `lib/pacer.ts`, `lib/player.ts`: holding events back while paused, speed changes, skipping to the report.
- `lib/api.ts`: typed client.
- `lib/labels.ts`: the single dictionary of plain-language names and definitions for categories, alarms, KPIs and tools.
- `lib/chart.ts`: geometry and wording for the KPI charts.
- `components/run/`: the investigation view (timeline, detail panel, report, charts, controls).
- `components/investigate/`, `components/incidents/`, `components/about/`: the three screens.

## Notes

- All times are shown in Africa/Tunis (UTC+1, no daylight saving time) and labelled as such.
- Motion is limited to short fades and rises for arriving steps and the report, press feedback, and tooltips. It all respects `prefers-reduced-motion`.
- The app makes no requests except to the API, and loads no external fonts or scripts.
