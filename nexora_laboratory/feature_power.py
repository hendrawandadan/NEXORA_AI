"""FASE 2A — Audit B: out-of-sample feature power.

Pure, read-only. Answers: does any of the model's features carry OOS information
about the future signed return (IC / mutual information), stable enough to imply a
cost-relevant edge?

All metrics are computed on a caller-supplied OUT-OF-SAMPLE slice only (the test
split). This module never refits on the data it measures, and never uses future
bars to build a feature.

Method
------
  IC            = Spearman rank correlation between feature[t] and signed_fwd[t].
                  Block-bootstrap CI (blocks preserve autocorrelation of returns).
  MI            = mutual information between a discretized feature and the SIGN of
                  the future return (bits); 0 = independent.
  Cost-relevance: convert a feature's implied directional edge into 'does |IC|
                  plausibly clear break-even at the median move/cost' using a
                  simple linear proxy: edge_est = IC * std(fwd) (rank-IC scaled).

Block bootstrap: resample contiguous blocks of length `block` (>= label horizon so
overlap is respected) with replacement; recompute IC each time -> 95% CI.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional

import numpy as np
import pandas as pd
from scipy.stats import spearmanr
from sklearn.metrics import mutual_info_score


@dataclass
class FeaturePowerResult:
    feature: str
    ic: float
    ic_ci_low: float
    ic_ci_high: float
    mi_bits: float
    n: int
    ic_excludes_zero: bool

    def as_dict(self) -> Dict[str, object]:
        return {
            "feature": self.feature, "ic": self.ic, "ic_ci_low": self.ic_ci_low,
            "ic_ci_high": self.ic_ci_high, "mi_bits": self.mi_bits, "n": self.n,
            "ic_excludes_zero": self.ic_excludes_zero,
        }


def _spearman(a: np.ndarray, b: np.ndarray) -> float:
    if len(a) < 3:
        return float("nan")
    # spearmanr is ~2x slower than rank+pearson; do it manually for bootstrap speed
    ra = pd.Series(a).rank().to_numpy()
    rb = pd.Series(b).rank().to_numpy()
    sa, sb = ra.std(), rb.std()
    if sa == 0 or sb == 0:
        return float("nan")
    return float(np.mean((ra - ra.mean()) * (rb - rb.mean())) / (sa * sb))


def _block_bootstrap_ic(
    feature: np.ndarray, target: np.ndarray, block: int, iters: int, seed: int
) -> tuple:
    n = len(feature)
    if n < block * 2 or iters <= 0:
        return float("nan"), float("nan")
    rng = np.random.default_rng(seed)
    n_blocks = int(np.ceil(n / block))
    ics = np.empty(iters)
    for i in range(iters):
        starts = rng.integers(0, n - block, n_blocks)
        idx = np.concatenate([np.arange(s, s + block) for s in starts])[:n]
        ics[i] = _spearman(feature[idx], target[idx])
    ics = ics[np.isfinite(ics)]
    if len(ics) == 0:
        return float("nan"), float("nan")
    return float(np.quantile(ics, 0.025)), float(np.quantile(ics, 0.975))


def _discretize(x: np.ndarray, q: int = 5) -> np.ndarray:
    """Rank-based quantile discretization to ints (-1 = invalid/NaN bucket)."""
    out = np.full(len(x), -1, dtype=int)
    ok = np.isfinite(x)
    if ok.sum() < q:
        return out
    vals = x[ok]
    ranks = pd.Series(vals).rank(method="first")  # 'first' avoids duplicate-edge NaN
    try:
        bins = pd.qcut(ranks, q=q, labels=False, duplicates="drop")
    except ValueError:
        return out
    bins = bins.to_numpy()
    # map NaN (shouldn't happen with rank 'first', but guard) to -1
    finite_bins = np.isfinite(bins)
    tmp = np.full(len(vals), -1, dtype=int)
    tmp[finite_bins] = bins[finite_bins].astype(int)
    out[ok] = tmp
    return out


def feature_power_oos(
    X_test: pd.DataFrame,
    signed_fwd: np.ndarray,
    *,
    horizon_bars: int = 2,
    block: Optional[int] = None,
    iters: int = 500,
    seed: int = 42,
    min_ic_to_keep: float = 0.02,
) -> Dict[str, object]:
    """Compute per-feature OOS IC (with block-bootstrap CI) and MI vs sign(fwd).

    Parameters
    ----------
    X_test : feature matrix on the TEST split only (chronological, no leakage).
    signed_fwd : signed future return aligned to X_test rows.
    horizon_bars : label horizon (sets default bootstrap block length).
    """
    signed_fwd = np.asarray(signed_fwd, dtype=float)
    if len(X_test) != len(signed_fwd):
        raise ValueError("X_test and signed_fwd must align")
    if block is None:
        # block >= horizon so overlapping labels are respected; scale to ~n^(1/3)
        block = max(int(horizon_bars), int(round(len(signed_fwd) ** (1 / 3))))

    sign = (signed_fwd > 0).astype(int)
    results: List[FeaturePowerResult] = []
    for col in X_test.columns:
        x = X_test[col].to_numpy(dtype=float)
        ok = np.isfinite(x) & np.isfinite(signed_fwd)
        if ok.sum() < block * 2:
            continue
        xv, tv = x[ok], signed_fwd[ok]
        ic = _spearman(xv, tv)
        lo, hi = _block_bootstrap_ic(xv, tv, block, iters, seed)
        # MI between discretized feature and sign
        xd = _discretize(xv)
        keep = xd >= 0
        try:
            mi = float(mutual_info_score(xd[keep], sign[ok][keep])) if keep.sum() > 10 else 0.0
        except Exception:
            mi = 0.0
        excludes0 = bool(np.isfinite(lo) and np.isfinite(hi) and (lo > 0 or hi < 0))
        results.append(FeaturePowerResult(str(col), ic, lo, hi, mi, int(ok.sum()),
                                          excludes0))

    results.sort(key=lambda r: abs(r.ic) if np.isfinite(r.ic) else 0.0, reverse=True)
    usable = [r for r in results if r.ic_excludes_zero and np.isfinite(r.ic)
              and abs(r.ic) >= min_ic_to_keep]

    return {
        "n_rows": int(len(signed_fwd)),
        "block_len": int(block),
        "iters": int(iters),
        "features": results,
        "usable_features": [r.feature for r in usable],
        "n_usable": len(usable),
        "verdict": (
            "features_have_usable_oos_power" if len(usable) > 0
            else "no_feature_clears_oos_ic_bar"
        ),
    }
