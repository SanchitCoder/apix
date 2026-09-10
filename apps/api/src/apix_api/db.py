"""Async SQLAlchemy wiring for the API.

One engine per process, created in ``lifespan`` and stored on ``app.state``; one
``AsyncSession`` per request, handed out by :func:`get_session` and closed when the
request finishes. Every endpoint in this service is async and queries through this
session directly — no threadpool bridging, so ``echo=True`` in tests shows exactly what
each endpoint issues.

Provenance is the one deliberate exception: ``apix_core.provenance.resolve()`` is
Phase-1 code that predates this service and uses a sync ``Session``. It is bridged via
``anyio.to_thread`` in ``routers/provenance.py`` rather than duplicated here.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import TYPE_CHECKING, Annotated

# Not type-checking-only despite what it looks like: get_session is wired in as
# Depends(get_session), and FastAPI resolves that signature via get_type_hints() at
# request time — a TYPE_CHECKING-only Request here would raise NameError on the first
# request, not at import time.
from fastapi import Depends, Request
from sqlalchemy import create_engine as create_sync_engine
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import Session, sessionmaker

if TYPE_CHECKING:
    from sqlalchemy import Engine

    from apix_core.settings import Settings


def create_engine(settings: Settings) -> AsyncEngine:
    return create_async_engine(
        settings.database_url,
        echo=settings.db_echo,
        pool_size=settings.db_pool_size,
        max_overflow=settings.db_pool_max_overflow,
        pool_pre_ping=True,
    )


def create_session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False)


def create_sync_provenance_engine(settings: Settings) -> Engine:
    """A sync engine for the one deliberate exception (see module docstring)."""
    return create_sync_engine(settings.database_sync_url, pool_pre_ping=True)


def create_sync_session_factory(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(engine)


async def get_session(request: Request) -> AsyncIterator[AsyncSession]:
    """FastAPI dependency: one session per request, from the engine on ``app.state``."""
    session_factory: async_sessionmaker[AsyncSession] = request.app.state.db_session_factory
    async with session_factory() as session:
        yield session


SessionDep = Annotated[AsyncSession, Depends(get_session)]
