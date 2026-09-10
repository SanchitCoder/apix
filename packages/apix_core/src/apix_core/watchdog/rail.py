"""AC-2 rail-fare substitution comparison.

No real rail-fare source exists in this repository yet — see docs/data-sources.md.
:class:`NotImplementedRailFareSource` is what runs until one is wired up; it fails
loudly and specifically rather than returning an empty or fabricated fare.
:func:`compare_to_rail` itself never fabricates a comparison: an empty ``rail_fares``
input produces an empty result, not an exception — the same "a comparison that cannot
be made is a recorded gap, not an invented number" pattern
:func:`apix_core.index.aggregate.national_index` uses for routes with no configured
weight.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

import pandas as pd

if TYPE_CHECKING:
    from datetime import date

REQUIRED_AIRFARE_COLUMNS = ("route_code", "period", "fare")
REQUIRED_RAIL_COLUMNS = ("route_code", "period", "rail_fare")

_OUTPUT_COLUMNS = ("route_code", "period", "airfare", "rail_fare", "ratio", "spread")


class RailFareSource(Protocol):
    """Anything that can produce AC-2 rail fares for a corridor and period."""

    def fares_for_corridor(self, corridor_code: str, period: date) -> pd.DataFrame:
        """AC-2 fares for ``corridor_code`` covering ``period``.

        Returns a DataFrame with ``period`` and ``rail_fare`` columns.
        """
        ...


class NotImplementedRailFareSource:
    """The rail-fare source until a real one is wired up.

    Raises immediately and specifically, so a caller that reaches for real rail data
    fails loudly rather than silently getting nothing back — CLAUDE.md principle 5:
    raise ``NotImplementedError`` rather than invent data.
    """

    def fares_for_corridor(self, corridor_code: str, period: date) -> pd.DataFrame:
        raise NotImplementedError(
            f"no rail fare source is configured for corridor {corridor_code!r} — "
            "implement RailFareSource against a real feed, or supply a "
            "db/seeds/rail/*.csv extract and a loader; see docs/data-sources.md"
        )


def compare_to_rail(airfare: pd.DataFrame, rail_fares: pd.DataFrame) -> pd.DataFrame:
    """Airfare vs. AC-2 rail fare, per ``(route_code, period)``.

    ``ratio = airfare / rail_fare``, ``spread = airfare - rail_fare``. An empty
    ``rail_fares`` — the honest state of this repository until a real source is
    integrated — returns an empty result with the right columns, not an error.
    """
    missing_air = [c for c in REQUIRED_AIRFARE_COLUMNS if c not in airfare.columns]
    if missing_air:
        raise ValueError(f"compare_to_rail: airfare missing required columns: {missing_air}")
    if airfare.empty:
        raise ValueError("compare_to_rail: airfare must have at least one row")
    if (airfare["fare"] <= 0).any():
        raise ValueError("compare_to_rail: fare must be strictly positive")
    missing_rail = [c for c in REQUIRED_RAIL_COLUMNS if c not in rail_fares.columns]
    if missing_rail:
        raise ValueError(f"compare_to_rail: rail_fares missing required columns: {missing_rail}")

    if rail_fares.empty:
        return pd.DataFrame(columns=list(_OUTPUT_COLUMNS))
    if (rail_fares["rail_fare"] <= 0).any():
        raise ValueError("compare_to_rail: rail_fare must be strictly positive")

    merged = airfare.merge(rail_fares, on=["route_code", "period"], how="inner")
    merged = merged.rename(columns={"fare": "airfare"})
    merged["ratio"] = merged["airfare"] / merged["rail_fare"]
    merged["spread"] = merged["airfare"] - merged["rail_fare"]
    return merged[list(_OUTPUT_COLUMNS)].reset_index(drop=True)


__all__ = [
    "REQUIRED_AIRFARE_COLUMNS",
    "REQUIRED_RAIL_COLUMNS",
    "NotImplementedRailFareSource",
    "RailFareSource",
    "compare_to_rail",
]
