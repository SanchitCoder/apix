"""FastAPI routers. One module per area of the contract."""

from __future__ import annotations

from apix_api.routers import analytics, export, health, index, metadata, provenance, routes, sdmx

__all__ = [
    "analytics",
    "export",
    "health",
    "index",
    "metadata",
    "provenance",
    "routes",
    "sdmx",
]
