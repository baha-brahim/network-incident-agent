# Cassettes

Recorded model responses for the replay test, `backend/tests/test_replay.py`. With them, CI runs
complete investigations (intake, tools, case file, report, verification) without an API key and
without a network: only the model is replaced, everything else runs for real against Postgres.

## What is here

```
evals/cassettes/
  fiber-cut/             one directory per investigation
  planned-maintenance/
  dns-degradation/
```

Each directory holds one JSON file per model call, named after the first 24 characters of its
cache key (a hash of the role, the exact messages, the tool schemas and the output schema). A file
has:

- `request`: hashes of the prompt parts and a short preview, to tell which call a file is;
- `response`: the model's text, its tool calls, and the parsed structured output;
- `usage`: the provider, model, token counts and latency of the original call.

There are no credentials in the files, and no run ids or timestamps. All files were recorded by
one model (the primary agent model, no fallback chain), and the test fails if they ever mix.

## The investigations

All are asked on the morning of Thursday 2026-09-03 (Africa/Tunis) on the small fixture world
(`backend/tests/fixtures_world.py`), with the detector's output and the runbooks (hashing
embedder) loaded into the test database.

| case | question is about | what the world says |
|---|---|---|
| `fiber-cut` | two sites that lost service the evening before | incident, `transport_failure`, `LNK-TUN-01-A` |
| `planned-maintenance` | a site that dropped off the air overnight | planned maintenance, `MW-0001` on `S-SFX-001` |
| `dns-degradation` | pages not loading around lunchtime although signal was full | incident, `core_degradation`, `CORE-DNS-01`; an upgrade on the same node an hour earlier is a coincidence |

The first recorded report of `dns-degradation` is wrong about the category: it blames the upgrade
(`bad_change`) with high confidence. The verify step refutes that from the timing (the change
landed an hour before the degradation) and the recording holds the one repair call in which the
model corrects the report to `core_degradation`. A case whose recorded answer is wrong can be
marked with `known_miss`: the true category is then asserted in a strict `xfail` test, so a
re-recording that gets it right turns that test red until the field is removed.

## How the test uses them

In the default mode (`replay`) the runner reads these files and never calls a provider, and no key
is read. A request that has no file raises a cache miss, and the test fails with a message that
says the prompts or the tool output changed, and how to re-record.

A miss in CI only (the same code passes on your machine) means a prompt differs between
machines. Do not re-record then; find the difference. `uv run pytest -m db tests/test_replay.py`
needs the database of `docker compose up -d` and runs in a few seconds.

## Re-recording

Re-record after changing a prompt, a tool's output, the fixture world, the runbooks or the
detector. It makes live calls to the primary model (`AGENT_MODEL`, Gemini by default, key in
`.env`): about 20 for the three investigations, against a free-tier limit of 15 requests a minute.
Run from `backend/`:

```
REPLAY_RECORD=1 uv run pytest -m db tests/test_replay.py                          # bash
$env:REPLAY_RECORD='1'; uv run pytest -m db tests/test_replay.py                  # PowerShell
```

Add `-k fiber-cut` (or another case id) to record one case. Recording stops at the first failed
model call and keeps what it has; after a rate limit, wait a minute and run the same command, which
continues where it stopped. Recordings the investigation no longer asks for are deleted, files
are written with Unix line endings, and the run itself must pass the assertions of the test.
Delete a case's directory first to record it from scratch with a new model. Commit the changed
files.

## Why the prompts are the same on every machine

The key hashes the exact text, so anything that depends on the machine breaks replay. What was
checked, and what was pinned:

- **Numbers.** Tool text goes through `num` and `pct`, which round to 9 decimals first so that the
  last-bit differences of a sum or of `exp`/`log` on another platform cannot flip a rounding tie,
  and never print `-0`. The raw KPI values do differ in the last digits between Windows and Linux
  (the fixture world uses `numpy.exp`); no printed number changes.
- **Order.** Rows reach a prompt through queries with a total `ORDER BY`, or are sorted in code
  first, and sets are sorted before they are rendered. The run id and wall times are in no prompt.
- **Time.** Local time is `Africa/Tunis` through an explicit zone, never the machine's. SQL uses
  `AT TIME ZONE 'Africa/Tunis'` or sets the session zone. The result is the same under any `TZ`
  and any `PGTZ`.
- **Text.** Prompts, tool text and runbooks are ASCII; the repository stores LF.
- **Detector and runbooks.** The detector runs on the loaded world, and the runbook documents
  are deleted and re-embedded with the hashing embedder on every run, so no vectors from another
  test survive.
- **Runbook ranking.** pgvector computes distances in float32, which can differ in the last bits
  between CPUs. Exact ties are broken by chunk id, and the test checks that the runbook searches
  in the cassettes have no neighbours closer than 1e-6 in the candidate list. A re-recording
  that searches for something with a closer pair fails that check.

Not covered: a change of the Postgres or pgvector image (the compose file and CI use the floating
`pgvector/pgvector:pg17` tag) or of the locked numpy, pandas or Python versions can change what
the tools print; re-record if the replay fails after such an upgrade.
