"""FASE 2A — ATR vs Adaptive experiment: protocol-integrity tests.

These prove the RUNNER obeys the pre-registered protocol without running the real
experiment:
  * walk-forward folds match pipeline.walk_forward_scores geometry exactly,
  * purge >= label effective horizon (no label overlap across splits),
  * the adaptive vol model is fit on TRAIN rows only (no test-outcome leak),
  * the verdict is the literal AND of the §6 criteria (both directions),
  * the regime helper uses only trailing info.

No production data is touched; all fixtures are synthetic/in-memory.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from nexora_laboratory.adaptive_experiment import (
    ExperimentConfig,
    _evaluate_go_no_go,
    walk_forward_folds,
)
from nexora_laboratory.regime import CALM, HIGH, MID, trailing_regime


# ---------------------------------------------------------------------------
# 1. Walk-forward geometry == pipeline.walk_forward_scores
# ---------------------------------------------------------------------------
def test_walk_forward_geometry_matches_pipeline_rule():
    n, folds, purge = 10000, 3, 24
    got = walk_forward_folds(n, folds, purge)
    initial = max(int(n * 0.50), 1000)
    chunk = (n - initial) // folds
    expected = []
    for k in range(folds):
        train_end = initial + k * chunk
        test_start = min(train_end + purge, n)
        test_end = n if k == folds - 1 else min(test_start + chunk, n)
        expected.append((np.arange(0, train_end), np.arange(test_start, test_end)))
    assert len(got) == len(expected)
    for (gt, ge), (et, ee) in zip(got, expected):
        assert np.array_equal(gt, et)
        assert np.array_equal(ge, ee)


def test_purge_never_smaller_than_horizon():
    # purge is applied in the runner via purge_bars(horizon, T3, embargo).
    from nexora_learning.pipeline import purge_bars
    for h in (1, 2, 4, 8, 12, 24):
        assert purge_bars(h, "T3", 24) >= h + 1


def test_folds_chronological_and_purged():
    folds = walk_forward_folds(8000, 3, 24)
    last_test_start = -1
    for tr, te in folds:
        if len(te):
            assert te[0] > last_test_start
            last_test_start = te[0]
        # train ends before test starts with at least the purge gap
        assert tr[-1] < te[0]
        assert te[0] - tr[-1] >= 24


# ---------------------------------------------------------------------------
# 2. Adaptive model fit uses TRAIN rows only (no outcome leak)
# ---------------------------------------------------------------------------
def test_adaptive_fit_is_train_only():
    from nexora_laboratory.adaptive_experiment import _fit_predict_adaptive_vol
    from nexora_laboratory.adaptive_barrier import VolTargetConfig

    rng = np.random.default_rng(0)
    n = 2000
    X = pd.DataFrame(rng.normal(size=(n, 3)), columns=list("abc"))
    y = pd.Series(np.abs(rng.normal(0.003, 0.001, n)))
    train = np.arange(0, 1400)
    test = np.arange(1500, 2000)

    pred1 = _fit_predict_adaptive_vol(X, y, train, test, VolTargetConfig())

    # Corrupt ONLY the test-row outcomes; predictions on test must be unchanged
    # (the model was fit on train rows only and predicts from features).
    y2 = y.copy()
    y2.iloc[test] = 999.0
    pred2 = _fit_predict_adaptive_vol(X, y2, train, test, VolTargetConfig())
    assert np.allclose(pred1, pred2, equal_nan=True)


# ---------------------------------------------------------------------------
# 3. Verdict is the literal AND of §6 (GO only if all pass)
# ---------------------------------------------------------------------------
def _fold(adaptive_net, atr_net):
    return {"scenarios": {"baseline": {
        "adaptive": {"n": 100, "mean_net": adaptive_net},
        "atr": {"n": 100, "mean_net": atr_net}}},
        "n_test_rows": 500}


def _summary(ci_low, stress_a, stress_b, regime_wins):
    reg = {}
    for i, rn in enumerate((CALM, MID, HIGH)):
        if i < regime_wins:
            reg[rn] = {"adaptive_mean_net": 0.001, "atr_mean_net": 0.0}
        else:
            reg[rn] = {"adaptive_mean_net": -0.001, "atr_mean_net": 0.0}
    return {
        "baseline": {"diff_mean": 0.001, "ci_low": ci_low, "ci_high": 0.002,
                     "per_regime": reg},
        "stress": {"adaptive": {"mean_net": stress_a}, "atr": {"mean_net": stress_b}},
    }


def test_verdict_go_when_all_criteria_pass():
    folds = [_fold(0.001, 0.0)] * 3          # >0 in all 3 folds
    summ = _summary(ci_low=0.0005, stress_a=0.001, stress_b=0.0, regime_wins=2)
    res = _evaluate_go_no_go(folds, summ, ExperimentConfig())
    assert res["verdict"] == "GO"
    assert all(v["pass"] for v in res["criteria"].values())


def test_verdict_no_go_when_ci_includes_zero():
    folds = [_fold(0.001, 0.0)] * 3
    summ = _summary(ci_low=-0.001, stress_a=0.001, stress_b=0.0, regime_wins=2)
    res = _evaluate_go_no_go(folds, summ, ExperimentConfig())
    assert res["verdict"] == "NO-GO"
    assert res["criteria"]["c2_ci_excludes_zero_baseline"]["pass"] is False


def test_verdict_no_go_when_fewer_than_3_folds():
    folds = [_fold(0.001, 0.0), _fold(-0.001, 0.0), _fold(0.001, 0.0)]  # only 2 positive
    summ = _summary(ci_low=0.0005, stress_a=0.001, stress_b=0.0, regime_wins=2)
    res = _evaluate_go_no_go(folds, summ, ExperimentConfig())
    assert res["verdict"] == "NO-GO"
    assert res["criteria"]["c1_positive_in_3_folds_baseline"]["pass"] is False


def test_verdict_no_go_when_stress_inconsistent():
    folds = [_fold(0.001, 0.0)] * 3
    summ = _summary(ci_low=0.0005, stress_a=-0.001, stress_b=0.0, regime_wins=2)
    res = _evaluate_go_no_go(folds, summ, ExperimentConfig())
    assert res["verdict"] == "NO-GO"
    assert res["criteria"]["c3_stress_consistent"]["pass"] is False


# ---------------------------------------------------------------------------
# 4. Regime helper uses trailing information only
# ---------------------------------------------------------------------------
def test_regime_trailing_no_lookahead():
    rng = np.random.default_rng(1)
    n = 6000
    close = 1.1 + np.cumsum(rng.normal(0, 0.0005, n))
    bars = pd.DataFrame({"close": close})

    from nexora_laboratory.regime import RegimeConfig
    cfg = RegimeConfig(window=32, lookback=500)
    reg1 = trailing_regime(bars, cfg)

    # Corrupt the FUTURE (after t0); regime at rows <= t0 must be unchanged.
    t0 = 3000
    bars2 = bars.copy()
    bars2.loc[t0 + 1:, "close"] *= 1.05
    reg2 = trailing_regime(bars2, cfg)

    a = reg1.iloc[t0 - 500:t0 + 1].to_numpy()
    b = reg2.iloc[t0 - 500:t0 + 1].to_numpy()
    # Allow the very last row(s) near the boundary to be equal regardless.
    same = [(x == y) or (x is None and y is None) for x, y in zip(a, b)]
    assert all(same)
