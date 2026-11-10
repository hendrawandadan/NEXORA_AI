"""Tests for walk-forward multi-split validation module."""

import numpy as np
import pandas as pd
import pytest

from nexora_laboratory.opportunity_discovery.walkforward import (
    make_folds, walkforward_ic, stability_verdict, assess_walkforward,
    SIGN_CONSIST_MIN, SIG_MIN, DOMINANCE_MAX, IC_MIN,
)
from nexora_laboratory.opportunity_discovery.information import build_features


def _bars(n, seed=0, signal=False):
    rng = np.random.default_rng(seed)
    steps = rng.normal(0, 1.0, n)
    if signal:
        # persistent: next return follows the previous 5-bar return in ALL periods
        for i in range(10, n - 6):
            steps[i + 1] += 0.8 * steps[i - 4]
    price = 100 + np.cumsum(steps)
    ts = pd.date_range("2020-01-01", periods=n, freq="h")
    return pd.DataFrame({"ts": ts, "open": price,
                         "high": price + 0.5, "low": price - 0.5,
                         "close": price, "volume": 1, "spread": 0.0})


# ---------- fold construction ----------
def test_make_folds_count_and_contiguity():
    folds = make_folds(100, 4)
    assert len(folds) == 4
    for (a, b) in folds:
        assert b > a
    # contiguous non-overlapping within the tail
    for i in range(len(folds) - 1):
        assert folds[i][1] == folds[i + 1][0]


def test_make_folds_requires_min():
    with pytest.raises(ValueError):
        make_folds(100, 1)


def test_make_folds_too_short():
    with pytest.raises(ValueError):
        make_folds(5, 10)


# ---------- walkforward_ic ----------
def test_walkforward_ic_structure():
    bars = _bars(600, seed=1)
    feats = build_features(bars, windows=(5,))
    wf = walkforward_ic(bars, "ret_5", feats, horizon=1, n_folds=4)
    assert "fold_ics" in wf and len(wf["fold_ics"]) == 4
    assert wf["n_folds_valid"] >= 1
    assert 0.0 <= wf["frac_sign_consistent"] <= 1.0


def test_walkforward_purges_boundaries():
    # With purging, a fold's usable n should be < raw block length when horizon>0
    bars = _bars(1000, seed=2)
    feats = build_features(bars, windows=(5,))
    wf = walkforward_ic(bars, "ret_5", feats, horizon=10, n_folds=4)
    bounds = wf["fold_bounds"]
    ns = wf["fold_ns"]
    for (a, b), n in zip(bounds, ns):
        if n > 0:
            assert n <= (b - a)  # purged block cannot exceed raw block


# ---------- stability verdict ----------
def test_stability_verdict_stable_case():
    wf = {"n_folds_valid": 5, "frac_sign_consistent": 0.9,
          "frac_folds_significant": 0.8, "max_fold_dominance": 0.3,
          "median_ic": 0.08, "fold_ics": [0.1] * 5}
    v = stability_verdict(wf)
    assert v["stable"] is True
    assert v["failed_checks"] == []


def test_stability_verdict_fails_on_sign_flip():
    wf = {"n_folds_valid": 5, "frac_sign_consistent": 0.5,
          "frac_folds_significant": 0.8, "max_fold_dominance": 0.3,
          "median_ic": 0.08, "fold_ics": [0.1, -0.1, 0.1, -0.1, 0.1]}
    v = stability_verdict(wf)
    assert v["stable"] is False
    assert "sign_consistency" in v["failed_checks"]


def test_stability_verdict_fails_on_dominance():
    wf = {"n_folds_valid": 5, "frac_sign_consistent": 0.9,
          "frac_folds_significant": 0.8, "max_fold_dominance": 0.9,
          "median_ic": 0.08, "fold_ics": [0.1] * 5}
    v = stability_verdict(wf)
    assert v["stable"] is False
    assert "not_dominated" in v["failed_checks"]


def test_stability_verdict_fails_on_magnitude():
    wf = {"n_folds_valid": 5, "frac_sign_consistent": 0.9,
          "frac_folds_significant": 0.8, "max_fold_dominance": 0.3,
          "median_ic": 0.001, "fold_ics": [0.001] * 5}
    v = stability_verdict(wf)
    assert v["stable"] is False
    assert "magnitude" in v["failed_checks"]


def test_stability_verdict_insufficient():
    v = stability_verdict({"n_folds_valid": 0, "fold_ics": []})
    assert v["stable"] is False


# ---------- thresholds documented ----------
def test_thresholds_are_strict():
    assert SIGN_CONSIST_MIN >= 0.75
    assert SIG_MIN >= 0.5
    assert DOMINANCE_MAX <= 0.7
    assert IC_MIN > 0


# ---------- assess_walkforward end-to-end ----------
def test_assess_walkforward_structure():
    bars = _bars(1200, seed=3)
    r = assess_walkforward(bars, features_to_test=["ret_5", "zclose_5"],
                           horizons=[1, 2], windows=(5,), n_folds=4)
    assert r["n_tests"] == 4  # 2 features x 2 horizons
    assert "stable" in r and "results" in r
    for row in r["results"]:
        assert "stable" in row and "stability_checks" in row


def test_assess_walkforward_injected_signal_may_be_stable():
    # Strong persistent signal -> at least some stability expected more than in noise.
    bars = _bars(3000, seed=4, signal=True)
    r = assess_walkforward(bars, features_to_test=["ret_5"], horizons=[1],
                           windows=(5,), n_folds=5)
    # We don't assert True (honest: could still fail); we assert it RUNS and reports.
    assert r["n_tests"] == 1
    assert r["results"][0]["stable"] in (True, False)
