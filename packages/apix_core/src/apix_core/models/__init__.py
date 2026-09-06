"""SQLAlchemy models for APIx.

Importing this package registers every table on ``Base.metadata``. Alembic imports it
for autogenerate, so a model that is not re-exported here is invisible to migrations.
"""

from __future__ import annotations

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
    RunStatus,
    SourceType,
    TosVerdict,
)
from apix_core.models.index import (
    DataSnapshot,
    IndexRun,
    IndexValue,
    MethodConfig,
    RevisionLog,
    Series,
)
from apix_core.models.nowcast import NowcastValue
from apix_core.models.quotes import FareQuote
from apix_core.models.reference import Airport, Carrier, Route

__all__ = [
    "Airport",
    "Base",
    "Carrier",
    "CarrierType",
    "CollectionMethod",
    "CollectionRun",
    "DataSnapshot",
    "FareClass",
    "FareQuote",
    "FareQuoteClean",
    "Frequency",
    "IndexNumber",
    "IndexRun",
    "IndexValue",
    "LegalBasis",
    "MethodConfig",
    "Money",
    "NowcastValue",
    "PolicyDecision",
    "PolicyDecisionOutcome",
    "RevisionLog",
    "Route",
    "RunStatus",
    "Series",
    "Source",
    "SourcePolicy",
    "SourceType",
    "TosVerdict",
]
