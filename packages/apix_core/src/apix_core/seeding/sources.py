"""Seed ``source`` and ``source_policy`` from ``config/sources.yaml``.

Unlike airports, carriers and routes, a source's compliance position changes over
time — a ToS review lands, a verdict changes, a source gets switched on — so this
upserts rather than skipping on conflict: re-running ``make seed`` after
``config/sources.yaml`` is edited must bring the database in line with it, since
``apix_core.policy.PolicyEngine`` reads the YAML directly but everything downstream
(``collection_run``, ``fare_quote``, ``policy_decision``) references these rows by
foreign key and needs them to exist and stay current.
"""

from __future__ import annotations

import uuid
from decimal import Decimal
from typing import TYPE_CHECKING, Any

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from apix_core.models.collection import Source, SourcePolicy

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

    from apix_core.config.sources import SourcesConfig


def source_rows(config: SourcesConfig) -> list[dict[str, Any]]:
    return [
        {
            "code": source.code,
            "display_name": source.display_name,
            "domain": source.domain,
            "source_type": source.source_type.value,
            "enabled": source.enabled,
        }
        for source in config.sources
    ]


def source_policy_rows(
    config: SourcesConfig, source_ids: dict[str, uuid.UUID]
) -> list[dict[str, Any]]:
    rows = []
    for source in config.sources:
        policy = source.policy
        rows.append(
            {
                "source_id": source_ids[source.code],
                "robots_url": policy.robots_url,
                "allowed_paths": policy.allowed_paths,
                "disallowed_paths": policy.disallowed_paths,
                "crawl_delay_s": Decimal(str(policy.crawl_delay_s)),
                "max_requests_per_hour": policy.max_requests_per_hour,
                "tos_url": policy.tos_url,
                "tos_reviewed_at": policy.tos_reviewed_at,
                "tos_verdict": policy.tos_verdict.value,
                "legal_basis": policy.legal_basis.value if policy.legal_basis else None,
            }
        )
    return rows


def seed_sources(session: Session, config: SourcesConfig) -> int:
    """Upsert every source and its policy. Returns the number of sources seeded."""
    rows = source_rows(config)
    source_stmt = pg_insert(Source).values(rows)
    session.execute(
        source_stmt.on_conflict_do_update(
            index_elements=[Source.code],
            set_={
                "display_name": source_stmt.excluded.display_name,
                "domain": source_stmt.excluded.domain,
                "source_type": source_stmt.excluded.source_type,
                "enabled": source_stmt.excluded.enabled,
            },
        )
    )
    source_ids: dict[str, uuid.UUID] = dict(
        session.execute(select(Source.code, Source.id)).tuples().all()
    )

    policy_rows = source_policy_rows(config, source_ids)
    policy_stmt = pg_insert(SourcePolicy).values(policy_rows)
    session.execute(
        policy_stmt.on_conflict_do_update(
            index_elements=[SourcePolicy.source_id],
            set_={
                "robots_url": policy_stmt.excluded.robots_url,
                "allowed_paths": policy_stmt.excluded.allowed_paths,
                "disallowed_paths": policy_stmt.excluded.disallowed_paths,
                "crawl_delay_s": policy_stmt.excluded.crawl_delay_s,
                "max_requests_per_hour": policy_stmt.excluded.max_requests_per_hour,
                "tos_url": policy_stmt.excluded.tos_url,
                "tos_reviewed_at": policy_stmt.excluded.tos_reviewed_at,
                "tos_verdict": policy_stmt.excluded.tos_verdict,
                "legal_basis": policy_stmt.excluded.legal_basis,
            },
        )
    )
    return len(rows)


__all__ = ["seed_sources", "source_policy_rows", "source_rows"]
