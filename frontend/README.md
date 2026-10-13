# Web interface

A Next.js (App Router) app that shows the incident-investigation agent at work. It talks only to the API in `../backend`.

Screens:

- **Investigate** (home): a board that plays the first recorded case, the list of recorded cases, and a form for live questions.
- **An investigation**: the evidence board, the agent's steps, and the cited report. The board has two views:
  - **Timeline**: one time axis with a lane per evidence source (detector alerts, alarms, KPIs, change log, maintenance, external events). A lane fills in when the agent checks that source; a source checked and found empty says so.
  - **Network**: the part of the network involved, drawn as the agent finds it, with alarms on their nodes and the root cause marked at the end.
- **Incidents**: saved runs and detector alerts, newest first. A saved run opens in the investigation screen.
- **How it works**: the pipeline, the design ideas, and the measured results with their caveats.

## Run it

Start the API first (from the repository root and `backend/`, see the root README), then:

```
cd frontend
npm install
npm run dev          # http://localhost:3000
```

To use only recorded replays, with no model call at all, start the API with `LLM_CACHE_MODE=replay`.

`/?case=<id>` starts a recorded case directly, for example `/?case=fiber-cut`.

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

Data, with no rendering:

- `lib/sse.ts`: parser for the event stream (fetch-based, so it can POST).
- `lib/investigation.ts`: the reducer that turns a list of events into view state. Replays, live runs and saved runs all use it.
- `lib/pacer.ts`, `lib/player.ts`: holding events back while paused, speed changes, skipping to the report.
- `lib/api.ts`: typed client.
- `lib/labels.ts`: the single dictionary of plain-language names and definitions for categories, alarms, KPIs and tools.
- `lib/format.ts`: Africa/Tunis time helpers.
- `lib/board.ts`: the Timeline view as data: lanes, the time axis, marks and how they are packed into rows.
- `lib/network.ts`, `lib/network-layout.ts`: the Network view as data: nodes, edges and their positions.
- `lib/chart.ts`: geometry and wording for a KPI series chart.
- `lib/results.ts`: the figures on "How it works", copied from `../docs/results/`.

Screens:

- `components/run/`: the investigation screen. `board*.tsx` is the Timeline view, `network/` the Network view; `feed.tsx` the steps, `detail.tsx` the selected item, `report-view.tsx` the report, `citations.tsx` the evidence behind each reference.
- `components/investigate/`: the home page, including the preview that plays a recorded case up to its completeness check and never shows the conclusion.
- `components/incidents/`, `components/about/`: the other two screens.
- `components/shell/`, `components/ui/`: header, footer and a few shared pieces.

Styling: design tokens and shared classes are in `app/globals.css`. Each screen keeps its own stylesheet next to its components, with every rule under that screen's root class.

## Notes

- Light theme only.
- All times are shown in Africa/Tunis (UTC+1, no daylight saving time) and labelled as such.
- Fonts are self-hosted: Funnel Display and Funnel Sans in `src/app/fonts/` (SIL Open Font License, see `OFL.txt` there) and Geist Mono from the `geist` package. The app makes no requests except to the API.
- Motion: marks grow from their start time, a sweep shows the lane being checked, steps rise in, and the conclusion wipes across the board. Nothing animates after "Skip to report" or on a saved run, and `prefers-reduced-motion` keeps opacity changes only.
