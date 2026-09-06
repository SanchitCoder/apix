"""Migrations against a real TimescaleDB.

Marked ``integration``: skipped when no container runtime is available, so ``make test``
stays useful on a laptop while CI runs the real thing.
"""

from __future__ import annotations

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text

from tests.conftest import requires_docker

pytestmark = [pytest.mark.integration, requires_docker]


@pytest.fixture(scope="module")
def migrated_engine(postgres_url: str, repo_root):
    """Run ``alembic upgrade head`` against the throwaway database."""
    sync_url = postgres_url.replace("postgresql+psycopg2://", "postgresql+psycopg2://")
    config = Config(str(repo_root / "alembic.ini"))
    config.set_main_option("script_location", str(repo_root / "db" / "migrations"))
    config.set_main_option("sqlalchemy.url", sync_url)
    command.upgrade(config, "head")
    engine = create_engine(sync_url)
    try:
        yield engine
    finally:
        engine.dispose()


def test_every_model_table_exists_after_migration(migrated_engine) -> None:
    """The migration and the models must not drift apart."""
    from apix_core.models import Base

    tables = set(inspect(migrated_engine).get_table_names())
    assert set(Base.metadata.tables) <= tables


def test_fare_quote_is_a_hypertable(migrated_engine) -> None:
    """The compose image ships TimescaleDB, so the hypertable path must have run."""
    with migrated_engine.connect() as conn:
        available = conn.execute(
            text("SELECT 1 FROM pg_extension WHERE extname = 'timescaledb'")
        ).scalar()
        if not available:
            pytest.skip("timescaledb extension not installed in this image")
        result = conn.execute(
            text(
                "SELECT 1 FROM timescaledb_information.hypertables "
                "WHERE hypertable_name = 'fare_quote'"
            )
        ).scalar()
    assert result == 1


def test_fare_quote_rejects_update_and_delete(migrated_engine) -> None:
    """Append-only is enforced by the database, not by convention.

    The rules make UPDATE and DELETE no-ops, so an accidental correction to raw evidence
    silently changes nothing rather than silently changing something.
    """
    with migrated_engine.connect() as conn:
        rules = (
            conn.execute(text("SELECT rulename FROM pg_rules WHERE tablename = 'fare_quote'"))
            .scalars()
            .all()
        )
    assert "fare_quote_no_update" in rules
    assert "fare_quote_no_delete" in rules


def test_treatment_check_constraints_are_installed(migrated_engine) -> None:
    with migrated_engine.connect() as conn:
        constraints = (
            conn.execute(
                text(
                    "SELECT conname FROM pg_constraint "
                    "WHERE conrelid = 'fare_quote_clean'::regclass AND contype = 'c'"
                )
            )
            .scalars()
            .all()
        )
    assert "ck_fare_quote_clean_imputed_needs_method" in constraints
    assert "ck_fare_quote_clean_outlier_needs_rule" in constraints
    assert "ck_fare_quote_clean_lineage_or_imputed" in constraints
