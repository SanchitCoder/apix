"""Test and validation infrastructure that ships with the library.

The synthetic fare generator lives here rather than under ``tests/`` because it is a
product surface: ``make seed-synthetic`` uses it to stand up a fully populated local
stack, and the index engine is validated against its known ground truth. Everything it
emits is labelled SYNTHETIC end to end.
"""

from __future__ import annotations

from apix_core.testing.synthetic import (
    SYNTHETIC_UUID_NAMESPACE,
    SyntheticDataset,
    generate,
    lead_time_multipliers,
)

__all__ = [
    "SYNTHETIC_UUID_NAMESPACE",
    "SyntheticDataset",
    "generate",
    "lead_time_multipliers",
]
