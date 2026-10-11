"""stored event lists of investigations run through the API, in schema app

Revision ID: 0005
Revises: 0004
Create Date: 2026-10-11
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

UPGRADE = """
-- The enriched event list of a run, as it was streamed. One row per run.
CREATE TABLE app.run_events (
    run_id      text PRIMARY KEY REFERENCES app.agent_runs (run_id) ON DELETE CASCADE,
    events      jsonb NOT NULL,
    created_at  timestamptz NOT NULL DEFAULT now()
);

REVOKE ALL ON app.run_events FROM PUBLIC;
"""

REVOKE_FROM_AGENT_RO = """
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'agent_ro') THEN
        REVOKE ALL ON ALL TABLES IN SCHEMA app FROM agent_ro;
    END IF;
END
$$
"""


def upgrade() -> None:
    op.execute(UPGRADE)
    op.execute(REVOKE_FROM_AGENT_RO)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS app.run_events")
