"""agent trace store: runs and steps, in schema app (invisible to the read-only agent role)

Revision ID: 0004
Revises: 0003
Create Date: 2026-10-10
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

UPGRADE = """
CREATE SCHEMA app;

-- One row per investigation.
CREATE TABLE app.agent_runs (
    run_id         text PRIMARY KEY,
    question       text NOT NULL,
    asked_at       timestamptz NOT NULL,          -- the investigation's "now"
    trigger        text NOT NULL,                 -- user | alert | eval
    alert_id       text,
    status         text NOT NULL,                 -- running | finished | error
    started_at     timestamptz NOT NULL,
    finished_at    timestamptz,
    wall_seconds   double precision,
    config         jsonb NOT NULL DEFAULT '{}',
    scope          jsonb,
    report         jsonb,
    markdown       text,
    llm_calls      integer,
    tool_calls     integer,
    input_tokens   integer,
    output_tokens  integer,
    models_used    text[],                        -- provider:model of every LLM step
    fell_back      boolean,                       -- true if any step was answered by a fallback
    issues         jsonb,                         -- verification problems and run problems
    error          text
);
CREATE INDEX ix_agent_runs_started_at ON app.agent_runs (started_at);

-- One row per LLM call and per tool call, in order.
CREATE TABLE app.agent_steps (
    run_id         text NOT NULL REFERENCES app.agent_runs (run_id) ON DELETE CASCADE,
    seq            integer NOT NULL,
    kind           text NOT NULL,                 -- llm | tool
    node           text NOT NULL,                 -- intake | orient | investigate | conclude | repair
    name           text NOT NULL,                 -- the tool, or the purpose of the LLM call
    call_ref       text,                          -- T1, T2, ... for tool steps
    input          jsonb,
    output         jsonb,
    provider       text,
    model          text,
    input_tokens   integer,
    output_tokens  integer,
    latency_ms     integer,                       -- the call itself (the original, if replayed)
    wall_ms        integer,                       -- time the run waited for it
    cached         boolean,
    fell_back      boolean,
    error          text,
    created_at     timestamptz NOT NULL,
    PRIMARY KEY (run_id, seq)
);

REVOKE ALL ON SCHEMA app FROM PUBLIC;
"""

REVOKE_FROM_AGENT_RO = """
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'agent_ro') THEN
        REVOKE ALL ON SCHEMA app FROM agent_ro;
        REVOKE ALL ON ALL TABLES IN SCHEMA app FROM agent_ro;
    END IF;
END
$$
"""


def upgrade() -> None:
    op.execute(UPGRADE)
    op.execute(REVOKE_FROM_AGENT_RO)


def downgrade() -> None:
    op.execute("DROP SCHEMA IF EXISTS app CASCADE")
