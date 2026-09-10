"""``api_key`` — bearer credentials for the researcher and official access tiers.

Public read access needs no row here. A key is only ever stored hashed (SHA-256 of the
high-entropy token; these are bearer secrets, not user passwords, so a slow KDF buys
nothing and would make every authenticated request pay for it) — the plaintext token is
shown to whoever mints it exactly once and never persisted.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, Index, String
from sqlalchemy.orm import Mapped, mapped_column

from apix_core.models.base import Base, created_at_col, pg_enum, uuid_pk
from apix_core.models.enums import Role


class ApiKey(Base):
    """One issued API key. Revoked, never deleted — an audit trail of who could read what."""

    __tablename__ = "api_key"

    id: Mapped[uuid.UUID] = uuid_pk()
    key_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    role: Mapped[Role] = mapped_column(pg_enum(Role, "role_enum"), nullable=False)
    label: Mapped[str] = mapped_column(String(128), nullable=False)
    created_at: Mapped[datetime] = created_at_col()
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        # Bare name, no "ck_" prefix: Base.metadata's naming_convention
        # ("ck_%(table_name)s_%(constraint_name)s") adds the table-scoped prefix itself
        # — matching migration 0003's literal DDL name exactly, rather than doubling it.
        CheckConstraint("role <> 'PUBLIC'", name="role_not_public"),
        Index("ix_api_key_key_hash", "key_hash"),
    )
