"""Normalisation, outlier detection, decomposition and imputation.

Turns raw ``fare_quote`` rows into the analysis-ready ``fare_quote_clean`` shape, in
five independently testable stages (see each submodule's docstring):

1. :mod:`apix_core.clean.dedup` — match the same physical flight across sources.
2. :mod:`apix_core.clean.decompose` — split total_fare into base/taxes/UDF/fee.
3. :mod:`apix_core.clean.outliers` — flag (never drop) implausible prices.
4. :mod:`apix_core.clean.missing` — distinguish not-collected, sold-out and malformed,
   and impute genuine sell-outs by cell mean.
5. :mod:`apix_core.clean.quality` — build the hedonic quality vector.

:func:`apix_core.clean.pipeline.clean_quotes` wires all five together.
:mod:`apix_core.clean.gates` runs the data-quality gates on the result.

Every function in this package is pure: DataFrames and plain mappings in, DataFrames
out. No database access, no I/O, no logging side-effects — see CLAUDE.md.
"""

from __future__ import annotations

from apix_core.clean.decompose import FareSplitSource, decompose_fares
from apix_core.clean.dedup import assign_flight_key
from apix_core.clean.gates import GateReport, GateResult, QualityGateError, run_quality_gates
from apix_core.clean.missing import (
    CELL_IDENTITY,
    ImputationResult,
    MissingReason,
    classify_missing_cells,
    compute_coverage,
    impute_sold_out,
    quarantine_malformed,
    with_carrier_type,
)
from apix_core.clean.outliers import detect_outliers
from apix_core.clean.pipeline import CLEAN_COLUMNS, CleanResult, clean_quotes
from apix_core.clean.quality import build_quality_vector

__all__ = [
    "CELL_IDENTITY",
    "CLEAN_COLUMNS",
    "CleanResult",
    "FareSplitSource",
    "GateReport",
    "GateResult",
    "ImputationResult",
    "MissingReason",
    "QualityGateError",
    "assign_flight_key",
    "build_quality_vector",
    "classify_missing_cells",
    "clean_quotes",
    "compute_coverage",
    "decompose_fares",
    "detect_outliers",
    "impute_sold_out",
    "quarantine_malformed",
    "run_quality_gates",
    "with_carrier_type",
]
