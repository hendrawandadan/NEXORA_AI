"""Tests for FASE 2A cost engine (units, no double counting)."""

from __future__ import annotations

import pytest

from nexora_laboratory.cost_engine import (
    PIP_SIZE,
    all_scenarios,
    apply_cost,
    cost_return_fraction,
    get_scenario,
)


def test_scenario_totals_match_approved():
    # Approved: optimistic 1.0+0.2=1.2, baseline 1.5+0.2=1.7, stress 2.0+0.2=2.2
    assert get_scenario("optimistic").total_pips == pytest.approx(1.2, abs=1e-9)
    assert get_scenario("baseline").total_pips == pytest.approx(1.7, abs=1e-9)
    assert get_scenario("stress").total_pips == pytest.approx(2.2, abs=1e-9)


def test_cost_fraction_units():
    # 1.7 pip * 0.0001 = 0.00017 fraction at reference price 1.0
    assert cost_return_fraction("baseline") == pytest.approx(1.7 * PIP_SIZE, abs=1e-12)
    assert cost_return_fraction("baseline") == pytest.approx(0.00017, abs=1e-12)


def test_reference_price_scaling():
    # At price 1.10 the same pip cost is a slightly smaller fraction
    c = cost_return_fraction("baseline", reference_price=1.10)
    assert c == pytest.approx(0.00017 / 1.10, abs=1e-12)


def test_no_double_counting_single_subtraction():
    # apply_cost subtracts exactly one scenario total once
    gross = 0.0005
    net = apply_cost(gross, "baseline")
    assert net == pytest.approx(gross - cost_return_fraction("baseline"), abs=1e-12)


def test_unknown_scenario_raises():
    with pytest.raises(KeyError):
        get_scenario("cheap")


def test_all_scenarios_present_and_assumption_tagged():
    s = all_scenarios()
    assert set(s) == {"optimistic", "baseline", "stress"}
    for sc in s.values():
        d = sc.as_dict()
        assert "assumption" in d and "double" in d["assumption"].lower()
