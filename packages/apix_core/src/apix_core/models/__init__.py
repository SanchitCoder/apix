"""SQLAlchemy models for APIx.

Importing this package registers every table on ``Base.metadata``. Alembic imports it
for autogenerate, so a model that is not re-exported here is invisible to migrations.
"""

from __future__ import annotations

from apix_core.models.auth import ApiKey
from apix_core.models.base import Base, IndexNumber, Money
from apix_core.models.clean import FareQuoteClean
from apix_core.models.collection import CollectionRun, PolicyDecision, Source, SourcePolicy
from apix_core.models.enums import (
    CarrierType,
    CollectionMethod,
    FareClass,
    Frequency,
    LegalBasis,
    PolicyDecisionOutcome,
    Role,
    RunStatus,
    SourceType,
    TosVerdict,
)
from apix_core.models.index import (
    DataSnapshot,
    IndexRun,
    IndexValue,
    IndexValueQuote,
    MethodConfig,
    RevisionLog,
    Series,
)
from apix_core.models.nowcast import NowcastValue
from apix_core.models.quotes import FareQuote
from apix_core.models.reference import Airport, Carrier, Route
from apix_core.models.reference_series import AtfPrice, CpiAirfareIndex, DgcaFareReference, RailFare
from apix_core.models.watchdog import DispersionStat, PersonalisationProbeObservation

__all__ = [
    "Airport",
    "ApiKey",
    "AtfPrice",
    "Base",
    "Carrier",
    "CarrierType",
    "CollectionMethod",
    "CollectionRun",
    "CpiAirfareIndex",
    "DataSnapshot",
    "DgcaFareReference",
    "DispersionStat",
    "FareClass",
    "FareQuote",
    "FareQuoteClean",
    "Frequency",
    "IndexNumber",
    "IndexRun",
    "IndexValue",
    "IndexValueQuote",
    "LegalBasis",
    "MethodConfig",
    "Money",
    "NowcastValue",
    "PersonalisationProbeObservation",
    "PolicyDecision",
    "PolicyDecisionOutcome",
    "RailFare",
    "RevisionLog",
    "Role",
    "Route",
    "RunStatus",
    "Series",
    "Source",
    "SourcePolicy",
    "SourceType",
    "TosVerdict",
]
