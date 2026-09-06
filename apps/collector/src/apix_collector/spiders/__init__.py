"""Concrete spiders, one module per source. See ``apix_collector.spiders.base.BaseSpider``."""

from __future__ import annotations

from apix_collector.spiders.akasa import AkasaSpider
from apix_collector.spiders.base import BaseSpider, CollectionOutcome
from apix_collector.spiders.cleartrip import CleartripSpider
from apix_collector.spiders.indigo import IndigoSpider

__all__ = ["AkasaSpider", "BaseSpider", "CleartripSpider", "CollectionOutcome", "IndigoSpider"]
