"""``make seed`` — load airports, carriers, the route basket and sources into the database.

Thin CLI over :mod:`apix_core.seeding`, which owns the one definition of how seed
files become rows. Airports/carriers/routes are idempotent no-ops on a re-run; sources
and their policy are upserted, since a source's compliance position (see
``config/sources.yaml``) changes as ToS reviews land — see
``apix_core.seeding.sources`` for why that half is not also skip-on-conflict.
"""

from __future__ import annotations

import argparse

import structlog
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from apix_core.config import find_config_dir, load_basket, load_sources
from apix_core.seeding import seed_reference, seed_sources
from apix_core.settings import get_settings

log = structlog.get_logger(__name__)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Seed reference data (airports, carriers, routes, sources)."
    )
    parser.add_argument(
        "--database-url", default=None, help="target database (default: APIX_DATABASE_SYNC_URL)"
    )
    args = parser.parse_args(argv)

    settings = get_settings()
    database_url = args.database_url or settings.database_sync_url
    repo_root = find_config_dir().parent
    basket = load_basket()
    sources = load_sources()

    engine = create_engine(database_url)
    try:
        with Session(engine) as session:
            counts = seed_reference(session, repo_root / "db" / "seeds", basket)
            source_count = seed_sources(session, sources)
            session.commit()
    finally:
        engine.dispose()

    log.info(
        "reference_seed_finished",
        airports=counts.airports,
        carriers=counts.carriers,
        routes=counts.routes,
        basket_version=basket.basket_version,
        sources=source_count,
        sources_version=sources.version,
    )
    return 0


if __name__ == "__main__":  # pragma: no cover — exercised via the integration test
    raise SystemExit(main())
