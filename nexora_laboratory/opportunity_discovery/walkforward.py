"""Walk-forward multi-split validation (read-only extension of STAGE 5/6/7).

Purpose: STAGE 5/6 used a SINGLE 70/30 temporal split, which showed that apparent IC
was unstable (sign flips train->test, single-year concentration). A signal can pass a
single split by luck. Walk-forward evaluates the SAME causal feature on MANY
out-of-sample folds and requires the IC to be:
  (a) sign-consistent across folds (the majority sign recurs),
  (b) significant in a majority of folds, AND
  (c) not dominated by one fold (dispersion check).

A feature is "walk-forward stable" ONLY if it passes all three across folds. This is
the honest bar: it cannot be satisfied by a regime artifact that appears once.

Method (strictly causal, no look-ahead):
  * Expanding-window folds. Timeline split into ``n_folds`` test blocks of equal length.
    For fold k, TRAIN = all rows before the block, TEST = the block. Features use only
    data <= t within each row; targets are forward returns. No leakage.
  * Per fold, compute Spearman IC on the TEST block only (that block is OOS w.r.t. its
    own expanding train window). Actually we compute OOS IC on each test block.
  * Aggregate: fold IC series, majority sign, sign-match count, median IC, std, and
    how many folds are significant (two-sided p<alpha).

DESCRIPTIVE only: a stable IC is still association, NOT a trading edge / profit.
"""

from __future__ import annotations

from typing import Dict, List, Sequence

import numpy as np
import pandas as pd

from .information import build_features, forward_returns, _spearman


def make_folds(n: int, n_folds: int) -> List[tuple]:
    """Return list of (test_start, test_end) index ranges for expanding-window WF.

    The first fold's test block starts after an initial burn-in equal to one block so
    there is always a training window before it. Blocks are contiguous and cover the
    tail of the series (the most recent data), which is what matters for validation.
    """
    if n_folds < 2:
        raise ValueError("n_folds must be >= 2")
    block = n // (n_folds + 1)  # +1 leaves one initial block as first train burn-in
    if block < 1:
        raise ValueError("series too short for requested n_folds")
    folds = []
    for k in range(1, n_folds + 1):
        start = k * block
        end = (k + 1) * block if k < n_folds else n
        if end - start < 1:
            continue
        folds.append((start, end))
    return folds


def walkforward_ic(
    bars: pd.DataFrame,
    feature: str,
    features: pd.DataFrame,
    *,
    horizon: int,
    n_folds: int = 5,
    alpha: float = 0.05,
) -> Dict[str, object]:
    """Compute fold-by-fold OOS Spearman IC for one (feature, horizon)."""
    y = forward_returns(bars, horizon).to_numpy(dtype=float)
    x = features[feature].to_numpy(dtype=float)
    valid_all = np.isfinite(x) & np.isfinite(y)

    folds = make_folds(len(bars), n_folds)
    fold_ics: List[float] = []
    fold_ps: List[float] = []
    fold_ns: List[int] = []
    fold_bounds: List[tuple] = []

    idx = np.arange(len(bars))
    for (a, b) in folds:
        # PURGE: drop the last `horizon` bars of the block, because their forward
        # return reaches into the NEXT block -> would leak across folds.
        b_eff = b - horizon
        if b_eff <= a:
            fold_ics.append(float("nan"))
            fold_ps.append(float("nan"))
            fold_ns.append(0)
            fold_bounds.append((a, b))
            continue
        m = valid_all
        block_mask = (idx >= a) & (idx < b_eff) & m
        rho, p = _spearman(x[block_mask], y[block_mask])
        fold_ics.append(rho)
        fold_ps.append(p)
        fold_ns.append(int(block_mask.sum()))
        fold_bounds.append((a, b))

    ics = np.array([v for v in fold_ics if np.isfinite(v)])
    if len(ics) == 0:
        return {"feature": feature, "horizon": horizon, "stable": False,
                "reason": "no finite fold IC", "fold_ics": fold_ics}

    pos = ics[ics > 0]
    neg = ics[ics < 0]
    majority_sign = 1 if len(pos) >= len(neg) else -1
    sign_match = int(np.sum(np.sign(ics) == majority_sign))
    n_valid = int(len(ics))
    frac_sign = sign_match / n_valid

    med_ic = float(np.median(ics))
    std_ic = float(np.std(ics))
    # significance per fold (finite p & p<alpha)
    sig_folds = int(sum(1 for rp in zip(fold_ics, fold_ps)
                        if np.isfinite(rp[0]) and np.isfinite(rp[1]) and rp[1] < alpha))
    frac_sig = sig_folds / n_valid

    # dominance: share of |IC| mass held by the single largest |IC| fold
    abs_ics = np.abs(ics)
    dominance = float(abs_ics.max() / abs_ics.sum()) if abs_ics.sum() > 0 else 1.0

    return {
        "feature": feature,
        "horizon": int(horizon),
        "n_folds_valid": n_valid,
        "fold_ics": [round(float(v), 5) if np.isfinite(v) else None for v in fold_ics],
        "fold_ps": [round(float(v), 6) if np.isfinite(v) else None for v in fold_ps],
        "fold_ns": fold_ns,
        "fold_bounds": fold_bounds,
        "majority_sign": majority_sign,
        "sign_match": sign_match,
        "frac_sign_consistent": round(frac_sign, 4),
        "median_ic": round(med_ic, 5),
        "std_ic": round(std_ic, 5),
        "frac_folds_significant": round(frac_sig, 4),
        "max_fold_dominance": round(dominance, 4),
        "fold_ics_list": [round(float(v), 5) if np.isfinite(v) else None for v in fold_ics],
    }


