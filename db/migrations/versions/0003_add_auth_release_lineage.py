"""add api_key, index_run.released_at, index_value_quote lineage

Revision ID: 0003
Revises: 0002
Create Date: 2026-09-07

Three additions needed to serve /v1 from real data instead of examples:

1. ``index_run.released_at`` — the public/draft distinction the API auths on. Null means
   draft/pre-release; a public caller cannot see it. There is no separate editorial
   release step yet, so the index-run job sets this the moment a run succeeds.
2. ``api_key`` — bearer credentials for the researcher and official tiers. Public access
   needs no row here.
3. ``index_value_quote`` — explicit lineage from a published ``index_value`` back to the
   ``fare_quote_clean`` rows that produced it. Without this, /v1/provenance's
   ``contributed_to`` could only be answered by inference, not a trace (principle 1).
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

ROLE_ENUM_VALUES = ("PUBLIC", "RESEARCHER", "OFFICIAL")


def upgrade() -> None:
    bind = op.get_bind()
    postgresql.ENUM(*ROLE_ENUM_VALUES, name="role_enum").create(bind, checkfirst=True)
    role_enum = postgresql.ENUM(*ROLE_ENUM_VALUES, name="role_enum", create_type=False)

    op.add_column("index_run", sa.Column("released_at", sa.DateTime(timezone=True), nullable=True))
    op.create_index("ix_index_run_released_at", "index_run", ["released_at"])

    op.create_table(
        "api_key",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("key_hash", sa.String(64), nullable=False),
        sa.Column("role", role_enum, nullable=False),
        sa.Column("label", sa.String(128), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id", name="pk_api_key"),
        sa.UniqueConstraint("key_hash", name="uq_api_key_key_hash"),
        sa.CheckConstraint("role <> 'PUBLIC'", name="ck_api_key_role_not_public"),
    )
    op.create_index("ix_api_key_key_hash", "api_key", ["key_hash"])

    op.create_table(
        "index_value_quote",
        sa.Column("index_run_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("series_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("period", sa.Date(), nullable=False),
        sa.Column("clean_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.PrimaryKeyConstraint(
            "index_run_id", "series_id", "period", "clean_id", name="pk_index_value_quote"
        ),
        sa.ForeignKeyConstraint(
            ["index_run_id", "series_id", "period"],
            ["index_value.index_run_id", "index_value.series_id", "index_value.period"],
            name="fk_index_value_quote_index_value",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["clean_id"],
            ["fare_quote_clean.id"],
            name="fk_index_value_quote_clean_id_fare_quote_clean",
            ondelete="RESTRICT",
        ),
    )
    op.create_index("ix_index_value_quote_clean_id", "index_value_quote", ["clean_id"])


def downgrade() -> None:
    op.drop_table("index_value_quote")
    op.drop_index("ix_api_key_key_hash", table_name="api_key")
    op.drop_table("api_key")
    op.drop_index("ix_index_run_released_at", table_name="index_run")
    op.drop_column("index_run", "released_at")
    postgresql.ENUM(name="role_enum").drop(op.get_bind(), checkfirst=True)
