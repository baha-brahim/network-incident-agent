"""synthetic network tables, ground-truth schema and regional KPI view

Mirrors incident_agent.simulator.world.SCHEMA (a unit test keeps the two in sync).
Everything except scenarios lives in `public`; the labels live in `gt`, which the
agent's read-only role must not be able to see.

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-10
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql as pg

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

GT_SCHEMA = "gt"
VIEW_NAME = "region_kpis_15m"


def _text(name: str, *, null: bool = False, pk: bool = False) -> sa.Column[str]:
    return sa.Column(name, sa.Text, nullable=null, primary_key=pk)


def _float(name: str, *, null: bool = False) -> sa.Column[float]:
    return sa.Column(name, pg.DOUBLE_PRECISION, nullable=null)


def _int(name: str) -> sa.Column[int]:
    return sa.Column(name, sa.Integer, nullable=False)


def _bool(name: str) -> sa.Column[bool]:
    return sa.Column(name, sa.Boolean, nullable=False)


def _ts(name: str, *, null: bool = False, pk: bool = False) -> sa.Column[sa.DateTime]:
    return sa.Column(name, sa.TIMESTAMP(timezone=True), nullable=null, primary_key=pk)


def _text_array(name: str) -> sa.Column[list[str]]:
    return sa.Column(name, pg.ARRAY(sa.Text), nullable=False)


def _json(name: str) -> sa.Column[object]:
    return sa.Column(name, pg.JSONB, nullable=False)


def build_metadata() -> sa.MetaData:
    """The tables created by this migration (also imported by the schema-drift unit test)."""
    md = sa.MetaData()

    sa.Table(
        "regions",
        md,
        _text("region_id", pk=True),
        _text("name"),
    )
    sa.Table(
        "nodes",
        md,
        _text("node_id", pk=True),
        _text("node_type"),
        _text("name"),
        _text("region_id", null=True),
        _text("parent_id", null=True),
        _json("attrs"),
        sa.ForeignKeyConstraint(["region_id"], ["regions.region_id"]),
        sa.ForeignKeyConstraint(["parent_id"], ["nodes.node_id"]),
        sa.Index("ix_nodes_parent_id", "parent_id"),
    )
    sa.Table(
        "cells",
        md,
        _text("cell_id", pk=True),
        _text("site_id"),
        _text("technology"),
        _int("sector"),
        _float("capacity_mbps"),
        sa.ForeignKeyConstraint(["site_id"], ["nodes.node_id"]),
        sa.Index("ix_cells_site_id", "site_id"),
    )
    sa.Table(
        "cell_kpis",
        md,
        _ts("ts"),
        _text("cell_id"),
        _float("dl_volume_mb"),
        _float("ul_volume_mb"),
        _float("active_users"),
        _float("rrc_success_pct", null=True),  # NULL while the cell is down
        _float("drop_rate_pct", null=True),
        _float("latency_ms", null=True),
        _float("prb_util_pct"),
        _float("availability_pct"),
        sa.ForeignKeyConstraint(["cell_id"], ["cells.cell_id"]),
        sa.PrimaryKeyConstraint("cell_id", "ts"),
        sa.Index("ix_cell_kpis_ts", "ts"),
    )
    sa.Table(
        "core_kpis",
        md,
        _ts("ts"),
        _text("node_id"),
        _text("metric"),
        _float("value"),
        sa.ForeignKeyConstraint(["node_id"], ["nodes.node_id"]),
        sa.PrimaryKeyConstraint("node_id", "metric", "ts"),
    )
    sa.Table(
        "alarms",
        md,
        _text("alarm_id", pk=True),
        _text("node_id"),
        _text("alarm_type"),
        _text("severity"),
        _ts("raised_at"),
        _ts("cleared_at", null=True),
        _text("description"),
        sa.ForeignKeyConstraint(["node_id"], ["nodes.node_id"]),
        sa.Index("ix_alarms_raised_at", "raised_at"),
        sa.Index("ix_alarms_node_id", "node_id"),
    )
    sa.Table(
        "changes",
        md,
        _text("change_id", pk=True),
        _text("node_id"),
        _text("change_type"),
        _ts("executed_at"),
        _text("description"),
        _text("ticket"),
        _text("status"),
        _text("rollback_of", null=True),
        sa.ForeignKeyConstraint(["node_id"], ["nodes.node_id"]),
        sa.ForeignKeyConstraint(["rollback_of"], ["changes.change_id"]),
        sa.Index("ix_changes_executed_at", "executed_at"),
        sa.Index("ix_changes_node_id", "node_id"),
    )
    sa.Table(
        "maintenance",
        md,
        _text("mw_id", pk=True),
        _text("node_id"),
        _ts("start_at"),
        _ts("end_at"),
        _text("description"),
        _text("expected_impact"),
        _text("status"),
        sa.ForeignKeyConstraint(["node_id"], ["nodes.node_id"]),
        sa.Index("ix_maintenance_start_at", "start_at"),
        sa.Index("ix_maintenance_node_id", "node_id"),
    )
    sa.Table(
        "external_events",
        md,
        _text("event_id", pk=True),
        _text("region_id", null=True),
        _text("node_id", null=True),
        _text("event_type"),
        _ts("start_at"),
        _ts("end_at"),
        _text("description"),
        sa.ForeignKeyConstraint(["region_id"], ["regions.region_id"]),
        sa.ForeignKeyConstraint(["node_id"], ["nodes.node_id"]),
        sa.Index("ix_external_events_start_at", "start_at"),
    )
    sa.Table(
        "dataset_meta",
        md,
        _text("key", pk=True),
        _text("value"),
    )
    sa.Table(
        "scenarios",
        md,
        _text("scenario_id", pk=True),
        _text("kind"),
        _bool("is_incident"),
        _text("root_cause_category"),
        _text("root_cause_node_id", null=True),
        _ts("start_at"),
        _ts("impact_start_at"),
        _ts("end_at"),
        _text_array("affected_node_ids"),
        _text_array("affected_region_ids"),
        _text("severity"),
        _text("difficulty"),
        _json("evidence"),
        _text_array("expected_tools"),
        _json("questions"),
        _json("confounders"),
        _text("notes"),
        sa.ForeignKeyConstraint(["root_cause_node_id"], ["nodes.node_id"]),
        sa.Index("ix_scenarios_start_at", "start_at"),
        schema=GT_SCHEMA,
    )
    return md


# Quality KPIs are traffic-weighted over the cells that reported them (NULL while a cell is
# down); a region with no reporting cell gets NULL.
REGION_KPIS_VIEW = f"""
CREATE VIEW public.{VIEW_NAME} AS
SELECT
    n.region_id,
    k.ts,
    SUM(k.dl_volume_mb) AS dl_volume_mb,
    SUM(k.ul_volume_mb) AS ul_volume_mb,
    SUM(k.active_users) AS active_users,
    COALESCE(SUM(k.latency_ms * k.dl_volume_mb)
             / NULLIF(SUM(k.dl_volume_mb) FILTER (WHERE k.latency_ms IS NOT NULL), 0),
             AVG(k.latency_ms)) AS latency_ms,
    COALESCE(SUM(k.drop_rate_pct * k.dl_volume_mb)
             / NULLIF(SUM(k.dl_volume_mb) FILTER (WHERE k.drop_rate_pct IS NOT NULL), 0),
             AVG(k.drop_rate_pct)) AS drop_rate_pct,
    COALESCE(SUM(k.rrc_success_pct * k.dl_volume_mb)
             / NULLIF(SUM(k.dl_volume_mb) FILTER (WHERE k.rrc_success_pct IS NOT NULL), 0),
             AVG(k.rrc_success_pct)) AS rrc_success_pct,
    AVG(k.prb_util_pct) AS prb_util_pct,
    MIN(k.availability_pct) AS min_availability_pct,
    COUNT(*) FILTER (WHERE k.availability_pct < 50) AS cells_down
