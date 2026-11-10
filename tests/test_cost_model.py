"""Tests for STAGE 3 — Transaction Cost Analysis (cost_model)."""

import pytest

from nexora_laboratory.opportunity_discovery.cost_model import (
    CostScenario, instrument_scenarios, session_costs, cost_vs_move,
    analyze_instrument_costs, MEASURED_SPREAD_PIPS, SCENARIO_QUANTILE,
)


# ---------- scenario construction ----------
def test_scenario_round_trip_is_sum():
    sc = CostScenario(name="baseline", spread_pips=1.55, slippage_pips=0.2, commission_pips=0.0)
    assert sc.round_trip_pips == pytest.approx(1.75)


def test_instrument_scenarios_use_measured_quantiles():
    scs = {s.name: s for s in instrument_scenarios("GBPUSDm")}
    q = MEASURED_SPREAD_PIPS["GBPUSDm"]["quantiles"]
    assert scs["optimistic"].spread_pips == pytest.approx(q["p50"])
    assert scs["baseline"].spread_pips == pytest.approx(q["p90"])
    assert scs["stress"].spread_pips == pytest.approx(q["p99"])


def test_instrument_scenarios_ordered_optimistic_lt_stress():
    scs = {s.name: s for s in instrument_scenarios("USDJPYm")}
    assert (scs["optimistic"].round_trip_pips
            < scs["baseline"].round_trip_pips
            < scs["stress"].round_trip_pips)


def test_commission_default_not_available():
    scs = instrument_scenarios("XAUUSDm")
    assert all(s.commission_pips == 0.0 for s in scs)
    assert all(s.commission_status == "NOT_AVAILABLE" for s in scs)


def test_commission_band_raises_cost():
    base = {s.name: s for s in instrument_scenarios("GBPUSDm")}
    withc = {s.name: s for s in instrument_scenarios("GBPUSDm", commission_pips=1.0)}
    assert withc["baseline"].round_trip_pips == pytest.approx(base["baseline"].round_trip_pips + 1.0)
    assert withc["baseline"].commission_status == "ASSUMED"


def test_metal_slippage_higher_than_fx():
    fx = {s.name: s for s in instrument_scenarios("USDJPYm")}
    metal = {s.name: s for s in instrument_scenarios("XAUUSDm")}
    assert metal["baseline"].slippage_pips > fx["baseline"].slippage_pips


# ---------- session costs ----------
def test_session_costs_present_and_ordered():
    sc = session_costs("GBPUSDm")
    assert set(sc) == {"ASIA", "LONDON", "NY", "LATE"}
    # LATE spread (1.55) higher than ASIA (1.15) -> RT higher
    assert sc["LATE"]["round_trip_pips"] > sc["ASIA"]["round_trip_pips"]


def test_session_costs_no_session_for_bar_estimate():
    # EURUSD estimate has no per-session data
    sc = session_costs("EURUSD")
    assert sc == {}


# ---------- cost vs move ----------
def test_cost_vs_move_basic():
    r = cost_vs_move(3.2, 32.0)  # cost 10% of move
    assert r["cost_fraction_of_move"] == pytest.approx(0.1)
    assert r["move_to_cost_ratio"] == pytest.approx(10.0)
    assert r["crossover"] is False


def test_cost_vs_move_crossover():
    r = cost_vs_move(5.0, 4.0)  # cost > move
    assert r["crossover"] is True
    assert r["cost_fraction_of_move"] == pytest.approx(1.25)


def test_cost_vs_move_zero_or_none_move():
    assert cost_vs_move(3.0, None)["cost_fraction_of_move"] is None
    assert cost_vs_move(3.0, 0.0)["cost_fraction_of_move"] is None


# ---------- analyze_instrument_costs ----------
def test_analyze_full():
    r = analyze_instrument_costs(
        "XAUUSDm",
        horizons_with_median_move={"H4:h12": 154.67, "H4:h4": 78.24})
    assert r["spread_source"] == "tick"
    assert r["commission_status"] == "NOT_AVAILABLE"
    assert "H4:h12" in r["cost_drag_by_horizon"]
    b = r["cost_drag_by_horizon"]["H4:h12"]["baseline"]
    # cost drag should be tiny for gold at long horizon
    assert b["cost_fraction_of_move"] < 0.10
    assert b["crossover"] is False


def test_analyze_drag_higher_for_estimate_eurusd():
    r = analyze_instrument_costs("EURUSD", horizons_with_median_move={"M30:h24": 18.4})
    b = r["cost_drag_by_horizon"]["M30:h24"]["baseline"]
    # EURUSD estimated cost drag at M30 h24 should be materially higher than gold
    assert b["cost_fraction_of_move"] > 0.15


def test_analyze_marks_most_expensive_session():
    r = analyze_instrument_costs("GBPUSDm")
    assert r["most_expensive_session"] == "LATE"


def test_analyze_without_horizons_has_empty_drag():
    r = analyze_instrument_costs("USDJPYm")
    assert r["cost_drag_by_horizon"] == {}


def test_spread_source_labels():
    assert MEASURED_SPREAD_PIPS["GBPUSDm"]["source"] == "tick"
    assert "estimate" in MEASURED_SPREAD_PIPS["EURUSD"]["source"]
