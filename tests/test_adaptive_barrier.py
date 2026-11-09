"""FASE 2A — Adaptive barrier (vol-targeted, approach #1): anti-leakage proofs.

These implement the design-doc §4 "wajib" proofs:
  - the supervised target genuinely depends on the FUTURE (so it is a real label),
  - the PREDICTION at bar t does NOT depend on bars > t (no look-ahead),
  - barrier distance formula + label schema match the frozen baseline.

No training is dispatched as a side effect of importing/testing beyond tiny
in-memory LightGBM fits on synthetic data.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from nexora_laboratory.adaptive_barrier import (
    VolTargetConfig,
    adaptive_atr_proxy,
    forward_realized_range,
    label_with_adaptive_barrier,
    VolatilityBarrierModel,
)
from nexora_laboratory.triple_barrier import (
    BarrierConfig,
    ExecutionConfig,
    label_events,
)


def _synth_bars(n=400, seed=0):
    rng = np.random.default_rng(seed)
    ts = pd.date_range("2021-01-04", periods=n, freq="30min")
    close = 1.1 + np.cumsum(rng.normal(0, 0.0005, n))
    high = close + rng.uniform(0.0001, 0.0008, n)
    low = close - rng.uniform(0.0001, 0.0008, n)
    open_ = np.r_[close[0], close[:-1]]
    return pd.DataFrame({"ts": ts, "open": open_, "high": high, "low": low, "close": close})


def _features(bars: pd.DataFrame) -> pd.DataFrame:
    """Minimal trailing feature set (only info <= t)."""
    c = bars["close"]
    return pd.DataFrame({
        "ret_1": c.diff(1),
        "ret_4": c.diff(4),
        "range": (bars["high"] - bars["low"]) / c,
        "vol8": c.diff().rolling(8).std(),
    }, index=bars.index)


# ---- 1. target is a genuine forward label -------------------------------
def test_target_depends_on_future_only():
    bars = _synth_bars()
    H = 16
    y = forward_realized_range(bars, H)

    # altering bars AFTER t changes the target AT t (it is forward-looking)
    bars_future = bars.copy()
    t = 100
    bars_future.loc[t + 1: t + H, "high"] += 0.01
    y_future = forward_realized_range(bars_future, H)
    assert not np.isclose(y.iloc[t], y_future.iloc[t])

    # altering bars BEFORE t (open/high/low/close, i.e. no row-blowup into the
    # future window) must NOT change the target at t, which uses close[t] and
    # bars t+1..t+H only.
    bars_past = bars.copy()
    bars_past.loc[: t - 1, ["open", "high", "low", "close"]] *= 1.01
    y_past = forward_realized_range(bars_past, H)
    assert np.isclose(y.iloc[t], y_past.iloc[t])


def test_target_tail_is_nan():
    bars = _synth_bars(n=60)
    H = 16
    y = forward_realized_range(bars, H)
    assert y.iloc[-H:].isna().all()
    assert y.iloc[:-H].notna().all()


# ---- 2. prediction at bar t must not see bars > t -----------------------
def test_predict_does_not_see_future():
    bars = _synth_bars()
    X = _features(bars)
    y = forward_realized_range(bars, 16)
    ok = X.notna().all(axis=1) & y.notna()
    X, y = X[ok], y[ok]

    # split deterministically by row position (no shuffle)
    cut = int(len(X) * 0.6)
    model = VolatilityBarrierModel(VolTargetConfig())
    model.fit(X.iloc[:cut], y.iloc[:cut])

    probe = X.iloc[cut: cut + 50]
    pred_before = model.predict_vol(probe)

    # perturb FUTURE rows only (>= cut+50); probe rows are < those
    bars2 = bars.copy()
    fut_idx = bars2.index[cut + 50:]
    bars2.loc[fut_idx, ["high", "low", "close", "open"]] *= 1.05
    X2 = _features(bars2)
    pred_after = model.predict_vol(X2.loc[probe.index])
    assert np.allclose(pred_before, pred_after)


# ---- 3. barrier distance formula ---------------------------------------
def test_barrier_distance_formula():
    bars = _synth_bars()
    X = _features(bars)
    y = forward_realized_range(bars, 16)
    ok = X.notna().all(axis=1) & y.notna()
    X, y = X[ok], y[ok]
    model = VolatilityBarrierModel(VolTargetConfig(k_vol=1.25)).fit(X, y)
    # fraction units (no ref price)
    dist_frac = model.barrier_distance(X.iloc[:10])
    assert np.allclose(dist_frac, 1.25 * model.predict_vol(X.iloc[:10]))
    # price units (× reference price, known at signal time)
    ref = np.full(10, 1.10)
    dist_price = model.barrier_distance(X.iloc[:10], ref_price=ref)
    assert np.allclose(dist_price, 1.25 * model.predict_vol(X.iloc[:10]) * 1.10)


def test_adaptive_proxy_round_trip():
    # atr_proxy * k reproduces the intended barrier distance
    pv = np.array([0.002, 0.003, 0.001])
    proxy = adaptive_atr_proxy(pv, 1.25).to_numpy()
    assert np.allclose(proxy * 1.25, pv)


# ---- 4. label schema matches the frozen baseline ------------------------
def test_label_uses_same_core():
    bars = _synth_bars(n=200)
    pv = np.full(len(bars), 0.002)  # constant predicted vol (price-fraction)
    cfg = VolTargetConfig(k_vol=1.25, vertical=4)
    ec = ExecutionConfig(half_spread_price=0.00005)
    lab = label_with_adaptive_barrier(bars, pv, cfg, ec, side=1)

    bcfg = BarrierConfig(k_up=1.25, k_dn=1.25, vertical=4)
    ref = label_events(bars, pd.Series(pv / 1.25, index=bars.index), bcfg, ec, side=1)

    assert list(lab.columns) == list(ref.columns)
    assert set(lab["event_status"]).issubset({"UPPER_HIT", "LOWER_HIT", "VERTICAL_EXIT", "AMBIGUOUS"})
    assert lab["event_status"].tolist() == ref["event_status"].tolist()
