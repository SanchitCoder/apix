"""add atf_price, cpi_airfare_index, dgca_fare_reference, rail_fare

Revision ID: 0004
Revises: 0003
Create Date: 2026-09-08

Four reference-series tables the nowcast bridge model, ATF pass-through estimate and
back-test harness score against. Every one of them follows the same "loader ready,
data NOT loaded" discipline as ``route.dgca_pax_share``: the schema lands here, in a
forward-only migration, but no row is inserted except by a human running the matching
loader (``apps/scheduler``'s ``atf_loader``/``cpi_loader``/``dgca_fare_loader``)
against a named, cited official release. See ``docs/data-sources.md``.

All four are append-only by convention (no UPDATE/DELETE rule is installed — unlike
``fare_quote``, these are low-volume, human-loaded tables where a rule would only get
in the way of a genuine correction load; the loaders themselves never overwrite, they
only insert a new row with a later ``collected_at``/``release_date``).
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "atf_price",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("price_date", sa.Date(), nullable=False),
        sa.Column("city", sa.String(64), nullable=False),
        sa.Column("price_per_kl", sa.Numeric(12, 2), nullable=False),
        sa.Column("source_note", sa.Text(), nullable=False),
        sa.Column(
            "collected_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name="pk_atf_price"),
        sa.CheckConstraint("price_per_kl > 0", name="ck_atf_price_price_per_kl_positive"),
    )
    op.create_index("ix_atf_price_date_city", "atf_price", ["price_date", "city"])

    op.create_table(
        "cpi_airfare_index",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("period", sa.Date(), nullable=False),
        sa.Column("value", sa.Numeric(14, 6), nullable=False),
        sa.Column("base_year", sa.String(16), nullable=False),
        sa.Column("release_date", sa.Date(), nullable=False),
        sa.Column("source_note", sa.Text(), nullable=False),
        sa.Column(
            "collected_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name="pk_cpi_airfare_index"),
        sa.CheckConstraint("value > 0", name="ck_cpi_airfare_index_value_positive"),
    )
    op.create_index(
        "ix_cpi_airfare_index_period_release", "cpi_airfare_index", ["period", "release_date"]
    )

    op.create_table(
        "dgca_fare_reference",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("route_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("period", sa.Date(), nullable=False),
        sa.Column("avg_fare", sa.Numeric(12, 2), nullable=False),
        sa.Column("source_note", sa.Text(), nullable=False),
        sa.Column(
            "collected_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name="pk_dgca_fare_reference"),
        sa.ForeignKeyConstraint(
            ["route_id"],
            ["route.id"],
            name="fk_dgca_fare_reference_route_id_route",
            ondelete="RESTRICT",
        ),
        sa.CheckConstraint("avg_fare > 0", name="ck_dgca_fare_reference_avg_fare_positive"),
    )
    op.create_index(
        "ix_dgca_fare_reference_route_period", "dgca_fare_reference", ["route_id", "period"]
    )

    op.create_table(
        "rail_fare",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("corridor_code", sa.String(32), nullable=False),
        sa.Column("effective_date", sa.Date(), nullable=False),
        sa.Column("fare", sa.Numeric(12, 2), nullable=False),
        sa.Column("source_note", sa.Text(), nullable=False),
        sa.Column(
            "collected_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name="pk_rail_fare"),
        sa.CheckConstraint("fare > 0", name="ck_rail_fare_fare_positive"),
    )
    op.create_index(
        "ix_rail_fare_corridor_effective", "rail_fare", ["corridor_code", "effective_date"]
    )


def downgrade() -> None:
    op.drop_index("ix_rail_fare_corridor_effective", table_name="rail_fare")
    op.drop_table("rail_fare")
    op.drop_index("ix_dgca_fare_reference_route_period", table_name="dgca_fare_reference")
    op.drop_table("dgca_fare_reference")
    op.drop_index("ix_cpi_airfare_index_period_release", table_name="cpi_airfare_index")
    op.drop_table("cpi_airfare_index")
    op.drop_index("ix_atf_price_date_city", table_name="atf_price")
    op.drop_table("atf_price")
