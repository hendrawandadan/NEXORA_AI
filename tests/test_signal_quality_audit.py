"""FASE 2A — Audit A (break-even) + Audit B (feature power) unit tests.

Pure, synthetic fixtures. Proves the math is correct and the no-edge behaviour is
correctly flagged, so the audit's verdicts are trustworthy.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from nexora_laboratory.break_even import (
    CostModel,
    break_even_accuracy_barrier,
    break_even_accuracy_symmetric,
    feasibility_table,
    realized_move_sizes,
    any_feasible,
)
from nexora_laboratory.feature_power import feature_power_oos


# ---------------------------------------------------------------------------
# Audit A — break-even math
# ---------------------------------------------------------------------------
def test_symmetric_break_even_zero_cost_is_half():
    assert break_even_accuracy_symmetric(0.001, 0.0) == pytest.approx(0.5)


def test_symmetric_break_even_increases_with_cost():
    a = break_even_accuracy_symmetric(0.001, 0.0001)
    b = break_even_accuracy_symmetric(0.001, 0.0003)
    assert b > a > 0.5


def test_symmetric_break_even_matches_formula():
    s, c = 0.001, 0.0002
    assert break_even_accuracy_symmetric(s, c) == pytest.approx(0.5 + c / (2 * s))


def test_barrier_break_even_zero_cost():
    # c=0 -> q* = k_dn/(k_up+k_dn) = 1.0/2.5 = 0.4
    assert break_even_accuracy_barrier(0.0, 0.01, 1.5, 1.0) == pytest.approx(0.4)


def test_barrier_break_even_rises_with_cost():
    a = break_even_accuracy_barrier(0.0001, 0.01, 1.5, 1.0)
    b = break_even_accuracy_barrier(0.0005, 0.01, 1.5, 1.0)
    assert b > a


def test_feasibility_flags_no_edge():
    # Small moves (~4 pip) vs big cost (3 pip) -> required acc near 0.9 -> 0.51 infeasible.
    moves = pd.DataFrame({"horizon_bars": [2], "n": [1000],
                          "median_pips": [4.5], "mean_pips": [7.0], "p75_pips": [9.0]})
    cost = CostModel(spread_pips=3.0, slippage_pips=0.2)
    ft = feasibility_table(moves, cost, observed_accuracy={2: 0.51})
    assert ft.loc[0, "required_acc_symmetric"] > 0.8
    assert bool(ft.loc[0, "feasible_symmetric"]) is False
    summ = any_feasible(ft)
    assert summ["any_feasible_symmetric"] is False


def test_feasibility_flags_edge_when_accuracy_high():
    moves = pd.DataFrame({"horizon_bars": [2], "n": [1000],
                          "median_pips": [4.5], "mean_pips": [7.0], "p75_pips": [9.0]})
    cost = CostModel(spread_pips=0.2, slippage_pips=0.0)  # tiny cost
    ft = feasibility_table(moves, cost, observed_accuracy={2: 0.75})
    assert bool(ft.loc[0, "feasible_symmetric"]) is True


def test_realized_move_sizes_increasing():
    rng = np.random.default_rng(0)
    n = 5000
    op = 1.1 + np.cumsum(rng.normal(0, 0.0005, n))
    bars = pd.DataFrame({"open": op})
    m = realized_move_sizes(bars, [1, 4, 8])
    assert m.loc[0, "median_pips"] < m.loc[1, "median_pips"] < m.loc[2, "median_pips"]


# ---------------------------------------------------------------------------
# Audit B — feature power
# ---------------------------------------------------------------------------
def test_strong_feature_detected():
    rng = np.random.default_rng(1)
    n = 4000
    x = rng.normal(size=n)
    fwd = 0.3 * x + rng.normal(0, 1.0, n)  # strong linear relationship
    X = pd.DataFrame({"x": x, "noise": rng.normal(size=n)})
    res = feature_power_oos(X, fwd, horizon_bars=2, iters=200, min_ic_to_keep=0.02)
    assert res["n_usable"] >= 1
    assert "x" in res["usable_features"]
    # noise should not be flagged
    assert "noise" not in res["usable_features"]


def test_all_noise_flags_none_usable():
    rng = np.random.default_rng(2)
    n = 4000
    X = pd.DataFrame({f"f{i}": rng.normal(size=n) for i in range(5)})
    fwd = rng.normal(size=n)
    res = feature_power_oos(X, fwd, horizon_bars=2, iters=200, min_ic_to_keep=0.02)
    assert res["n_usable"] == 0
    assert res["verdict"] == "no_feature_clears_oos_ic_bar"


def test_feature_power_alignment_guard():
    X = pd.DataFrame({"a": np.arange(10.0)})
    with pytest.raises(ValueError):
        feature_power_oos(X, np.arange(5.0))
