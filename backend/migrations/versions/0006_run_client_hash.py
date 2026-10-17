"""salted hash of the client that started a run, for the per-client daily limit

Revision ID: 0006
Revises: 0005
Create Date: 2026-10-18
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

UPGRADE = """
-- First 16 hex characters of sha256(salt + client address). The address itself is never stored.
ALTER TABLE app.agent_runs ADD COLUMN client_hash text;
CREATE INDEX ix_agent_runs_client ON app.agent_runs (client_hash, started_at);
"""


def upgrade() -> None:
    op.execute(UPGRADE)


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS app.ix_agent_runs_client")
    op.execute("ALTER TABLE app.agent_runs DROP COLUMN IF EXISTS client_hash")
