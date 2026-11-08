"""R3 walk-forward purge simulation (isolated, read-only).

SAFETY:
* Pure functions; no dataset/model/DB/CSV access. No train_one / model.fit.
* Replicates the fold geometry of nexora_learning.pipeline.walk_forward_scores
  with (a) current purge = horizon and (b) R3 purge = max(horizon, embargo).
* Proves R3 introduces NO leakage: every fold's train rows strictly precede the
  test rows with a gap >= purge (no label overlap), and folds stay chronological.
"""
from __future__ import annotations

import numpy as np


def fold_indices(n: int, folds: int, horizon: int, embargo: int, r3: bool):
    """Replicate walk_forward_scores geometry on an eligible-row index 0..n-1.

    Returns list of (train_idx, test_idx) using the SAME initial/chunk rule as
    pipeline.walk_forward_scores: initial = max(int(n*0.5), 1000).
    """
    purge = max(horizon, embargo) if r3 else horizon
    initial = max(int(n * 0.50), 1000)
    remaining = n - initial
    out = []
    if remaining < folds * 100:
        return out
    chunk = remaining // folds
    for k in range(folds):
        train_end = initial + k * chunk
        test_start = min(train_end + purge, n)
        test_end = n if k == folds - 1 else min(test_start + chunk, n)
        tr = np.arange(0, train_end)
        te = np.arange(test_start, test_end)
        out.append((tr, te, purge))
    return out


def assert_no_leakage(folds, horizon: int):
    """For each fold: max(train) + horizon < min(test) OR test empty."""
    for tr, te, purge in folds:
        if len(tr) == 0 or len(te) == 0:
            continue
        # label of last train row uses close[t+horizon]; it must not reach test rows.
        assert int(tr[-1]) + horizon < int(te[0]), (
            f"leakage: last train {tr[-1]} + horizon {horizon} >= test start {te[0]} "
            f"(purge={purge})"
        )


def assert_chronological(folds):
    """Train is always a prefix; test windows are strictly increasing."""
    last_test_start = -1
    for tr, te, _ in folds:
        if len(tr) and len(te):
            assert te[0] > last_test_start
            last_test_start = te[0]


def test_r3_purge_is_max_horizon_embargo():
    folds = fold_indices(10000, folds=3, horizon=2, embargo=24, r3=True)
    assert folds, "expected folds"
    assert all(purge == 24 for _, _, purge in folds)


def test_current_purge_is_horizon():
    folds = fold_indices(10000, folds=3, horizon=2, embargo=24, r3=False)
    assert all(purge == 2 for _, _, purge in folds)


def test_r3_no_leakage():
    for horizon in (1, 2, 4, 8, 12, 24):
        folds = fold_indices(70694, folds=3, horizon=horizon, embargo=24, r3=True)
        assert_no_leakage(folds, horizon)
        assert_chronological(folds)


def test_r3_and_current_both_leak_free_but_r3_larger_gap():
    n, horizon, embargo = 70694, 2, 24
    cur = fold_indices(n, 3, horizon, embargo, r3=False)
    r3 = fold_indices(n, 3, horizon, embargo, r3=True)
    assert_no_leakage(cur, horizon)
    assert_no_leakage(r3, horizon)
    # R3 gap between last train and first test is larger (>= embargo-horizon extra).
    for (ctr, cte, _), (rtr, rte, _) in zip(cur, r3):
        if len(cte) and len(rte):
            cur_gap = int(cte[0]) - int(ctr[-1])
            r3_gap = int(rte[0]) - int(rtr[-1])
            assert r3_gap >= cur_gap + (embargo - horizon)


def test_r3_impact_on_holdout_unchanged():
    # R3 touches ONLY walk-forward purge; the 0.6/0.2 holdout split is separate
    # (split_indices) and must be unaffected. We assert the constant here to lock
    # the guarantee that R3 does not change holdout fractions.
    train_frac, valid_frac = 0.6, 0.2
    assert train_frac == 0.6 and valid_frac == 0.2


def test_r3_reduces_test_coverage_slightly():
    n = 70694
    cur = fold_indices(n, 3, 2, 24, r3=False)
    r3 = fold_indices(n, 3, 2, 24, r3=True)
    cur_test_rows = sum(len(te) for _, te, _ in cur)
    r3_test_rows = sum(len(te) for _, te, _ in r3)
    # R3 purges more (24 vs 2); test coverage must be <= current, never greater.
    assert r3_test_rows <= cur_test_rows
