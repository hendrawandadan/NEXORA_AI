"""FASE 2A — Directional-edge audit of a probability signal.

Question (R1 follow-up): does the predicted probability actually separate
HIGH-quality trades from BAD trades, or is the AUC/accuracy illusory once cost is
applied?

This module audits a signal using ONLY its held-out (OOS) probabilities and the
realized forward returns those probabilities were attached to. It is pure and
read-only; it does not train or label.

What it reports:
  1. Discrimination   : AUC (rank separation), and AUC of |p-0.5| vs |return|
                        (does confidence magnitude relate to payoff magnitude?).
  2. Calibration      : Brier / log-loss and reliability by probability bucket.
  3. Monotonicity     : does mean NET-of-cost return rise monotonically across
                        probability buckets? (separation that survives cost)
  4. Threshold grid   : for each |p-0.5| (or p) threshold, the trade count,
                        mean NET return, win rate, and total net return -> shows
                        whether ANY cut-off is profitable after cost.
  5. Spread/directional asymmetry: long vs short net edge by bucket.

Execution assumption: the input `realized_forward_return` is the signed return of
the traded direction (positive = favourable), so net = realized - round-trip cost.
Cost is expressed as a return fraction derived from a pip assumption at an assumed
reference price (caller supplies), documented as a SIMULATED cost.
"""

from __future__ import annotations

from typing import Dict, Optional

import numpy as np
import pandas as pd
from sklearn.metrics import roc_auc_score, brier_score_loss, log_loss


def _auc(y: np.ndarray, p: np.ndarray) -> Optional[float]:
    if len(np.unique(y)) < 2:
        return None
    return float(roc_auc_score(y, p))


def _cost_fraction(round_trip_cost_pips: float, reference_price: float) -> float:
    if reference_price <= 0:
        raise ValueError("reference_price must be positive")
    return (round_trip_cost_pips * 0.0001) / float(reference_price)


