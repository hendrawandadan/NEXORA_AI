"""Tests for FASE 2A triple-barrier labeling: anti-leakage + correctness."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from nexora_laboratory.triple_barrier import (
    BarrierConfig,
    atr_from_bars,
    label_events,
    label_summary,
)


def _synthetic_bars(n=200, seed=0, start="2021-01-04 00:00"):
    rng = np.random.default_rng(seed)
    ts = pd.date_range(start, periods=n, freq="30min")
    close = 1.10 + np.cumsum(rng.normal(0, 0.0005, n))
    open_ = close + rng.normal(0, 0.0001, n)
    high = np.maximum(open_, close) + np.abs(rng.normal(0, 0.0002, n))
    low = np.minimum(open_, close) - np.abs(rng.normal(0, 0.0002, n))
    return pd.DataFrame({"ts": ts, "open": open_, "high": high, "low": low, "close": close})


def test_label_time_is_after_signal_time_no_leak():
    bars = _synthetic_bars(300, seed=1)
    atr = atr_from_bars(bars, 14)
    cfg = BarrierConfig(k_up=1.5, k_dn=1.0, vertical=16, atr_span=14)
    labels = label_events(bars, atr, cfg, entry_at_next_open=True)
    assert not labels.empty
    # Label resolution time must be strictly after the signal time (no future label == signal)
    assert (labels["exit_time"] > labels["signal_time"]).all()
    # Entry must be the next bar's open and after signal
    assert (labels["entry_time"] > labels["signal_time"]).all()


def test_entry_is_next_open():
    bars = _synthetic_bars(120, seed=2)
    atr = atr_from_bars(bars, 14)
    cfg = BarrierConfig(vertical=8)
    labels = label_events(bars, atr, cfg, entry_at_next_open=True)
    # For the first label (t=0), entry_price must equal bars.open[1]
    first = labels.iloc[0]
    assert np.isclose(first["entry_price"], bars["open"].iloc[1])
    assert first["signal_time"] == bars["ts"].iloc[0]
    assert first["entry_time"] == bars["ts"].iloc[1]


def test_barriers_are_atr_scaled_and_ordered():
    bars = _synthetic_bars(150, seed=3)
    atr = atr_from_bars(bars, 14)
    cfg = BarrierConfig(k_up=1.5, k_dn=1.0, vertical=16)
    labels = label_events(bars, atr, cfg)
    # upper > entry > lower and gaps match ATR multiples
    assert (labels["upper"] > labels["entry_price"]).all()
    assert (labels["lower"] < labels["entry_price"]).all()
    up_gap = labels["upper"] - labels["entry_price"]
    dn_gap = labels["entry_price"] - labels["lower"]
    assert np.allclose(up_gap, cfg.k_up * labels["atr"])
    assert np.allclose(dn_gap, cfg.k_dn * labels["atr"])


def test_atr_uses_only_past_bars():
    """Changing FUTURE bars must not change ATR at an earlier index."""
    bars = _synthetic_bars(100, seed=4)
    atr1 = atr_from_bars(bars, 14)
    bars2 = bars.copy()
    bars2.loc[80:, ["open", "high", "low", "close"]] *= 1.5  # alter the future
    atr2 = atr_from_bars(bars2, 14)
    # ATR up to index 79 must be identical (uses <= t)
    assert np.allclose(atr1.iloc[:80].to_numpy(), atr2.iloc[:80].to_numpy(), equal_nan=True)


def test_first_touch_order_respected_on_single_bar_spike():
    """A bar that only pierces upper first must resolve +1 (not vertical)."""
    n = 40
    ts = pd.date_range("2021-01-04 00:00", periods=n, freq="30min")
    px = np.full(n, 1.1000)
    open_ = px.copy(); close = px.copy(); high = px + 0.0001; low = px - 0.0001
    # Force a big upward spike at bar 5 only
    high[5] = 1.1100
    bars = pd.DataFrame({"ts": ts, "open": open_, "high": high, "low": low, "close": close})
    # constant ATR
    atr = pd.Series(np.full(n, 0.001), index=bars.index)
    cfg = BarrierConfig(k_up=1.5, k_dn=1.0, vertical=16)
    labels = label_events(bars, atr, cfg, entry_at_next_open=True)
    # Find the event whose window includes bar 5 (entry index <=5)
    hit = labels[labels["raw_outcome"] == 1]
    assert len(hit) >= 1


def test_vertical_when_no_barrier_hit():
    n = 40
    ts = pd.date_range("2021-01-04 00:00", periods=n, freq="30min")
    px = np.full(n, 1.1000)
    bars = pd.DataFrame({"ts": ts, "open": px, "high": px + 0.00001,
                         "low": px - 0.00001, "close": px})
    atr = pd.Series(np.full(n, 0.01), index=bars.index)  # wide barriers, never hit
    cfg = BarrierConfig(k_up=5.0, k_dn=5.0, vertical=10)
    labels = label_events(bars, atr, cfg)
    assert (labels["raw_outcome"] == 0).all()
    assert (~labels["ambiguous"]).all()


def test_summary_shape():
    bars = _synthetic_bars(120, seed=5)
    atr = atr_from_bars(bars, 14)
    labels = label_events(bars, atr, BarrierConfig())
    s = label_summary(labels)
    assert s["n"] == len(labels)
    assert s["upper(+1)"] + s["lower(-1)"] + s["vertical(0)"] == s["n"] - s["ambiguous"]
