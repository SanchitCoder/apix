"""The shipped basket must be valid, and the guards against bad weights must bite."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest
from pydantic import ValidationError

from apix_core.config import BasketConfig, load_basket
from apix_core.config.basket import AdvanceWindow, RouteEntry


def _route(code: str, share: Decimal | None = None) -> dict[str, object]:
    origin, dest = code.split("-")
    return {
        "code": code,
        "origin": origin,
        "dest": dest,
        "dgca_pax_share": share,
        "active_from": date(2026, 1, 1),
    }


def _basket(routes: list[dict[str, object]]) -> dict[str, object]:
    return {
        "basket_version": "test",
        "effective_from": date(2026, 1, 1),
        "advance_windows": [{"code": "AP00_03", "min_days": 0, "max_days": 3, "label": "walk-up"}],
        "routes": routes,
    }


class TestShippedBasket:
    def test_the_real_basket_file_validates(self, config_dir) -> None:
        basket = load_basket(config_dir)
        assert basket.basket_version == "2026.1"
        assert len(basket.routes) == 50

    def test_every_dgca_share_is_null_until_phase_2(self, config_dir) -> None:
        """CLAUDE.md principle 5: no invented DGCA figures.

        If this test ever fails, someone has written a passenger share into the basket.
        That is only legitimate once Phase 2 loads the real DGCA release for *every*
        route, at which point this test is replaced by one that checks the shares sum
        to 1.
        """
        basket = load_basket(config_dir)
        assert all(r.dgca_pax_share is None for r in basket.routes)
        assert basket.weights_are_populated is False

    def test_routes_are_directional_pairs(self, config_dir) -> None:
        codes = {r.code for r in load_basket(config_dir).routes}
        for code in codes:
            origin, dest = code.split("-")
            assert f"{dest}-{origin}" in codes, f"{code} has no reverse direction"


class TestBasketValidation:
    def test_partially_populated_weights_are_rejected(self) -> None:
        """A half-filled weight vector would silently bias the index."""
        with pytest.raises(ValidationError, match="some routes but not all"):
            BasketConfig.model_validate(
                _basket([_route("DEL-BOM", Decimal("0.1")), _route("BOM-DEL")])
            )

    def test_weights_summing_above_one_are_rejected(self) -> None:
        with pytest.raises(ValidationError, match="sum to more than 1"):
            BasketConfig.model_validate(
                _basket([_route("DEL-BOM", Decimal("0.7")), _route("BOM-DEL", Decimal("0.7"))])
            )

    def test_fully_populated_weights_are_accepted(self) -> None:
        basket = BasketConfig.model_validate(
            _basket([_route("DEL-BOM", Decimal("0.4")), _route("BOM-DEL", Decimal("0.4"))])
        )
        assert basket.weights_are_populated is True

    def test_duplicate_route_codes_are_rejected(self) -> None:
        with pytest.raises(ValidationError, match="duplicate route codes"):
            BasketConfig.model_validate(_basket([_route("DEL-BOM"), _route("DEL-BOM")]))

    def test_duplicate_window_codes_are_rejected(self) -> None:
        payload = _basket([_route("DEL-BOM")])
        payload["advance_windows"] = [payload["advance_windows"][0]] * 2  # type: ignore[index]
        with pytest.raises(ValidationError, match="duplicate advance window codes"):
            BasketConfig.model_validate(payload)

    def test_code_must_match_endpoints(self) -> None:
        with pytest.raises(ValidationError, match="does not match"):
            RouteEntry.model_validate(
                {
                    "code": "DEL-BOM",
                    "origin": "DEL",
                    "dest": "BLR",
                    "active_from": date(2026, 1, 1),
                }
            )

    def test_malformed_code_is_rejected(self) -> None:
        with pytest.raises(ValidationError, match="must look like"):
            RouteEntry.model_validate(
                {
                    "code": "DELBOM",
                    "origin": "DEL",
                    "dest": "BOM",
                    "active_from": date(2026, 1, 1),
                }
            )

    def test_self_loop_is_rejected(self) -> None:
        with pytest.raises(ValidationError, match="same airport"):
            RouteEntry.model_validate(
                {
                    "code": "DEL-DEL",
                    "origin": "DEL",
                    "dest": "DEL",
                    "active_from": date(2026, 1, 1),
                }
            )

    def test_inverted_active_window_is_rejected(self) -> None:
        with pytest.raises(ValidationError, match="active_to must be after"):
            RouteEntry.model_validate(
                {
                    "code": "DEL-BOM",
                    "origin": "DEL",
                    "dest": "BOM",
                    "active_from": date(2026, 6, 1),
                    "active_to": date(2026, 1, 1),
                }
            )

    def test_inverted_advance_window_is_rejected(self) -> None:
        with pytest.raises(ValidationError, match="max_days must be >= min_days"):
            AdvanceWindow.model_validate(
                {"code": "BAD", "min_days": 30, "max_days": 3, "label": "x"}
            )
