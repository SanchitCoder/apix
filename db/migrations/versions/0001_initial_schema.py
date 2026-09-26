"""initial schema — reference, collection, quotes, clean, index, nowcast

Revision ID: 0001
Revises:
Create Date: 2026-09-04

Establishes the full APIx data model in one forward-only revision.

Two things in here are not plain DDL and deserve to be read before they are changed:

1. ``fare_quote`` becomes a TimescaleDB hypertable partitioned on ``collected_at``.
   Timescale requires the partitioning column to be part of every unique index, which
   is why the table's primary key is ``(id, collected_at)`` and why
   ``fare_quote_clean`` carries ``quote_collected_at`` alongside ``quote_id`` to form a
   real composite foreign key. If the ``timescaledb`` extension is unavailable (a plain
   Postgres in CI, for instance) the table stays an ordinary table and everything else
   still works — the schema is identical either way.

2. ``fare_quote`` is made append-only at the database level with rules that reject
   UPDATE and DELETE. This is guardrail five in CLAUDE.md, enforced rather than
   documented. Corrections belong in ``fare_quote_clean``.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


# Native enum types. Created once, referenced with create_type=False thereafter.
ENUM_TYPES: dict[str, tuple[str, ...]] = {
    "carrier_type_enum": ("FSC", "LCC", "REGIONAL", "CHARTER"),
    "source_type_enum": ("AIRLINE", "OTA", "METASEARCH", "GDS", "OFFICIAL"),
    "collection_method_enum": (
        "STATIC_HTML",
        "RENDERED_PAGE",
        "PUBLIC_JSON_API",
        "PARTNER_FEED",
        "FIXTURE",
    ),
    "legal_basis_enum": (
        "ROBOTS_ALLOWED",
        "TOS_PERMITTED",
        "CONTRACTUAL",
        "OFFICIAL_PUBLICATION",
        "FIXTURE",
    ),
    "tos_verdict_enum": ("PERMITTED", "PROHIBITED", "AMBIGUOUS", "NOT_REVIEWED"),
    "policy_decision_outcome_enum": (
        "ALLOWED",
        "DENIED_ROBOTS",
        "DENIED_TOS",
        "DENIED_RATE_LIMIT",
        "DENIED_PATH",
        "DENIED_SOURCE_DISABLED",
        "DENIED_CAPTCHA",
    ),
    "run_status_enum": ("PENDING", "RUNNING", "SUCCEEDED", "PARTIAL", "FAILED", "BLOCKED"),
    "fare_class_enum": ("ECONOMY", "PREMIUM_ECONOMY", "BUSINESS", "FIRST"),
    "frequency_enum": ("D", "W", "M", "Q", "A"),
}


def _enum(name: str) -> postgresql.ENUM:
    """Reference an already-created enum type."""
    return postgresql.ENUM(*ENUM_TYPES[name], name=name, create_type=False)


def upgrade() -> None:
    bind = op.get_bind()

    # gen_random_uuid() lives in pgcrypto on PG<13 and in core from PG13. Postgres 16
    # is pinned, but the extension is requested explicitly so the default is portable.
    op.execute("CREATE EXTENSION IF NOT EXISTS pgcrypto")

    for name, values in ENUM_TYPES.items():
        postgresql.ENUM(*values, name=name).create(bind, checkfirst=True)

    # ------------------------------------------------------------- reference ----
    op.create_table(
        "airport",
        sa.Column("iata", sa.String(3), nullable=False),
        sa.Column("icao", sa.String(4), nullable=True),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column("city", sa.String(64), nullable=False),
        sa.Column("state", sa.String(64), nullable=True),
        sa.Column("lat", sa.Numeric(9, 6), nullable=True),
        sa.Column("lon", sa.Numeric(9, 6), nullable=True),
        sa.PrimaryKeyConstraint("iata", name="pk_airport"),
        sa.UniqueConstraint("icao", name="uq_airport_icao"),
        sa.CheckConstraint("char_length(iata) = 3", name="ck_airport_iata_len"),
        sa.CheckConstraint("lat IS NULL OR (lat BETWEEN -90 AND 90)", name="ck_airport_lat_range"),
        sa.CheckConstraint(
            "lon IS NULL OR (lon BETWEEN -180 AND 180)", name="ck_airport_lon_range"
        ),
    )
    op.create_index("ix_airport_city", "airport", ["city"])

    op.create_table(
        "carrier",
        sa.Column("iata", sa.String(2), nullable=False),
        sa.Column("icao", sa.String(3), nullable=True),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column("carrier_type", _enum("carrier_type_enum"), nullable=False),
        sa.PrimaryKeyConstraint("iata", name="pk_carrier"),
        sa.UniqueConstraint("icao", name="uq_carrier_icao"),
        sa.CheckConstraint("char_length(iata) = 2", name="ck_carrier_iata_len"),
    )

    op.create_table(
        "route",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("origin_iata", sa.String(3), nullable=False),
        sa.Column("dest_iata", sa.String(3), nullable=False),
        sa.Column("code", sa.String(7), nullable=False),
        sa.Column("dgca_pax_share", sa.Numeric(9, 8), nullable=True),
        sa.Column("basket_version", sa.String(32), nullable=False),
        sa.Column("active_from", sa.Date(), nullable=False),
        sa.Column("active_to", sa.Date(), nullable=True),
        sa.PrimaryKeyConstraint("id", name="pk_route"),
        sa.ForeignKeyConstraint(
            ["origin_iata"],
            ["airport.iata"],
            name="fk_route_origin_iata_airport",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["dest_iata"], ["airport.iata"], name="fk_route_dest_iata_airport", ondelete="RESTRICT"
        ),
        sa.UniqueConstraint("code", name="uq_route_code"),
        sa.UniqueConstraint(
            "origin_iata", "dest_iata", "basket_version", name="uq_route_pair_version"
        ),
        sa.CheckConstraint("origin_iata <> dest_iata", name="ck_route_distinct_endpoints"),
        sa.CheckConstraint(
            "dgca_pax_share IS NULL OR (dgca_pax_share >= 0 AND dgca_pax_share <= 1)",
            name="ck_route_pax_share_unit_interval",
        ),
        sa.CheckConstraint(
            "active_to IS NULL OR active_to > active_from", name="ck_route_active_window"
        ),
    )
    op.create_index(
        "ix_route_basket_version_active", "route", ["basket_version", "active_from", "active_to"]
    )

    # ------------------------------------------------------------ collection ----
    op.create_table(
        "source",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("code", sa.String(32), nullable=False),
        sa.Column("display_name", sa.String(128), nullable=False),
        sa.Column("domain", sa.String(255), nullable=False),
        sa.Column("source_type", _enum("source_type_enum"), nullable=False),
        sa.Column("enabled", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_source"),
        sa.UniqueConstraint("code", name="uq_source_code"),
    )
    op.create_index("ix_source_enabled", "source", ["enabled"])

    op.create_table(
        "source_policy",
        sa.Column("source_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("robots_url", sa.String(512), nullable=True),
        sa.Column(
            "allowed_paths",
            postgresql.JSONB(),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "disallowed_paths",
            postgresql.JSONB(),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column("crawl_delay_s", sa.Numeric(6, 2), server_default=sa.text("2.0"), nullable=False),
        sa.Column(
            "max_requests_per_hour", sa.Integer(), server_default=sa.text("60"), nullable=False
        ),
        sa.Column("tos_url", sa.String(512), nullable=True),
        sa.Column("tos_reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "tos_verdict",
            _enum("tos_verdict_enum"),
            server_default=sa.text("'NOT_REVIEWED'"),
            nullable=False,
        ),
        sa.Column("legal_basis", sa.String(64), nullable=True),
        sa.Column("robots_fetched_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("robots_etag", sa.String(128), nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("source_id", name="pk_source_policy"),
        sa.ForeignKeyConstraint(
            ["source_id"],
            ["source.id"],
            name="fk_source_policy_source_id_source",
            ondelete="CASCADE",
        ),
        sa.CheckConstraint("crawl_delay_s >= 0", name="ck_source_policy_crawl_delay_non_negative"),
        sa.CheckConstraint(
            "max_requests_per_hour > 0", name="ck_source_policy_rate_limit_positive"
        ),
    )

    op.create_table(
        "policy_decision",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("source_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("url_hash", sa.String(64), nullable=False),
        sa.Column("decision", _enum("policy_decision_outcome_enum"), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column(
            "decided_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name="pk_policy_decision"),
        sa.ForeignKeyConstraint(
            ["source_id"],
            ["source.id"],
            name="fk_policy_decision_source_id_source",
            ondelete="RESTRICT",
        ),
    )
    op.create_index(
        "ix_policy_decision_source_decided", "policy_decision", ["source_id", "decided_at"]
    )
    op.create_index("ix_policy_decision_url_hash", "policy_decision", ["url_hash"])

    op.create_table(
        "collection_run",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("source_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("route_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "started_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "status", _enum("run_status_enum"), server_default=sa.text("'PENDING'"), nullable=False
        ),
        sa.Column("quotes_collected", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("blocked_count", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("error_class", sa.String(128), nullable=True),
        sa.Column("error_detail", postgresql.JSONB(), nullable=True),
        sa.PrimaryKeyConstraint("id", name="pk_collection_run"),
        sa.ForeignKeyConstraint(
            ["source_id"],
            ["source.id"],
            name="fk_collection_run_source_id_source",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["route_id"], ["route.id"], name="fk_collection_run_route_id_route", ondelete="RESTRICT"
        ),
        sa.CheckConstraint("quotes_collected >= 0", name="ck_collection_run_quotes_non_negative"),
        sa.CheckConstraint("blocked_count >= 0", name="ck_collection_run_blocked_non_negative"),
        sa.CheckConstraint(
            "finished_at IS NULL OR finished_at >= started_at",
            name="ck_collection_run_finished_after_started",
        ),
    )
    op.create_index(
        "ix_collection_run_source_started", "collection_run", ["source_id", "started_at"]
    )
    op.create_index("ix_collection_run_route_started", "collection_run", ["route_id", "started_at"])
    op.create_index("ix_collection_run_status", "collection_run", ["status"])

    # ------------------------------------------------------------ index core ----
    # data_snapshot is created before fare_quote_clean, which references it.
    op.create_table(
        "data_snapshot",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("row_count", sa.BigInteger(), nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("id", name="pk_data_snapshot"),
        sa.CheckConstraint("row_count >= 0", name="ck_data_snapshot_row_count_non_negative"),
    )
    op.create_index("ix_data_snapshot_content_hash", "data_snapshot", ["content_hash"])
    op.create_index("ix_data_snapshot_created_at", "data_snapshot", ["created_at"])

    op.create_table(
        "method_config",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("config_hash", sa.String(64), nullable=False),
        sa.Column("config", postgresql.JSONB(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name="pk_method_config"),
        sa.UniqueConstraint("config_hash", name="uq_method_config_config_hash"),
    )

    op.create_table(
        "index_run",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("snapshot_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("method_config_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("vintage_date", sa.Date(), nullable=False),
        sa.Column(
            "computed_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "status", _enum("run_status_enum"), server_default=sa.text("'PENDING'"), nullable=False
        ),
        sa.PrimaryKeyConstraint("id", name="pk_index_run"),
        sa.ForeignKeyConstraint(
            ["snapshot_id"],
            ["data_snapshot.id"],
            name="fk_index_run_snapshot_id_data_snapshot",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["method_config_id"],
            ["method_config.id"],
            name="fk_index_run_method_config_id_method_config",
            ondelete="RESTRICT",
        ),
    )
    op.create_index("ix_index_run_vintage_date", "index_run", ["vintage_date"])
    op.create_index(
        "ix_index_run_snapshot_method", "index_run", ["snapshot_id", "method_config_id"]
    )

    op.create_table(
        "series",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("code", sa.String(64), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column(
            "dimensions", postgresql.JSONB(), server_default=sa.text("'{}'::jsonb"), nullable=False
        ),
        sa.Column("frequency", _enum("frequency_enum"), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_series"),
        sa.UniqueConstraint("code", name="uq_series_code"),
    )
    op.create_index("ix_series_dimensions", "series", ["dimensions"], postgresql_using="gin")

    op.create_table(
        "index_value",
        sa.Column("index_run_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("series_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("period", sa.Date(), nullable=False),
        sa.Column("value", sa.Numeric(14, 6), nullable=False),
        sa.Column("n_quotes", sa.BigInteger(), nullable=False),
        sa.Column("coverage_pct", sa.Numeric(5, 2), nullable=True),
        sa.PrimaryKeyConstraint("index_run_id", "series_id", "period", name="pk_index_value"),
        sa.ForeignKeyConstraint(
            ["index_run_id"],
            ["index_run.id"],
            name="fk_index_value_index_run_id_index_run",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["series_id"],
            ["series.id"],
            name="fk_index_value_series_id_series",
            ondelete="RESTRICT",
        ),
        sa.CheckConstraint("n_quotes >= 0", name="ck_index_value_n_quotes_non_negative"),
        sa.CheckConstraint(
            "coverage_pct IS NULL OR (coverage_pct >= 0 AND coverage_pct <= 100)",
            name="ck_index_value_coverage_pct_range",
        ),
    )
    op.create_index("ix_index_value_series_period", "index_value", ["series_id", "period"])
    op.create_index("ix_index_value_run", "index_value", ["index_run_id"])

    op.create_table(
        "revision_log",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("series_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("period", sa.Date(), nullable=False),
        sa.Column("old_value", sa.Numeric(14, 6), nullable=True),
        sa.Column("new_value", sa.Numeric(14, 6), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column(
            "revised_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name="pk_revision_log"),
        sa.ForeignKeyConstraint(
            ["series_id"],
            ["series.id"],
            name="fk_revision_log_series_id_series",
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint("series_id", "period", "revised_at", name="uq_revision_log_event"),
    )
    op.create_index("ix_revision_log_series_period", "revision_log", ["series_id", "period"])

    # ---------------------------------------------------------------- quotes ----
    op.create_table(
        "fare_quote",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column(
            "collected_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("run_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("source_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("collection_method", _enum("collection_method_enum"), nullable=False),
        sa.Column("legal_basis", _enum("legal_basis_enum"), nullable=False),
        sa.Column("source_url_hash", sa.String(64), nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("raw_payload_ref", sa.Text(), nullable=True),
        sa.Column("route_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("carrier_iata", sa.String(2), nullable=False),
        sa.Column("flight_number", sa.String(8), nullable=True),
        sa.Column("dep_datetime_local", sa.DateTime(timezone=False), nullable=False),
        sa.Column("arr_datetime_local", sa.DateTime(timezone=False), nullable=True),
        sa.Column("stops", sa.SmallInteger(), server_default=sa.text("0"), nullable=False),
        sa.Column("travel_date", sa.Date(), nullable=False),
        sa.Column("query_date", sa.Date(), nullable=False),
        sa.Column("advance_days", sa.SmallInteger(), nullable=False),
        sa.Column(
            "fare_class",
            _enum("fare_class_enum"),
            server_default=sa.text("'ECONOMY'"),
            nullable=False,
        ),
        sa.Column("fare_brand", sa.String(64), nullable=True),
        sa.Column("base_fare", sa.Numeric(12, 2), nullable=True),
        sa.Column("taxes", sa.Numeric(12, 2), nullable=True),
        sa.Column("udf", sa.Numeric(12, 2), nullable=True),
        sa.Column("convenience_fee", sa.Numeric(12, 2), nullable=True),
        sa.Column("total_fare", sa.Numeric(12, 2), nullable=False),
        sa.Column("currency", sa.String(3), server_default=sa.text("'INR'"), nullable=False),
        sa.Column("seats_shown", sa.Integer(), nullable=True),
        sa.Column("refundable", sa.Boolean(), nullable=True),
        sa.Column("baggage_included", sa.Boolean(), nullable=True),
        # Composite PK: Timescale requires the partition column in every unique index.
        sa.PrimaryKeyConstraint("id", "collected_at", name="pk_fare_quote"),
        sa.ForeignKeyConstraint(
            ["run_id"],
            ["collection_run.id"],
            name="fk_fare_quote_run_id_collection_run",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["source_id"], ["source.id"], name="fk_fare_quote_source_id_source", ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["route_id"], ["route.id"], name="fk_fare_quote_route_id_route", ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["carrier_iata"],
            ["carrier.iata"],
            name="fk_fare_quote_carrier_iata_carrier",
            ondelete="RESTRICT",
        ),
        sa.CheckConstraint("total_fare >= 0", name="ck_fare_quote_total_fare_non_negative"),
        sa.CheckConstraint(
            "base_fare IS NULL OR base_fare >= 0", name="ck_fare_quote_base_fare_non_negative"
        ),
        sa.CheckConstraint("stops >= 0 AND stops <= 4", name="ck_fare_quote_stops_plausible"),
        sa.CheckConstraint(
            "advance_days >= 0 AND advance_days <= 365", name="ck_fare_quote_advance_days_range"
        ),
        sa.CheckConstraint("travel_date >= query_date", name="ck_fare_quote_travel_after_query"),
        sa.CheckConstraint("char_length(currency) = 3", name="ck_fare_quote_currency_iso4217"),
        sa.CheckConstraint(
            "seats_shown IS NULL OR seats_shown >= 0", name="ck_fare_quote_seats_shown_non_negative"
        ),
    )
    op.create_index("ix_fare_quote_route_travel_date", "fare_quote", ["route_id", "travel_date"])
    op.create_index(
        "ix_fare_quote_route_advance_query",
        "fare_quote",
        ["route_id", "advance_days", "query_date"],
    )
    op.create_index("ix_fare_quote_collected_at", "fare_quote", ["collected_at"])
    op.create_index("ix_fare_quote_run", "fare_quote", ["run_id"])
    op.create_index("ix_fare_quote_content_hash", "fare_quote", ["content_hash"])
    op.create_index(
        "uq_fare_quote_dedup", "fare_quote", ["content_hash", "collected_at"], unique=True
    )

    # Turn fare_quote into a hypertable when Timescale is present. Skipped, loudly, when
    # it is not, so a plain Postgres still yields an identical logical schema.
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM pg_available_extensions WHERE name = 'timescaledb') THEN
                CREATE EXTENSION IF NOT EXISTS timescaledb;
                PERFORM create_hypertable(
                    'fare_quote', 'collected_at',
                    chunk_time_interval => INTERVAL '7 days',
                    if_not_exists => TRUE,
                    migrate_data => TRUE
                );
            ELSE
                RAISE NOTICE 'timescaledb unavailable: fare_quote created as a plain table';
            END IF;
        END
        $$;
        """
    )

    # Append-only enforcement. fare_quote is evidence; it is never edited or deleted.
    # Postgres RULEs cannot be created on a hypertable ("hypertables do not support
    # rules"), so this is a BEFORE-trigger that returns NULL to skip the operation —
    # the same silent no-op DO INSTEAD NOTHING gave, but hypertable-compatible.
    op.execute(
        """
        CREATE OR REPLACE FUNCTION fare_quote_append_only() RETURNS trigger AS $$
        BEGIN
            RETURN NULL;
        END;
        $$ LANGUAGE plpgsql
        """
    )
    op.execute(
        "CREATE TRIGGER fare_quote_no_update BEFORE UPDATE ON fare_quote "
        "FOR EACH ROW EXECUTE FUNCTION fare_quote_append_only()"
    )
    op.execute(
        "CREATE TRIGGER fare_quote_no_delete BEFORE DELETE ON fare_quote "
        "FOR EACH ROW EXECUTE FUNCTION fare_quote_append_only()"
    )

    # ----------------------------------------------------------------- clean ----
    op.create_table(
        "fare_quote_clean",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("quote_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("quote_collected_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("snapshot_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("route_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("carrier_iata", sa.String(2), nullable=False),
        sa.Column("travel_date", sa.Date(), nullable=False),
        sa.Column("advance_days", sa.SmallInteger(), nullable=False),
        sa.Column("dep_hour_bucket", sa.SmallInteger(), nullable=False),
        sa.Column("stops", sa.SmallInteger(), nullable=False),
        sa.Column("base_fare", sa.Numeric(12, 2), nullable=True),
        sa.Column("total_fare", sa.Numeric(12, 2), nullable=False),
        sa.Column("is_outlier", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("outlier_rule", sa.String(64), nullable=True),
        sa.Column("is_imputed", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("imputation_method", sa.String(64), nullable=True),
        sa.Column(
            "quality_vector",
            postgresql.JSONB(),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name="pk_fare_quote_clean"),
        sa.ForeignKeyConstraint(
            ["quote_id", "quote_collected_at"],
            ["fare_quote.id", "fare_quote.collected_at"],
            name="fk_fare_quote_clean_quote",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["snapshot_id"],
            ["data_snapshot.id"],
            name="fk_fare_quote_clean_snapshot_id_data_snapshot",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["route_id"],
            ["route.id"],
            name="fk_fare_quote_clean_route_id_route",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["carrier_iata"],
            ["carrier.iata"],
            name="fk_fare_quote_clean_carrier_iata_carrier",
            ondelete="RESTRICT",
        ),
        sa.CheckConstraint(
            "(quote_id IS NOT NULL AND quote_collected_at IS NOT NULL) OR is_imputed",
            name="ck_fare_quote_clean_lineage_or_imputed",
        ),
        sa.CheckConstraint(
            "(NOT is_outlier) OR outlier_rule IS NOT NULL",
            name="ck_fare_quote_clean_outlier_needs_rule",
        ),
        sa.CheckConstraint(
            "(NOT is_imputed) OR imputation_method IS NOT NULL",
            name="ck_fare_quote_clean_imputed_needs_method",
        ),
        sa.CheckConstraint(
            "dep_hour_bucket BETWEEN 0 AND 23", name="ck_fare_quote_clean_dep_hour_bucket_range"
        ),
        sa.CheckConstraint(
            "advance_days >= 0 AND advance_days <= 365",
            name="ck_fare_quote_clean_advance_days_range",
        ),
        sa.CheckConstraint("total_fare >= 0", name="ck_fare_quote_clean_total_fare_non_negative"),
    )
    op.create_index(
        "ix_fare_quote_clean_route_travel_date", "fare_quote_clean", ["route_id", "travel_date"]
    )
    op.create_index(
        "ix_fare_quote_clean_route_advance_travel",
        "fare_quote_clean",
        ["route_id", "advance_days", "travel_date"],
    )
    op.create_index("ix_fare_quote_clean_snapshot", "fare_quote_clean", ["snapshot_id"])
    op.create_index("ix_fare_quote_clean_quote", "fare_quote_clean", ["quote_id"])

    # --------------------------------------------------------------- nowcast ----
    op.create_table(
        "nowcast_value",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("target_series", sa.String(64), nullable=False),
        sa.Column("target_period", sa.Date(), nullable=False),
        sa.Column("point_estimate", sa.Numeric(14, 6), nullable=False),
        sa.Column("ci_low", sa.Numeric(14, 6), nullable=True),
        sa.Column("ci_high", sa.Numeric(14, 6), nullable=True),
        sa.Column("model_version", sa.String(32), nullable=False),
        sa.Column(
            "produced_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name="pk_nowcast_value"),
        sa.CheckConstraint(
            "ci_low IS NULL OR ci_high IS NULL OR ci_low <= ci_high",
            name="ck_nowcast_value_ci_ordered",
        ),
    )
    op.create_index("ix_nowcast_value_target", "nowcast_value", ["target_series", "target_period"])
    op.create_index("ix_nowcast_value_produced_at", "nowcast_value", ["produced_at"])


def downgrade() -> None:
    """Drop everything this revision created.

    Present so a local database can be reset. Migrations are forward-only in any
    deployed environment: this is never run against staging or production.
    """
    op.execute("DROP TRIGGER IF EXISTS fare_quote_no_delete ON fare_quote")
    op.execute("DROP TRIGGER IF EXISTS fare_quote_no_update ON fare_quote")
    op.execute("DROP FUNCTION IF EXISTS fare_quote_append_only()")

    for table in (
        "nowcast_value",
        "fare_quote_clean",
        "fare_quote",
        "revision_log",
        "index_value",
        "series",
        "index_run",
        "method_config",
        "data_snapshot",
        "collection_run",
        "policy_decision",
        "source_policy",
        "source",
        "route",
        "carrier",
        "airport",
    ):
        op.drop_table(table)

    bind = op.get_bind()
    for name, values in ENUM_TYPES.items():
        postgresql.ENUM(*values, name=name).drop(bind, checkfirst=True)
