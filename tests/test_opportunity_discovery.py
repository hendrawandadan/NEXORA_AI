"""Tests for Economic Opportunity Discovery (STAGE 1 horizon discovery).

Covers: granularity break detection, forward-move stats invariants, break-even
math, scenario arithmetic, and pip-factor per instrument. Pure, no data files
beyond a small synthetic frame — must pass offline.
"""

import numpy as np
import pandas as pd
import pytest

from nexora_laboratory.opportunity_discovery.granularity import granularity_break
from nexora_laboratory.opportunity_discovery.moves import (
    forward_move_stats, _entry_exit_arrays,
)
from nexora_laboratory.opportunity_discovery.horizon import (
    Scenario, pip_size_for, horizon_economics,
)
from nexora_laboratory.break_even import (
    break_even_accuracy_symmetric, break_even_accuracy_barrier,
)


def _bars(ts_list, o, h, l, c, spread=None):
    d = pd.DataFrame({
        "ts": pd.to_datetime(ts_list), "open": o, "high": h, "low": l, "close": c,
    })
    if spread is not None:
        d["spread"] = spread
    return d


# ---------- pip factor ----------
def test_pip_size_per_instrument():
    assert pip_size_for("EURUSD") == pytest.approx(0.0001)
    assert pip_size_for("GBPUSDm") == pytest.approx(0.0001)
    assert pip_size_for("USDJPYm") == pytest.approx(0.01)
    assert pip_size_for("XAUUSD") == pytest.approx(0.10)


# ---------- break-even math ----------
def test_break_even_symmetric_monotone():
    # larger move -> smaller required accuracy
    a = break_even_accuracy_symmetric(0.0010, 0.0003)
    b = break_even_accuracy_symmetric(0.0050, 0.0003)
    assert a > b > 0.5


def test_break_even_barrier_formula():
    # q* = (k_dn + c)/(k_up + k_dn), c = C/S
    q = break_even_accuracy_barrier(cost_price=0.00032, scale_price=0.0010)
    c = 0.00032 / 0.0010
    assert q == pytest.approx((1.0 + c) / (1.5 + 1.0))


# ---------- scenario arithmetic ----------
def test_scenario_round_trip():
    s = Scenario("baseline", spread_pips=3.0, slippage_pips=0.2)
    assert s.round_trip_pips == pytest.approx(3.2)


# ---------- granularity break ----------
def test_granularity_detects_daily_prefix_then_intraday():
    # 3 daily bars (1440 min apart) then 5 intraday 30-min bars
    ts = ["2020-01-02 00:00", "2020-01-03 00:00", "2020-01-04 00:00",
          "2020-01-05 09:00", "2020-01-05 09:30", "2020-01-05 10:00",
          "2020-01-05 10:30", "2020-01-05 11:00"]
    n = len(ts)
    b = _bars(ts, [1.0]*n, [1.01]*n, [0.99]*n, [1.0]*n)
    brk = granularity_break(b, expected_minutes=30)
    assert brk["has_daily_prefix"] is True
    assert brk["prefix_rows"] >= 1
    # the intraday segment should contain the 30-min-spaced tail
    seg_start = pd.Timestamp(brk["intraday_first"])
    assert seg_start >= pd.Timestamp("2020-01-05 09:00")


def test_granularity_no_break_when_all_intraday():
    ts = pd.date_range("2021-01-01 00:00", periods=10, freq="30min").astype(str).tolist()
    n = len(ts)
    b = _bars(ts, [1.0]*n, [1.01]*n, [0.99]*n, [1.0]*n)
    brk = granularity_break(b, expected_minutes=30)
    assert brk["has_daily_prefix"] is False
    assert brk["prefix_rows"] == 0


# ---------- forward move stats invariants ----------
def test_forward_move_stats_basic():
    # linear up ramp of 1 pip per bar; h=1 absolute move should be ~10 pips (0.0010)
    n = 50
    o = np.arange(n) * 0.0001 + 1.1000
    b = _bars(pd.date_range("2021-01-01", periods=n, freq="30min").astype(str),
              o, o + 0.00005, o - 0.00005, o)
    st = forward_move_stats(b, h=1, pip_size=0.0001)
    # each 1-bar forward move = 0.0001 = 1 pip
    assert st.median_pips == pytest.approx(1.0, abs=1e-6)
    assert st.n == n - 1 - 0  # entry_shift default 0 -> n-h valid


def test_forward_move_stats_flat_series():
    n = 30
    o = np.full(n, 1.1000)
    b = _bars(pd.date_range("2021-01-01", periods=n, freq="30min").astype(str),
              o, o, o, o)
    st = forward_move_stats(b, h=4, pip_size=0.0001)
    assert st.median_pips == pytest.approx(0.0)
    assert st.frac_up == pytest.approx(0.0)  # no positive moves


def test_entry_shift_aligns():
    n = 20
    o = np.arange(n) * 0.0001 + 1.1000
    b = _bars(pd.date_range("2021-01-01", periods=n, freq="30min").astype(str),
              o, o, o, o)
    e0, x0, _, _, v0 = _entry_exit_arrays(b, h=2, entry_shift=0)
    e1, x1, _, _, v1 = _entry_exit_arrays(b, h=2, entry_shift=1)
    # entry_shift=1 drops the first bar and uses open[t+1]
    assert len(e1) == len(e0) - 1
    assert e1[0] == pytest.approx(o[1])


# ---------- horizon economics integration ----------
def test_horizon_economics_monotone_ratio():
    n = 400
    rng = np.random.default_rng(0)
    steps = rng.normal(0, 0.0002, n)
    o = 1.1000 + np.cumsum(steps)
    o = np.abs(o) + 1.0
    b = _bars(pd.date_range("2021-01-01", periods=n, freq="30min").astype(str),
              o, o + 0.0001, o - 0.0001, o)
    scen = [Scenario("baseline", 3.0, 0.2)]
    res = horizon_economics(b, [2, 8, 32], scen, pip_size=0.0001)
    ratios = [r["move_to_cost_ratio"] for r in res["economics"]]
    # longer horizon -> larger move/cost (monotone non-decreasing)
    assert ratios[0] <= ratios[1] <= ratios[2]
    # required accuracy strictly decreases toward 0.5
    reqs = [r["required_acc_symmetric"] for r in res["economics"]]
    assert reqs[0] > reqs[1] > reqs[2]