# ----------------------------------------------------------------------------- #
# Stability verdict per (feature, horizon).
# ----------------------------------------------------------------------------- #
# Criteria (documented, strict):
# 1. sign consistency: >= SIGN_CONSIST_MIN of valid folds share the majority sign
# 2. majority significance: >= SIG_MIN of valid folds are individually significant
# 3. not dominated: max_fold_dominance <= DOMINANCE_MAX (one fold must not carry it)
# 4. magnitude: |median_ic| >= IC_MIN (non-trivial)
SIGN_CONSIST_MIN = 0.80
SIG_MIN = 0.60
DOMINANCE_MAX = 0.60
IC_MIN = 0.02


def stability_verdict(wf: Dict[str, object]) -> Dict[str, object]:
    if "fold_ics" not in wf or wf.get("n_folds_valid", 0) == 0:
        return {"stable": False, "reason": "insufficient folds"}
    frac_sign = wf["frac_sign_consistent"]
    frac_sig = wf["frac_folds_significant"]
    dom = wf["max_fold_dominance"]
    med = abs(wf["median_ic"])
    checks = {
        "sign_consistency": frac_sign >= SIGN_CONSIST_MIN,
        "majority_significant": frac_sig >= SIG_MIN,
        "not_dominated": dom <= DOMINANCE_MAX,
        "magnitude": med >= IC_MIN,
    }
    stable = all(checks.values())
    reasons = [k for k, v in checks.items() if not v]
    return {"stable": stable, "checks": checks,
            "failed_checks": reasons,
            "reason": "all pass" if stable else f"failed: {reasons}"}


def assess_walkforward(
    bars: pd.DataFrame,
    *,
    features_to_test: Sequence[str],
    horizons: Sequence[int],
    windows: Sequence[int] = (5, 20, 60),
    n_folds: int = 5,
    alpha: float = 0.05,
) -> Dict[str, object]:
    """Walk-forward assess a chosen feature x horizon grid."""
    feats = build_features(bars, windows=windows)
    rows: List[Dict[str, object]] = []
    for h in horizons:
        for f in features_to_test:
            if f not in feats.columns:
                continue
            wf = walkforward_ic(bars, f, feats, horizon=h, n_folds=n_folds, alpha=alpha)
            sv = stability_verdict(wf)
            row = dict(wf)
            row["stable"] = sv["stable"]
            row["stability_checks"] = sv["checks"]
            row["failed_checks"] = sv["failed_checks"]
            row["stability_reason"] = sv["reason"]
            rows.append(row)

    stable = [r for r in rows if r["stable"]]
    return {
        "n_folds": n_folds,
        "alpha": alpha,
        "n_tests": len(rows),
        "n_stable": len(stable),
        "criteria": {"sign_consist_min": SIGN_CONSIST_MIN, "sig_min": SIG_MIN,
                     "dominance_max": DOMINANCE_MAX, "ic_min": IC_MIN},
        "results": rows,
        "stable": stable,
    }