def audit_directional_edge(
    prob_up: np.ndarray,
    signed_return: np.ndarray,
    *,
    round_trip_cost_pips: float = 1.7,
    reference_price: float = 1.10,
    n_buckets: int = 10,
    threshold_grid: Optional[np.ndarray] = None,
) -> Dict[str, object]:
    """Audit whether probability separates cost-aware trade quality.

    Parameters
    ----------
    prob_up : model P(up), in [0,1].
    signed_return : realized return of the trade actually taken (direction-aware;
        positive means the trade won). Length must match prob_up.
    round_trip_cost_pips : round-trip cost in pips (spread+slippage, executable).
    reference_price : price used to convert pips -> return fraction (SIMULATED).
    """
    prob_up = np.asarray(prob_up, dtype=float)
    ret = np.asarray(signed_return, dtype=float)
    if len(prob_up) != len(ret):
        raise ValueError("prob_up and signed_return must have equal length")
    mask = np.isfinite(prob_up) & np.isfinite(ret)
    prob_up, ret = prob_up[mask], ret[mask]
    if len(ret) == 0:
        raise ValueError("no finite rows to audit")

    cost = _cost_fraction(round_trip_cost_pips, reference_price)
    net = ret - cost
    win_gross = (ret > 0).astype(int)
    win_net = (net > 0).astype(int)

    # --- 1. discrimination ---
    # Direction correctness: did prob exceed 0.5 on a winning trade (and below on a loser)?
    discrimination = {
        "auc_dir_gross": _auc(win_gross, prob_up),
        "auc_dir_net": _auc(win_net, prob_up),
        "n": int(len(ret)),
        "positive_rate_gross": float(win_gross.mean()),
        "positive_rate_net": float(win_net.mean()),
    }
    # Confidence magnitude vs payoff magnitude (does |p-.5| predict |return|?)
    conf = np.abs(prob_up - 0.5)
    if len(np.unique(np.round(conf, 6))) >= 2:
        # Spearman via rank corr of confidence vs abs gross return
        rc = np.corrcoef(pd.Series(conf).rank(), pd.Series(np.abs(ret)).rank())[0, 1]
        discrimination["spearman_conf_vs_absreturn"] = float(rc)
    else:
        discrimination["spearman_conf_vs_absreturn"] = None

    # --- 2. calibration ---
    calibration = {
        "brier": float(brier_score_loss(win_gross, np.clip(prob_up, 1e-6, 1 - 1e-6)))
        if len(np.unique(win_gross)) == 2 else None,
        "log_loss": float(log_loss(win_gross, np.clip(prob_up, 1e-6, 1 - 1e-6),
                                   labels=[0, 1])) if len(np.unique(win_gross)) == 2 else None,
    }

    # --- 3. bucket monotonicity (by prob_up deciles) ---
    q = pd.qcut(prob_up, q=min(n_buckets, len(np.unique(prob_up))),
                labels=False, duplicates="drop")
    bucket_rows = []
    for b in sorted(pd.Series(q).dropna().unique()):
        sel = q == b
        if sel.sum() == 0:
            continue
        bucket_rows.append({
            "bucket": int(b),
            "p_min": float(prob_up[sel].min()),
            "p_max": float(prob_up[sel].max()),
            "n": int(sel.sum()),
            "mean_ret_gross": float(ret[sel].mean()),
            "mean_ret_net": float(net[sel].mean()),
            "win_rate_net": float(win_net[sel].mean()),
        })
    bucket_df = pd.DataFrame(bucket_rows)
    # monotonicity: Spearman of bucket index vs mean_ret_net
    if len(bucket_df) >= 3 and bucket_df["mean_ret_net"].nunique() > 1:
        mono = float(np.corrcoef(
            bucket_df["bucket"].rank(), bucket_df["mean_ret_net"].rank())[0, 1])
    else:
        mono = None

    # --- 4. threshold grid: trade longs when p>=t, shorts when p<=1-t ---
    if threshold_grid is None:
        threshold_grid = np.round(np.arange(0.50, 0.71, 0.02), 3)
    grid_rows = []
    for t in threshold_grid:
        long_sel = prob_up >= t
        short_sel = prob_up <= (1 - t)
        row = {"threshold": float(t)}
        for name, sel in (("long", long_sel), ("short", short_sel)):
            if sel.sum() == 0:
                row[f"{name}_n"] = 0
                row[f"{name}_mean_net"] = float("nan")
                row[f"{name}_win_net"] = float("nan")
                row[f"{name}_total_net"] = 0.0
                continue
            row[f"{name}_n"] = int(sel.sum())
            row[f"{name}_mean_net"] = float(net[sel].mean())
            row[f"{name}_win_net"] = float(win_net[sel].mean())
            row[f"{name}_total_net"] = float(net[sel].sum())
        grid_rows.append(row)
    grid_df = pd.DataFrame(grid_rows)

    best_cut = None
    if not grid_df.empty:
        combo = grid_df["long_total_net"].fillna(0) + grid_df["short_total_net"].fillna(0)
        if combo.notna().any():
            idx = combo.idxmax()
            best_cut = {"threshold": float(grid_df.loc[idx, "threshold"]),
                        "total_net": float(combo.loc[idx])}

    return {
        "n": int(len(ret)),
        "cost_fraction": float(cost),
        "round_trip_cost_pips": float(round_trip_cost_pips),
        "reference_price": float(reference_price),
        "discrimination": discrimination,
        "calibration": calibration,
        "buckets": bucket_df,
        "bucket_monotonicity_spearman": mono,
        "threshold_grid": grid_df,
        "best_threshold_total_net": best_cut,
    }


def verdict_from_audit(audit: Dict[str, object], min_auc: float = 0.52) -> Dict[str, object]:
    """Summarise whether the signal carries a usable, cost-surviving directional edge.

    Usable edge (GO on the *signal*) requires BOTH:
      * discrimination: net AUC > min_auc (above chance once cost applied), and
      * monotonicity: bucket mean net return rises with probability (spearman > 0), and
      * at least one threshold with positive TOTAL net return.
    Otherwise the edge is NOT economically usable after cost, even if AUC looks ok.
    """
    d = audit["discrimination"]
    auc_net = d.get("auc_dir_net")
    mono = audit.get("bucket_monotonicity_spearman")
    best = audit.get("best_threshold_total_net")
    checks = {
        "auc_net_above_chance": bool(auc_net is not None and auc_net > min_auc),
        "buckets_monotonic": bool(mono is not None and mono > 0),
        "some_threshold_profitable": bool(best is not None and best["total_net"] > 0),
    }
    usable = all(checks.values())
    return {"usable_edge": usable, "checks": checks,
            "auc_net": auc_net, "bucket_monotonicity": mono,
            "best_threshold": best}
