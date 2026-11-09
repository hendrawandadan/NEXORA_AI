"""FASE 2A v2 tests: cost engine (component split, no double counting)."""

from __future__ import annotations

import pytest

from nexora_laboratory.cost_engine import (
    PIP_SIZE,
    STATUS_NOT_AVAILABLE,
    cost_fraction_from_pips,
    components_for_scenario,
    total_cost_fraction,
)


def test_scenario_totals():
    assert components_for_scenario("optimistic").total_pips() == pytest.approx(1.2)
    assert components_for_scenario("baseline").total_pips() == pytest.approx(1.7)
    assert components_for_scenario("stress").total_pips() == pytest.approx(2.2)


def test_commission_status_not_available():
    c = components_for_scenario("baseline")
    assert c.commission_status == STATUS_NOT_AVAILABLE


def test_cost_uses_reference_price():
    # 1.7 pip at entry price 1.10 -> 1.7*0.0001/1.10
    c = components_for_scenario("baseline")
    frac = total_cost_fraction(c, reference_price=1.10, spread_already_in_prices=False)
    assert frac == pytest.approx(1.7 * PIP_SIZE / 1.10)


def test_no_double_count_spread_in_executable_mode():
    """Executable mode already contains spread in prices -> exclude spread here."""
    c = components_for_scenario("baseline")  # spread 1.5, slip 0.2
    flat = total_cost_fraction(c, 1.10, spread_already_in_prices=False)
    execu = total_cost_fraction(c, 1.10, spread_already_in_prices=True)
    # executable must subtract ONLY slippage/commission/swap (0.2 pip), much less
    assert execu == pytest.approx(0.2 * PIP_SIZE / 1.10)
    assert flat - execu == pytest.approx(1.5 * PIP_SIZE / 1.10)  # exactly the spread, once


def test_pips_to_fraction():
    assert cost_fraction_from_pips(1.0, 1.0) == pytest.approx(0.0001)


def test_reference_price_positive_required():
    c = components_for_scenario("baseline")
    with pytest.raises(ValueError):
        total_cost_fraction(c, reference_price=0.0, spread_already_in_prices=False)


def test_unknown_scenario():
    with pytest.raises(KeyError):
        components_for_scenario("cheap")
