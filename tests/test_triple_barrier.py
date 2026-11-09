"""FASE 2A v2 tests: side-aware executable triple-barrier (review item 9).

All fixtures use known synthetic prices so outcomes are mathematically verifiable.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from nexora_laboratory.triple_barrier import (
    AMBIGUOUS,
    LOWER_HIT,
    UPPER_HIT,
    VERTICAL_EXIT,
    BarrierConfig,
    ExecutionConfig,
    atr_from_bars,
    label_events,
)


def _flat_bars(n, price=1.1000, start="2021-01-04 00:00"):
    ts = pd.date_range(start, periods=n, freq="30min")
    return pd.DataFrame({
        "ts": ts, "open": np.full(n, price), "high": np.full(n, price),
        "low": np.full(n, price), "close": np.full(n, price),
    })


def _const_atr(bars, val=0.0010):
    return pd.Series(np.full(len(bars), val), index=bars.index)


def _make_with_spike(up_idx=None, up_px=None, dn_idx=None, dn_px=None, n=40, price=1.1):
    b = _flat_bars(n, price)
    if up_idx is not None:
        b.loc[up_idx, "high"] = up_px
    if dn_idx is not None:
        b.loc[dn_idx, "low"] = dn_px
    return b


CFG = BarrierConfig(k_up=1.5, k_dn=1.0, vertical=5)


# ---- 1. BUY upper hit ------------------------------------------------------
def test_buy_upper_hit():
    bars = _make_with_spike(up_idx=3, up_px=1.1 + 10 * 0.001)  # far above upper
    atr = _const_atr(bars)
    # need full window: n=40, vertical=5 ok
    labels = label_events(bars, atr, CFG, ExecutionConfig(half_spread_price=0.0), side=1)
    first = labels.iloc[0]
    assert first["event_status"] == UPPER_HIT
    assert first["barrier_outcome"] == 1
    assert labels["gross_return"].max() > 0


# ---- 2. BUY lower hit ------------------------------------------------------
def test_buy_lower_hit():
    bars = _make_with_spike(dn_idx=3, dn_px=1.1 - 10 * 0.001)
    atr = _const_atr(bars)
    labels = label_events(bars, atr, CFG, ExecutionConfig(half_spread_price=0.0), side=1)
    first = labels.iloc[0]
    assert first["event_status"] == LOWER_HIT
    assert first["barrier_outcome"] == -1


# ---- 3. SELL upper hit (upper is LOSS for sell) ---------------------------
def test_sell_upper_hit_is_loss():
    bars = _make_with_spike(up_idx=3, up_px=1.1 + 10 * 0.001)
    atr = _const_atr(bars)
    labels = label_events(bars, atr, CFG, ExecutionConfig(half_spread_price=0.0), side=-1)
    first = labels.iloc[0]
    assert first["event_status"] == UPPER_HIT   # physically upper touched
    assert first["barrier_outcome"] == -1        # but it's a LOSS for a short
    assert first["gross_return"] < 0


# ---- 4. SELL lower hit (lower is PROFIT for sell) ------------------------
def test_sell_lower_hit_is_profit():
    bars = _make_with_spike(dn_idx=3, dn_px=1.1 - 10 * 0.001)
    atr = _const_atr(bars)
    labels = label_events(bars, atr, CFG, ExecutionConfig(half_spread_price=0.0), side=-1)
    first = labels.iloc[0]
    assert first["event_status"] == LOWER_HIT
    assert first["barrier_outcome"] == 1
    assert first["gross_return"] > 0


# ---- 5/6. BUY vertical profit / loss -------------------------------------
def test_buy_vertical_profit_and_loss():
    # wide barriers never hit -> vertical; drift close at the vertical exit bar
    n = 20
    b = _flat_bars(n, 1.1)
    atr = _const_atr(b, val=0.01)  # wide barriers
    cfg = BarrierConfig(k_up=10, k_dn=10, vertical=5)
    # first event: signal t=0, entry=1, vertical exit index = 1+5 = 6
    vert_idx = 1 + cfg.vertical
    # profit: exit bar closed higher
    b2 = b.copy(); b2.loc[vert_idx, "close"] = 1.1005; b2.loc[vert_idx, "high"] = 1.1005
    lab = label_events(b2, atr, cfg, ExecutionConfig(), side=1)
    first = lab.iloc[0]
    assert first["event_status"] == VERTICAL_EXIT
    assert first["gross_return"] > 0
    # loss
    b3 = b.copy(); b3.loc[vert_idx, "close"] = 1.0995; b3.loc[vert_idx, "low"] = 1.0995
    lab2 = label_events(b3, atr, cfg, ExecutionConfig(), side=1)
    assert lab2.iloc[0]["event_status"] == VERTICAL_EXIT
    assert lab2.iloc[0]["gross_return"] < 0


# ---- 7/8. SELL vertical profit / loss -----------------------------------
def test_sell_vertical_profit_and_loss():
    n = 20
    b = _flat_bars(n, 1.1)
    atr = _const_atr(b, val=0.01)
    cfg = BarrierConfig(k_up=10, k_dn=10, vertical=5)
    vert_idx = 1 + cfg.vertical
    b2 = b.copy(); b2.loc[vert_idx, "close"] = 1.0995; b2.loc[vert_idx, "low"] = 1.0995
    lab = label_events(b2, atr, cfg, ExecutionConfig(), side=-1)
    assert lab.iloc[0]["event_status"] == VERTICAL_EXIT
    assert lab.iloc[0]["gross_return"] > 0   # short profits when price falls
    b3 = b.copy(); b3.loc[vert_idx, "close"] = 1.1005; b3.loc[vert_idx, "high"] = 1.1005
    lab2 = label_events(b3, atr, cfg, ExecutionConfig(), side=-1)
    assert lab2.iloc[0]["gross_return"] < 0


# ---- bid/ask spread accounting -------------------------------------------
def test_executable_spread_accounting():
    """With a half-spread, a BUY entry is at ask (higher) and exit at bid (lower):
    gross return identical price path should be strictly worse than zero spread."""
    n = 20
    b = _flat_bars(n, 1.1)
    atr = _const_atr(b, val=0.01)
    cfg = BarrierConfig(k_up=10, k_dn=10, vertical=5)
    # vertical exit at same mid; round-trip spread cost should make BUY negative
    lab0 = label_events(b, atr, cfg, ExecutionConfig(half_spread_price=0.0), side=1)
    lab1 = label_events(b, atr, cfg, ExecutionConfig(half_spread_price=0.0001), side=1)
    assert np.isclose(lab0.iloc[0]["gross_return"], 0.0, atol=1e-9)
    assert lab1.iloc[0]["gross_return"] < 0  # buy ask, exit bid -> loss ~2*hs/price


def test_executable_entry_exit_sides():
    n = 20
    b = _flat_bars(n, 1.1)
    atr = _const_atr(b, val=0.01)
    cfg = BarrierConfig(k_up=10, k_dn=10, vertical=5)
    hs = 0.0001
    lab_buy = label_events(b, atr, cfg, ExecutionConfig(half_spread_price=hs), side=1)
    # BUY entry = mid+hs
    assert np.isclose(lab_buy.iloc[0]["entry_price"], 1.1 + hs)
    lab_sell = label_events(b, atr, cfg, ExecutionConfig(half_spread_price=hs), side=-1)
    # SELL entry = mid-hs
    assert np.isclose(lab_sell.iloc[0]["entry_price"], 1.1 - hs)


# ---- ambiguous intrabar event -------------------------------------------
def test_ambiguous_intrabar_event():
    """A bar whose range spans BOTH barriers with no M1 -> AMBIGUOUS (not vertical)."""
    n = 20
    b = _flat_bars(n, 1.1)
    atr = _const_atr(b, val=0.001)
    cfg = BarrierConfig(k_up=1.5, k_dn=1.0, vertical=5)
    # bar 1 (entry) spans both: high above upper, low below lower
    b.loc[1, "high"] = 1.1 + 0.005
    b.loc[1, "low"] = 1.1 - 0.005
    lab = label_events(b, atr, cfg, ExecutionConfig(), side=1)  # no m1
    first = lab.iloc[0]
    assert first["event_status"] == AMBIGUOUS
    assert first["ambiguous"] is True or bool(first["ambiguous"]) is True


# ---- no-leakage / event window -------------------------------------------
def test_event_window_after_signal():
    n = 40
    b = _flat_bars(n, 1.1)
    atr = _const_atr(b)
    lab = label_events(b, atr, CFG, ExecutionConfig(), side=1)
    assert (lab["entry_time"] > lab["signal_time"]).all()
    assert (lab["event_end_time"] >= lab["event_start_time"]).all()
    assert (lab["exit_time"] > lab["signal_time"]).all()


def test_atr_no_future_leak():
    n = 80
    b = _flat_bars(n, 1.1)
    atr1 = atr_from_bars(b, 14)
    b2 = b.copy(); b2.loc[50:, ["open", "high", "low", "close"]] *= 1.5
    atr2 = atr_from_bars(b2, 14)
    assert np.allclose(atr1.iloc[:50].to_numpy(), atr2.iloc[:50].to_numpy(), equal_nan=True)


def test_invalid_side_raises():
    b = _flat_bars(20, 1.1)
    atr = _const_atr(b)
    with pytest.raises(ValueError):
        label_events(b, atr, CFG, ExecutionConfig(), side=0)
