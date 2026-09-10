"""Role resolution and the microdata/draft-data gate.

Rate limiting and API-key resolution both happen once, in
:func:`apix_api.middleware.enforce_access_control`, before routing — the same
single-choke-point shape ``PolicyEngine`` uses on the collection side. This module is
what an endpoint reaches for afterwards: the resolved :class:`Role` on ``request.state``,
and a dependency to require an authenticated (researcher or official) caller.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING, Annotated

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy import select

from apix_core.models import ApiKey
from apix_core.models import Role as Role
from apix_core.provenance.hashing import sha256_hex

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

API_KEY_HEADER = "X-API-Key"

__all__ = [
    "API_KEY_HEADER",
    "InvalidApiKeyError",
    "Role",
    "RoleDep",
    "get_role",
    "require_authenticated",
    "resolve_role",
]


class InvalidApiKeyError(Exception):
    """Raised by :func:`resolve_role` for a header that does not name a live key.

    Not an ``HTTPException``: :func:`resolve_role` runs from inside
    ``apix_api.middleware.enforce_access_control``, ahead of routing, where FastAPI's
    exception handlers are not guaranteed to see it. The middleware catches this and
    builds the problem+json response itself.
    """


async def resolve_role(session: AsyncSession, api_key: str | None) -> tuple[Role, str]:
    """Resolve an ``X-API-Key`` header value to a role and a rate-limit identity.

    No header means public access — no lookup, no row required. A header that does not
    match a live (unrevoked) key raises :class:`InvalidApiKeyError` rather than silently
    downgrading to public: a caller presenting a bad key almost certainly intended to
    authenticate.
    """
    if api_key is None:
        return Role.PUBLIC, "anonymous"

    key_hash = sha256_hex(api_key.encode("utf-8"))
    row = (
        await session.execute(
            select(ApiKey).where(ApiKey.key_hash == key_hash, ApiKey.revoked_at.is_(None))
        )
    ).scalar_one_or_none()
    if row is None:
        raise InvalidApiKeyError

    row.last_used_at = datetime.now(tz=UTC)
    await session.commit()
    return row.role, str(row.id)


def get_role(request: Request) -> Role:
    """The role ``enforce_access_control`` resolved for this request."""
    return getattr(request.state, "role", Role.PUBLIC)


RoleDep = Annotated[Role, Depends(get_role)]


def require_authenticated(request: Request) -> None:
    """Gate microdata and draft/pre-release endpoints to researcher/official callers.

    Public and researcher/official are not distinguished further here: the contract
    asks only that microdata and unpublished figures require *a* key, not that the two
    authenticated roles see different things.
    """
    role = get_role(request)
    if role is Role.PUBLIC:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=(
                "this endpoint serves microdata or pre-release figures; "
                f"present a researcher or official {API_KEY_HEADER}"
            ),
        )