FROM public.cell_kpis k
JOIN public.cells c ON c.cell_id = k.cell_id
JOIN public.nodes n ON n.node_id = c.site_id
GROUP BY n.region_id, k.ts
"""

# agent_ro is created by docker/postgres/init.sql; it may be absent on other hosts.
REVOKE_GT_FROM_AGENT_RO = f"""
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'agent_ro') THEN
        REVOKE ALL ON SCHEMA {GT_SCHEMA} FROM agent_ro;
        REVOKE ALL ON ALL TABLES IN SCHEMA {GT_SCHEMA} FROM agent_ro;
    END IF;
END
$$
"""


def upgrade() -> None:
    bind = op.get_bind()
    op.execute(f"CREATE SCHEMA {GT_SCHEMA}")
    build_metadata().create_all(bind)
    op.execute(REGION_KPIS_VIEW)
    op.execute(f"REVOKE ALL ON SCHEMA {GT_SCHEMA} FROM PUBLIC")
    op.execute(REVOKE_GT_FROM_AGENT_RO)


def downgrade() -> None:
    op.execute(f"DROP VIEW IF EXISTS public.{VIEW_NAME}")
    build_metadata().drop_all(op.get_bind())
    op.execute(f"DROP SCHEMA IF EXISTS {GT_SCHEMA} CASCADE")
