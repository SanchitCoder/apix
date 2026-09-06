"""The mapper contract: one module per source, mapping its response shape to ``RawQuote``.

A mapper is pure: bytes in, ``RawQuote`` list out (or :class:`SchemaDriftError`). It
never makes a request, never touches the database, and never repairs a shape it does
not recognise — that is ``apix_collector.drift``'s job, called by the mapper only to
report the drift, never to paper over it.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from apix_collector.quote import MapperContext, RawQuote


class Mapper(Protocol):
    """Normalises one source's raw response bytes into canonical quotes."""

    source_code: str

    def parse(self, payload: bytes, context: MapperContext) -> list[RawQuote]:
        """Parse ``payload``.

        Raises :class:`apix_collector.errors.SchemaDriftError` if the payload's shape
        does not match what this mapper expects. Never returns a partial or
        best-effort result for a shape it does not recognise — a wrong guess here
        would enter the evidence base for a published statistic.
        """
        ...


__all__ = ["Mapper"]
