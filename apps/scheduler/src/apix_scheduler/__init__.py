"""APIx orchestration.

Prefect 3 flows: collection, cleaning, snapshot, index run, nowcast. Phase 2 implements
them.

Every flow stamps its ``run_id`` onto the structured log context, and an index flow
records the ``data_snapshot`` and ``method_config`` hashes it ran under, so any published
figure can be reproduced from its stamp alone.
"""

from __future__ import annotations

__version__ = "0.1.0"

__all__ = ["__version__"]
