"""add SYNTHETIC to source_type, collection_method and legal_basis enums

Revision ID: 0002
Revises: 0001
Create Date: 2026-09-04

The labelled synthetic dataset (apix_core.testing) writes real rows into fare_quote so
the whole pipeline is exercisable without touching a live website. Those rows must be
impossible to confuse with collected data, so the tag is a first-class enum value on
all three provenance dimensions — source_type, collection_method and legal_basis —
rather than a naming convention.

ALTER TYPE ... ADD VALUE is used instead of recreating the types: the enums are already
referenced by live tables, and migrations are forward-only. Postgres cannot run
ADD VALUE inside the surrounding transaction and then use the value in the same
transaction, but nothing here uses it — the seeder runs later, in its own session.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

ENUMS = ("source_type_enum", "collection_method_enum", "legal_basis_enum")


def upgrade() -> None:
    # COMMIT first: ALTER TYPE ... ADD VALUE cannot run in a transaction block on
    # Postgres < 12, and on >= 12 the new value would be unusable until commit anyway.
    # Alembic re-opens a transaction for whatever runs next.
    with op.get_context().autocommit_block():
        for enum_name in ENUMS:
            op.execute(f"ALTER TYPE {enum_name} ADD VALUE IF NOT EXISTS 'SYNTHETIC'")


def downgrade() -> None:
    """Enum values cannot be removed in place; forward-only, like every migration.

    A local reset is `alembic downgrade base` (dropping the types) followed by
    `alembic upgrade head`.
    """
    raise NotImplementedError(
        "0002 adds enum values, which Postgres cannot remove in place. "
        "Reset a local database with `alembic downgrade base && alembic upgrade head`."
    )
