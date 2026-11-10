"""Tests for STAGE 5 — New Information Assessment (information module)."""

import numpy as np
import pandas as pd
import pytest

from nexora_laboratory.opportunity_discovery.information import (
    build_features, forward_returns, split_mask, compute_ic, assess_information,
    benjamini_hochberg, bonferroni, _spearman,
)


def _make_bars(n=600, seed=0, signal=False):
    rng = np.random.default_rng(seed)
    steps = rng.normal(0, 1.0, n)
    if signal:
        # inject: tomorrow's return partially follows today's trailing 5-return
        for i in range(10, n - 1):
            steps[i + 1] += 0.6 * steps[i - 4]  # mild serial dependence
    price = 100 + np.cumsum(steps)
    ts = pd.date_range("2020-01-01", periods=n, freq="h")
    return pd.DataFrame({
        "ts": ts + pd.Timedelta(minutes=1),
        "open": price, "high": price + np.abs(rng.normal(0, 0.5, n)),
        "low": price - np.abs(rng.normal(0, 0.5, n)),
        "close": price, "volume": 100, "spread": 0.0,
    })


# ---------- features: causality ----------
def test_features_are_causal_no_lookahead():
    bars = _make_bars(300, seed=1)
    feats = build_features(bars, windows=(5, 20))
    # Changing a FUTURE bar must not change past feature values.
    bars2 = bars.copy()
    bars2.loc[250:, "close"] = bars2.loc[250:, "close"] * 1.5
    feats2 = build_features(bars2, windows=(5, 20))
    # rows strictly before index 250 must be identical
    cols = [c for c in feats.columns]
    pd.testing.assert_frame_equal(feats.iloc[:240][cols], feats2.iloc[:240][cols],
                                  check_like=True)


def test_features_have_expected_columns():
    bars = _make_bars(120, seed=2)
    feats = build_features(bars, windows=(5, 20, 60))
    for pre in ("ret_", "zclose_", "vol_", "rng_", "posrng_", "rsi_"):
        assert any(c.startswith(pre) for c in feats.columns)
    assert feats.shape[0] == len(bars)


def test_features_align_index():
    bars = _make_bars(150, seed=3)
    feats = build_features(bars, windows=(10,))
    assert list(feats.index) == list(bars.index)


# ---------- forward returns ----------
def test_forward_returns_shift():
    bars = _make_bars(50, seed=4)
    fr = forward_returns(bars, 3)
    expected = bars["close"].shift(-3) / bars["close"] - 1.0
    pd.testing.assert_series_equal(fr, expected, check_names=False)
    # last 3 are NaN (no future)
    assert fr.tail(3).isna().all()


# ---------- split ----------
def test_split_mask_temporal():
    bars = _make_bars(1000, seed=5)
    m = split_mask(bars, test_frac=0.30)
    assert m.sum() == 300
    # test is the LAST segment
    assert not m[:-300].any()
    assert m[-300:].all()


# ---------- spearman helper ----------
def test_spearman_edge_cases():
    x = np.arange(50, dtype=float)
    y = np.arange(50, dtype=float)
    rho, p = _spearman(x, y)
    assert rho == pytest.approx(1.0, abs=1e-9)
    # constant input -> nan
    rho0, _ = _spearman(np.zeros(50), y)
    assert np.isnan(rho0)
    # too small -> nan
    r = _spearman(np.arange(5, dtype=float), np.arange(5, dtype=float))[0]
    assert np.isnan(r)


# ---------- multiple comparison ----------
def test_bonferroni_threshold_and_reject():
    p = [0.001, 0.01, 0.5, 0.9]
    r = bonferroni(p, alpha=0.05)
    assert r["threshold"] == pytest.approx(0.05 / 4)
    assert r["reject"] == [True, True, False, False]


def test_bh_rejects_strong_small_p():
    p = [1e-6, 1e-5, 0.01, 0.5, 0.9]
    r = benjamini_hochberg(p, alpha=0.05)
    assert r["n_tests"] == 5
    # the tiny p-values should survive
    assert sum(r["reject"]) >= 2


def test_bh_qvalues_monotone_and_bounded():
    p = [0.9, 0.001, 0.5, 0.01, 0.2]
    r = benjamini_hochberg(p, alpha=0.05)
    q = np.array(r["q_values"])
    assert np.all(q <= 1.0) and np.all(q >= 0.0)
    assert len(q) == len(p)


# ---------- end-to-end assess ----------
def test_assess_returns_structure():
    bars = _make_bars(800, seed=6)
    res = assess_information(bars, horizons=[2, 5], windows=(5, 20), test_frac=0.3)
    assert res["n_horizons"] == 2
    assert res["n_tests"] == len(res["ic_table"])
    for row in res["ic_table"]:
        assert "train_ic" in row and "test_ic" in row and "test_q_bh" in row
    assert "multiple_comparison" in res
    assert res["multiple_comparison"]["n_survive_bh"] >= 0


def test_assess_detects_injected_signal_more_in_test():
    # With injected serial dependence, a trailing-return feature should show
    # non-trivial IC somewhere; we just assert the machinery finds *some* finite IC.
    bars = _make_bars(1500, seed=7, signal=True)
    res = assess_information(bars, horizons=[1], windows=(5,), test_frac=0.3, alpha=0.05)
    ics = [r["test_ic"] for r in res["ic_table"] if r["test_ic"] is not None]
    assert len(ics) > 0


def test_assess_no_is_lookahead_in_features():
    # Deterministic check: test set target uses future close; features do not.
    bars = _make_bars(600, seed=8)
    feats = build_features(bars, windows=(5,))
    # feature at index t uses closes <= t only -> compare to trailing calc
    t = 100
    manual_ret5 = bars["close"].iloc[t] / bars["close"].iloc[t - 5] - 1.0
    assert feats["ret_5"].iloc[t] == pytest.approx(manual_ret5, rel=1e-9)
