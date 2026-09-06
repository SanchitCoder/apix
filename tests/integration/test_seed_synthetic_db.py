"""End-to-end synthetic seeding against a real, migrated database.

Marked ``integration``: skipped when no container runtime is available. This is the
test behind `make seed-synthetic DAYS=90` — same code path, smaller window.
"""

from __future__ import annotations

import shutil
from datetime import date

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text

from tests.conftest import requires_docker

pytestmark = [pytest.mark.integration, requires_docker]

DAYS = 7
START = date(2026, 6, 7)


@pytest.fixture(scope="module")
def seeded(postgres_url: str, repo_root, tmp_path_factory):
    """Migrate the throwaway database and run the synthetic seeder into it."""
    config = Config(str(repo_root / "alembic.ini"))
    config.set_main_option("script_location", str(repo_root / "db" / "migrations"))
    config.set_main_option("sqlalchemy.url", postgres_url)
    command.upgrade(config, "head")

    # Ground truth must land in a throwaway tree, not the repo's fixtures/.
    scratch_root = tmp_path_factory.mktemp("synthetic-repo")
    (scratch_root / "db").mkdir()
    shutil.copytree(repo_root / "db" / "seeds", scratch_root / "db" / "seeds")

    from apix_core.testing.seed import seed_synthetic

    counts = seed_synthetic(postgres_url, DAYS, START, scratch_root)

    engine = create_engine(postgres_url)
    try:
        yield engine, counts, scratch_root
    finally:
        engine.dispose()


def test_fare_quote_is_populated_and_traceable(seeded) -> None:
    engine, counts, _ = seeded
    with engine.connect() as conn:
        total = conn.execute(text("SELECT count(*) FROM fare_quote")).scalar()
        orphans = conn.execute(
            text(
                "SELECT count(*) FROM fare_quote fq "
                "LEFT JOIN collection_run cr ON cr.id = fq.run_id WHERE cr.id IS NULL"
            )
        ).scalar()
    assert total == counts["quotes"] > 0
    assert orphans == 0, "every quote must resolve to its collection run"


def test_every_row_is_tagged_synthetic(seeded) -> None:
    """The tag that makes generated data impossible to confuse with collected data."""
    engine, _, _ = seeded
    with engine.connect() as conn:
        methods = conn.execute(
            text("SELECT DISTINCT collection_method, legal_basis FROM fare_quote")
        ).all()
        source_types = (
            conn.execute(
                text(
                    "SELECT DISTINCT s.source_type FROM fare_quote fq "
                    "JOIN source s ON s.id = fq.source_id"
                )
            )
            .scalars()
            .all()
        )
    assert methods == [("SYNTHETIC", "SYNTHETIC")]
    assert source_types == ["SYNTHETIC"]


def test_reference_tables_are_seeded(seeded) -> None:
    engine, _, _ = seeded
    with engine.connect() as conn:
        airports = conn.execute(text("SELECT count(*) FROM airport")).scalar()
        routes = conn.execute(text("SELECT count(*) FROM route")).scalar()
    assert airports >= 116
    assert routes == 50


def test_seeding_is_idempotent(seeded, repo_root) -> None:
    """Re-running the same window adds nothing: deterministic ids meet ON CONFLICT."""
    engine, counts, scratch_root = seeded
    from apix_core.testing.seed import seed_synthetic

    seed_synthetic(str(engine.url.render_as_string(hide_password=False)), DAYS, START, scratch_root)
    with engine.connect() as conn:
        total = conn.execute(text("SELECT count(*) FROM fare_quote")).scalar()
    assert total == counts["quotes"]


def test_ground_truth_file_written(seeded) -> None:
    _, counts, scratch_root = seeded
    path = scratch_root / "fixtures" / "synthetic" / "anomaly_ground_truth.json"
    assert path.is_file()
    assert counts["anomalies"] > 0
