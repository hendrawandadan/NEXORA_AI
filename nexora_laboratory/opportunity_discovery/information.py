"""STAGE 5 — New Information Assessment (pure, read-only).

Question this answers: does a given CAUSAL price-derived feature carry information
about FUTURE returns that is (a) present OUT-OF-SAMPLE and (b) statistically
significant after correcting for the many feature x horizon tests we run?

Method (deliberately model-free):
  1. Build causal features at bar t using ONLY data up to and including t.
  2. Target = forward return over horizon h (close[t] -> close[t+h]).
  3. Split time into TRAIN (early) and TEST (later) segments -> no look-ahead leak.
  4. IC = Spearman rank correlation between feature(t) and forward return(t),
     computed SEPARATELY on TRAIN and TEST. The TEST IC is the OOS evidence.
  5. Significance: two-sided p-value of the Spearman correlation; then
     Benjamini-Hochberg FDR and Bonferroni across all tests.

Everything is descriptive/diagnostic: an IC is "association strength", NOT a
trading edge, NOT profitability, and NOT a model result. A weak/insignificant IC
is reported honestly (including negative ICs and failures).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional, Sequence

import numpy as np
import pandas as pd
from scipy import stats


# ----------------------------------------------------------------------------- #
# Causal features (NO look-ahead: every value at index t uses rows <= t).
# ----------------------------------------------------------------------------- #
def build_features(bars: pd.DataFrame, *, windows: Sequence[int] = (5, 20, 60)) -> pd.DataFrame:
    """Return a DataFrame of causal features aligned to bars.index.

    Features (all use only data <= t):
      ret_k      : k-bar simple return close[t]/close[t-k] - 1
      zclose_k   : (close[t] - SMA_k[t]) / STD_k[t]   (price z-score)
      vol_k      : rolling std of 1-bar returns over k (realized vol proxy)
      rng_k      : mean(high-low)/close over k
      posrng_k   : position of close within trailing k-bar high-low range (0..1)
      rsi_k      : Wilder-style RSI over k
    """
    close = bars["close"].astype(float)
    high = bars["high"].astype(float)
    low = bars["low"].astype(float)
    ret1 = close.pct_change()

    feats: Dict[str, pd.Series] = {}
    for k in windows:
        feats[f"ret_{k}"] = close / close.shift(k) - 1.0
        sma = close.rolling(k).mean()
        std = close.rolling(k).std()
        feats[f"zclose_{k}"] = (close - sma) / std.replace(0, np.nan)
        feats[f"vol_{k}"] = ret1.rolling(k).std()
        rng = ((high - low) / close).rolling(k).mean()
        feats[f"rng_{k}"] = rng
        roll_hi = high.rolling(k).max()
        roll_lo = low.rolling(k).min()
        span = (roll_hi - roll_lo).replace(0, np.nan)
        feats[f"posrng_{k}"] = (close - roll_lo) / span
        # RSI (Wilder): use simple EMA of gains/losses (causal)
        up = ret1.clip(lower=0).rolling(k).mean()
        dn = (-ret1.clip(upper=0)).rolling(k).mean()
        rs = up / dn.replace(0, np.nan)
        feats[f"rsi_{k}"] = 100 - 100 / (1 + rs)

    out = pd.DataFrame(feats, index=bars.index)
    return out


def forward_returns(bars: pd.DataFrame, h: int) -> pd.Series:
    """Forward simple return close[t+h]/close[t] - 1 (target). Uses future data but
    ONLY as the label; never fed back as a feature."""
    close = bars["close"].astype(float)
    return close.shift(-h) / close - 1.0


# ----------------------------------------------------------------------------- #
# IC computation.
# ----------------------------------------------------------------------------- #
@dataclass
class ICTest:
    feature: str
    horizon: int
    segment: str            # 'train' | 'test'
    ic: float               # Spearman rho
    p_value: float
    n: int

    def as_dict(self) -> Dict[str, object]:
        return {"feature": self.feature, "horizon": self.horizon,
                "segment": self.segment, "ic": round(self.ic, 5),
                "p_value": round(self.p_value, 6), "n": self.n}


def _spearman(x: np.ndarray, y: np.ndarray) -> tuple:
    if len(x) < 20:
        return (float("nan"), float("nan"))
    # guard against constant input
    if np.nanstd(x) == 0 or np.nanstd(y) == 0:
        return (float("nan"), float("nan"))
    rho, p = stats.spearmanr(x, y)
    return (float(rho), float(p))


def split_mask(bars: pd.DataFrame, test_frac: float = 0.30) -> np.ndarray:
    """Temporal split: last ``test_frac`` of rows = TEST, the rest = TRAIN."""
    n = len(bars)
    n_test = int(round(n * test_frac))
    cut = n - n_test
    m = np.zeros(n, dtype=bool)
    m[cut:] = True
    return m  # True = test


def compute_ic(features: pd.DataFrame, target: pd.Series, feature: str, h: int,
               test_mask: np.ndarray) -> Dict[str, ICTest]:
    """Compute train/test Spearman IC for one (feature, horizon)."""
    x = features[feature].to_numpy(dtype=float)
    y = target.to_numpy(dtype=float)
    valid = np.isfinite(x) & np.isfinite(y)

    tr = valid & (~test_mask)
    te = valid & test_mask

    rho_tr, p_tr = _spearman(x[tr], y[tr])
    rho_te, p_te = _spearman(x[te], y[te])
    return {
        "train": ICTest(feature, h, "train", rho_tr, p_tr, int(tr.sum())),
        "test": ICTest(feature, h, "test", rho_te, p_te, int(te.sum())),
    }


# ----------------------------------------------------------------------------- #
# Multiple-comparison correction.
# ----------------------------------------------------------------------------- #
def benjamini_hochberg(pvals: Sequence[float], alpha: float = 0.05) -> Dict[str, object]:
    """BH-FDR. Returns per-test rejections + adjusted q-values (order preserved)."""
    p = np.asarray(pvals, dtype=float)
    m = len(p)
    order = np.argsort(p)
    ranked = p[order]
    q = np.empty(m)
    # q_i = min_{k>=i} (p_k * m / k)
    prev = 1.0
    for i in range(m - 1, -1, -1):
        val = ranked[i] * m / (i + 1)
        prev = min(prev, val)
        q[i] = prev
    qvals = np.empty(m)
    qvals[order] = np.minimum(q, 1.0)
    reject = qvals <= alpha
    return {"reject": reject.tolist(), "q_values": qvals.tolist(),
            "alpha": alpha, "n_tests": m}


def bonferroni(pvals: Sequence[float], alpha: float = 0.05) -> Dict[str, object]:
    p = np.asarray(pvals, dtype=float)
    m = len(p)
    thr = alpha / m if m else alpha
    reject = p <= thr
    return {"reject": reject.tolist(), "threshold": thr, "alpha": alpha, "n_tests": m}


# ----------------------------------------------------------------------------- #
# Full assessment for one instrument.
# ----------------------------------------------------------------------------- #
def assess_information(
    bars: pd.DataFrame,
    *,
    horizons: Sequence[int],
    windows: Sequence[int] = (5, 20, 60),
    test_frac: float = 0.30,
    alpha: float = 0.05,
) -> Dict[str, object]:
    """Run the full model-free IC assessment over feature x horizon grid."""
    feats = build_features(bars, windows=windows)
    test_mask = split_mask(bars, test_frac=test_frac)

    feature_names = list(feats.columns)
    rows: List[Dict[str, object]] = []
    # collect test-set p-values for multiple comparison
    test_tests: List[ICTest] = []

    for h in horizons:
        tgt = forward_returns(bars, h)
        for fname in feature_names:
            res = compute_ic(feats, tgt, fname, h, test_mask)
            tr, te = res["train"], res["test"]
            rows.append({
                "feature": fname, "horizon": int(h),
                "train_ic": round(tr.ic, 5) if np.isfinite(tr.ic) else None,
                "train_p": round(tr.p_value, 6) if np.isfinite(tr.p_value) else None,
                "train_n": tr.n,
                "test_ic": round(te.ic, 5) if np.isfinite(te.ic) else None,
                "test_p": round(te.p_value, 6) if np.isfinite(te.p_value) else None,
                "test_n": te.n,
                # sign consistency between train and test (a robustness hint)
                "sign_consistent": bool(
                    np.isfinite(tr.ic) and np.isfinite(te.ic)
                    and np.sign(tr.ic) == np.sign(te.ic)),
            })
            if np.isfinite(te.p_value):
                test_tests.append(te)

    ic_table = pd.DataFrame(rows)

    # Multiple-comparison on the TEST-set p-values (OOS evidence only).
    pvals = [t.p_value for t in test_tests]
    bh = benjamini_hochberg(pvals, alpha=alpha)
    bf = bonferroni(pvals, alpha=alpha)

    # Map back to the table rows that had a finite test p-value.
    has_p = [i for i, r in enumerate(rows) if r["test_p"] is not None]
    bh_q = [None] * len(rows)
    bf_rej = [None] * len(rows)
    for j, idx in enumerate(has_p):
        bh_q[idx] = round(bh["q_values"][j], 6)
        bf_rej[idx] = bool(bf["reject"][j])
    ic_table["test_q_bh"] = bh_q
    ic_table["test_reject_bonferroni"] = bf_rej
    ic_table["test_reject_bh"] = [None if q is None else bool(q <= alpha)
                                  for q in bh_q]

    # Headline survivors: OOS-significant after BH on TEST set.
    survivors = ic_table[ic_table["test_reject_bh"] == True].copy()  # noqa: E712
    survivors = survivors.sort_values("test_ic", key=lambda s: s.abs(), ascending=False)

    return {
        "n_features": len(feature_names),
        "n_horizons": len(horizons),
        "n_tests": int(len(ic_table)),
        "test_frac": test_frac,
        "alpha": alpha,
        "multiple_comparison": {
            "bh_alpha": bh["alpha"], "bh_n_tests": bh["n_tests"],
            "bonferroni_threshold": bf["threshold"],
            "n_survive_bh": int((ic_table["test_reject_bh"] == True).sum()),  # noqa: E712
            "n_survive_bonferroni": int((ic_table["test_reject_bonferroni"] == True).sum()),  # noqa: E712
        },
        "ic_table": ic_table.to_dict("records"),
        "survivors": survivors.to_dict("records"),
        "feature_names": feature_names,
    }
