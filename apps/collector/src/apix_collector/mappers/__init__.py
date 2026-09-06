"""One mapper module per source. See ``apix_collector.mapper.Mapper``."""

from __future__ import annotations

from apix_collector.mappers.akasa import AkasaMapper
from apix_collector.mappers.cleartrip import CleartripMapper
from apix_collector.mappers.indigo import IndigoMapper

__all__ = ["AkasaMapper", "CleartripMapper", "IndigoMapper"]
