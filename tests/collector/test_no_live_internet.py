"""The collector's non-negotiables, asserted rather than described."""

from __future__ import annotations

import inspect

import apix_collector


def test_collector_package_imports() -> None:
    assert apix_collector.__version__


def test_the_only_documented_egress_path_is_the_policy_engine() -> None:
    """Guardrail one: no spider makes its own HTTP request.

    Phase 2 will add a real test that every spider's downloader is the PolicyEngine.
    This asserts the constraint is at least stated where a spider author will read it.
    """
    doc = inspect.getdoc(apix_collector) or ""
    assert "PolicyEngine" in doc
    assert "fixtures" in doc
