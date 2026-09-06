"""The data model is a contract. These tests pin the parts later phases depend on."""

from __future__ import annotations

import pytest
from sqlalchemy.schema import CreateTable

from apix_core.models import Base, FareQuote, FareQuoteClean, IndexValue, Route

EXPECTED_TABLES = {
    "airport",
    "carrier",
    "route",
    "source",
    "source_policy",
    "policy_decision",
    "collection_run",
    "fare_quote",
    "fare_quote_clean",
    "data_snapshot",
    "method_config",
    "index_run",
    "series",
    "index_value",
    "revision_log",
    "nowcast_value",
}


def test_every_expected_table_is_registered() -> None:
    assert set(Base.metadata.tables) == EXPECTED_TABLES


def test_fare_quote_primary_key_includes_the_partition_column() -> None:
    """Timescale requires the partition column in every unique index.

    fare_quote is a hypertable on collected_at, so its primary key is
    (id, collected_at). Reducing this to (id) would make migration 0001 fail at
    create_hypertable.
    """
    assert [c.name for c in FareQuote.__table__.primary_key.columns] == ["id", "collected_at"]


def test_clean_rows_carry_the_composite_key_back_to_the_raw_quote() -> None:
    """Provenance is a real foreign key, not a convention."""
    fks = {
        tuple(sorted(fk.column_keys)): fk for fk in FareQuoteClean.__table__.foreign_key_constraints
    }
    assert ("quote_collected_at", "quote_id") in fks


@pytest.mark.parametrize(
    ("table", "columns"),
    [
        ("fare_quote", ("route_id", "travel_date")),
        ("fare_quote", ("route_id", "advance_days", "query_date")),
        ("index_value", ("series_id", "period")),
    ],
)
def test_dashboard_query_patterns_are_indexed(table: str, columns: tuple[str, ...]) -> None:
    """The dashboard's hot paths must not be sequential scans."""
    indexed = {
        tuple(c.name for c in index.columns) for index in Base.metadata.tables[table].indexes
    }
    assert columns in indexed, f"{table} has no index on {columns}"


def test_index_value_is_keyed_by_run_so_vintages_survive() -> None:
    """A recomputed period is a new row, not an overwrite. That is what makes
    /v1/index/vintage answerable and revisions visible."""
    assert [c.name for c in IndexValue.__table__.primary_key.columns] == [
        "index_run_id",
        "series_id",
        "period",
    ]


def test_treatment_flags_cannot_be_set_without_a_reason() -> None:
    """Nothing fails silently: an outlier or an imputation carries why."""
    checks = {c.name for c in FareQuoteClean.__table__.constraints if c.name}
    assert "ck_fare_quote_clean_outlier_needs_rule" in checks
    assert "ck_fare_quote_clean_imputed_needs_method" in checks
    assert "ck_fare_quote_clean_lineage_or_imputed" in checks


def test_dgca_pax_share_is_nullable() -> None:
    """Phase 2 populates it. Until then, null is the honest value."""
    assert Route.__table__.c.dgca_pax_share.nullable is True


def test_every_table_compiles_to_postgres_ddl() -> None:
    """Catches a type or constraint that has no PostgreSQL rendering."""
    from sqlalchemy.dialects import postgresql

    for table in Base.metadata.sorted_tables:
        ddl = str(CreateTable(table).compile(dialect=postgresql.dialect()))
        assert ddl.startswith("\nCREATE TABLE")
