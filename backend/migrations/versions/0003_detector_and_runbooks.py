"""anomaly detector output (anomalies, alerts) and runbook search (docs, chunks)

Revision ID: 0003
Revises: 0002
Create Date: 2026-10-10
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Must match incident_agent.rag.EMBEDDING_DIM (BAAI/bge-small-en-v1.5).
EMBEDDING_DIM = 384

UPGRADE = f"""
-- One alert = one group of anomalies that overlap in time and are related in the topology.
-- Alerts are what trigger investigations (M7) and what the detector is scored on.
CREATE TABLE alerts (
    alert_id     text PRIMARY KEY,                -- ALR-0001
    start_at     timestamptz NOT NULL,
    end_at       timestamptz NOT NULL,
    region_ids   text[] NOT NULL,                 -- empty = core / nationwide
    entity_ids   text[] NOT NULL,                 -- sites, regions or core nodes involved
    metrics      text[] NOT NULL,
    severity     text NOT NULL,                   -- low | medium | high
    score        double precision NOT NULL,       -- higher = more severe; used for ranking
    n_anomalies  integer NOT NULL,
    summary      text NOT NULL,                   -- one templated sentence, no LLM
    status       text NOT NULL DEFAULT 'new'      -- new | investigating | reported
);
CREATE INDEX ix_alerts_start_at ON alerts (start_at);

-- One anomaly = one entity, one metric, one continuous interval away from its baseline.
CREATE TABLE anomalies (
    anomaly_id      text PRIMARY KEY,             -- ANM-000001
    alert_id        text REFERENCES alerts (alert_id) ON DELETE SET NULL,
    entity_type     text NOT NULL,                -- site | region | core_node
    entity_id       text NOT NULL,
    region_id       text,                         -- null for core nodes
    metric          text NOT NULL,
    direction       text NOT NULL,                -- drop | spike
    start_at        timestamptz NOT NULL,
    end_at          timestamptz NOT NULL,
    n_steps         integer NOT NULL,
    peak_z          double precision NOT NULL,    -- signed robust z-score at the worst step
    baseline_value  double precision NOT NULL,    -- expected value at the worst step
    observed_value  double precision NOT NULL     -- actual value at the worst step
);
CREATE INDEX ix_anomalies_start_at ON anomalies (start_at);
CREATE INDEX ix_anomalies_entity ON anomalies (entity_id, start_at);
CREATE INDEX ix_anomalies_alert ON anomalies (alert_id);

CREATE TABLE runbook_docs (
    doc_id        text PRIMARY KEY,               -- RB-FIBER-CUT
    title         text NOT NULL,
    path          text NOT NULL,                  -- repo-relative source file
    tags          text[] NOT NULL,
    categories    text[] NOT NULL,                -- root-cause categories the doc applies to
    content_hash  text NOT NULL
);

CREATE TABLE runbook_chunks (
    chunk_id      text PRIMARY KEY,               -- RB-FIBER-CUT#03
    doc_id        text NOT NULL REFERENCES runbook_docs (doc_id) ON DELETE CASCADE,
    ordinal       integer NOT NULL,
    section_id    text NOT NULL,                  -- stable anchor, e.g. RB-FIBER-CUT/diagnosis
    heading_path  text NOT NULL,                  -- "Fiber cut > Diagnosis"
    content       text NOT NULL,
    n_tokens      integer NOT NULL,
    embedding     vector({EMBEDDING_DIM}) NOT NULL,
    tsv           tsvector GENERATED ALWAYS AS (
                      to_tsvector('english', heading_path || ' ' || content)
                  ) STORED
);
CREATE INDEX ix_runbook_chunks_doc ON runbook_chunks (doc_id, ordinal);
CREATE INDEX ix_runbook_chunks_embedding ON runbook_chunks
    USING hnsw (embedding vector_cosine_ops);
CREATE INDEX ix_runbook_chunks_tsv ON runbook_chunks USING gin (tsv);
"""

DOWNGRADE = """
DROP TABLE runbook_chunks;
DROP TABLE runbook_docs;
DROP TABLE anomalies;
DROP TABLE alerts;
"""


def upgrade() -> None:
    op.execute(UPGRADE)


def downgrade() -> None:
    op.execute(DOWNGRADE)
