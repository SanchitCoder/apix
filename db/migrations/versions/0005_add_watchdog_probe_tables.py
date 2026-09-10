"""add personalisation_probe_observation, dispersion_stat

Revision ID: 0005
Revises: 0004
Create Date: 2026-09-08

The personalised-pricing probe's landing tables. ``personalisation_probe_observation``
mirrors ``fare_quote``'s provenance shape (``run_id``, ``source_id``,
``collection_method``, ``legal_basis``, ``content_hash``, ``raw_payload_ref``) plus
three columns identifying which of the N session profiles produced the row; it reuses
the ``collection_method_enum``/``legal_basis_enum`` types migration 0001 already
created. ``dispersion_stat`` holds the computed per-probe dispersion statistic — the
"per-source dispersion statistic over time" the task asks be reported.

Surge detection and sell-out velocity are deliberately not given tables here: both are
cheap to recompute on demand from ``fare_quote``/``fare_quote_clean`` and do not carry
the same past-vintage auditability requirement a raw probe observation does.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_COLLECTION_METHOD_ENUM = postgresql.ENUM(
    "STATIC_HTML",
    "RENDERED_PAGE",
    "PUBLIC_JSON_API",
    "PARTNER_FEED",
    "FIXTURE",
    name="collection_method_enum",
    create_type=False,
)
_LEGAL_BASIS_ENUM = postgresql.ENUM(
    "ROBOTS_ALLOWED",
    "TOS_PERMITTED",
    "CONTRACTUAL",
    "OFFICIAL_PUBLICATION",
    "FIXTURE",
    name="legal_basis_enum",
    create_type=False,
)


def upgrade() -> None:
    op.create_table(
        "personalisation_probe_observation",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("probed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("run_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("source_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("collection_method", _COLLECTION_METHOD_ENUM, nullable=False),
        sa.Column("legal_basis", _LEGAL_BASIS_ENUM, nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("raw_payload_ref", sa.Text(), nullable=True),
        sa.Column("route_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("flight_key", sa.String(64), nullable=False),
        sa.Column("session_id", sa.String(64), nullable=False),
        sa.Column("cookie_state", sa.String(32), nullable=False),
        sa.Column("ua_class", sa.String(32), nullable=False),
        sa.Column("geography_tag", sa.String(32), nullable=False),
        sa.Column("total_fare", sa.Numeric(12, 2), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_personalisation_probe_observation"),
        sa.ForeignKeyConstraint(
            ["run_id"],
            ["collection_run.id"],
            name="fk_personalisation_probe_observation_run_id_collection_run",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["source_id"],
            ["source.id"],
            name="fk_personalisation_probe_observation_source_id_source",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["route_id"],
            ["route.id"],
            name="fk_personalisation_probe_observation_route_id_route",
            ondelete="RESTRICT",
        ),
        sa.CheckConstraint(
            "total_fare > 0", name="ck_personalisation_probe_observation_total_fare_positive"
        ),
    )
    op.create_index(
        "ix_personalisation_probe_observation_flight_probed",
        "personalisation_probe_observation",
        ["source_id", "flight_key", "probed_at"],
    )

    op.create_table(
        "dispersion_stat",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("source_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("flight_key", sa.String(64), nullable=False),
        sa.Column("probed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("statistic_name", sa.String(64), nullable=False),
        sa.Column("value", sa.Numeric(12, 2), nullable=False),
        sa.Column("n_sessions", sa.Integer(), nullable=False),
        sa.Column(
            "computed_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name="pk_dispersion_stat"),
        sa.ForeignKeyConstraint(
            ["source_id"],
            ["source.id"],
            name="fk_dispersion_stat_source_id_source",
            ondelete="RESTRICT",
        ),
        sa.CheckConstraint("n_sessions >= 1", name="ck_dispersion_stat_n_sessions_positive"),
        sa.CheckConstraint("value >= 0", name="ck_dispersion_stat_value_non_negative"),
    )
    op.create_index(
        "ix_dispersion_stat_source_flight_probed",
        "dispersion_stat",
        ["source_id", "flight_key", "probed_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_dispersion_stat_source_flight_probed", table_name="dispersion_stat")
    op.drop_table("dispersion_stat")
    op.drop_index(
        "ix_personalisation_probe_observation_flight_probed",
        table_name="personalisation_probe_observation",
    )
    op.drop_table("personalisation_probe_observation")
