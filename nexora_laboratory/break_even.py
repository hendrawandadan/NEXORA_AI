"""FASE 2A — Audit A: break-even horizon vs transaction cost.

Pure, read-only. Answers: for each horizon, what directional accuracy is REQUIRED
to break even after cost, given the realized move size at that horizon? And does
ANY observed accuracy clear it?

Two break-even models are provided because the symmetric-payoff model understates
what a real barrier trade needs:

  symmetric (outcome is +move or -move, equal size):
      EV = p*s - (1-p)*s - C = 0   ->   p* = 0.5 + C/(2s)
      where s = representative move size (price), C = round-trip cost (price).

  barrier / payoff-asymmetric (TP = k_up*S, SL = k_dn*S, hit-up prob q, vertical
  timeout handled by expected drift 0 assumption):
      EV = q*k_up*S - (1-q)*k_dn*S - C = 0  ->  q* = (k_dn + c)/(k_up + k_dn)
      where S = barrier scale (e.g. ATR), c = C/S. This matches the triple-barrier
      geometry the project actually uses.

All arithmetic in PRICE units internally; pips are display-only (1 pip = 0.0001).

NO look-ahead: move sizes are computed from realized future bars purely to size the
*requirement*; they are descriptive statistics, not used to predict. This module
does not train or evaluate a model.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional

import numpy as np
import pandas as pd

PIP = 0.0001


@dataclass
class CostModel:
    """SIMULATED round-trip cost in pips (explicitly an assumption)."""

    spread_pips: float
    slippage_pips: float = 0.2
    commission_pips: float = 0.0

    @property
    def round_trip_pips(self) -> float:
        return float(self.spread_pips + self.slippage_pips + self.commission_pips)

    def as_price(self) -> float:
        return self.round_trip_pips * PIP

    def as_dict(self) -> Dict[str, float]:
        return {"spread_pips": self.spread_pips, "slippage_pips": self.slippage_pips,
                "commission_pips": self.commission_pips,
                "round_trip_pips": self.round_trip_pips}


def realized_move_sizes(bars: pd.DataFrame, horizons: List[int]) -> pd.DataFrame:
    """Median/mean/p75 of |open[t+h]-open[t]| per horizon, in pips.

    Descriptive only (uses realized bars to size the *requirement*). The negative
    shift aligns a t-bar decision with the t+h open, matching the T3 entry/exit
    (open[t+1] -> open[t+1+h]) convention closely enough for move-sizing; we use
    open[t] -> open[t+h] here as the generic 'move over h bars'.
    """
    op = bars["open"].to_numpy(dtype=float)
    n = len(op)
    rows = []
    for h in horizons:
        if h <= 0 or h >= n:
            continue
        move_pips = np.abs(op[h:] - op[:-h]) / PIP
        move_pips = move_pips[np.isfinite(move_pips)]
        rows.append({
            "horizon_bars": int(h),
            "n": int(len(move_pips)),
            "median_pips": float(np.median(move_pips)),
            "mean_pips": float(np.mean(move_pips)),
            "p75_pips": float(np.percentile(move_pips, 75)),
        })
    return pd.DataFrame(rows)


def break_even_accuracy_symmetric(move_price: float, cost_price: float) -> float:
    """Required up-accuracy p* = 0.5 + C/(2*s) for a symmetric-payoff bet."""
    if move_price <= 0:
        raise ValueError("move_price must be positive")
    return 0.5 + cost_price / (2.0 * move_price)


def break_even_accuracy_barrier(cost_price: float, scale_price: float,
                                k_up: float = 1.5, k_dn: float = 1.0) -> float:
    """Required up-hit probability q* = (k_dn + c)/(k_up + k_dn), c = C/scale.

    For EV = q*k_up*S - (1-q)*k_dn*S - C = 0.
    """
    if scale_price <= 0:
        raise ValueError("scale_price must be positive")
    c = cost_price / scale_price
    return (k_dn + c) / (k_up + k_dn)


def feasibility_table(
    moves: pd.DataFrame,
    cost: CostModel,
    *,
    observed_accuracy: Optional[Dict[int, float]] = None,
    barrier_scale_by_h: Optional[Dict[int, float]] = None,
    k_up: float = 1.5,
    k_dn: float = 1.0,
) -> pd.DataFrame:
    """Per-horizon required vs observed accuracy and feasibility.

    Parameters
    ----------
    moves : output of realized_move_sizes (has median_pips, horizon_bars).
    cost : CostModel (round-trip, pips).
    observed_accuracy : {horizon_bars: actual_oos_accuracy} if known (optional).
    barrier_scale_by_h : {horizon_bars: barrier scale in PRICE}. If given, also
        compute the barrier break-even; else use median move as scale proxy.

    Returns a DataFrame with required accuracies and a ``feasible`` flag
    (observed >= required, symmetric model) when observed is provided.
    """
    cost_p = cost.as_price()
    rows = []
    for _, r in moves.iterrows():
        h = int(r["horizon_bars"])
        med_p = float(r["median_pips"]) * PIP
        req_sym = break_even_accuracy_symmetric(med_p, cost_p)
        scale_p = (barrier_scale_by_h or {}).get(h, med_p)
        req_bar = break_even_accuracy_barrier(cost_p, scale_p, k_up, k_dn)
        row = {
            "horizon_bars": h,
            "median_move_pips": float(r["median_pips"]),
            "cost_pips": cost.round_trip_pips,
            "required_acc_symmetric": req_sym,
            "required_acc_barrier": req_bar,
        }
        if observed_accuracy and h in observed_accuracy and observed_accuracy[h] is not None:
            obs = float(observed_accuracy[h])
            row["observed_accuracy"] = obs
            row["gap_symmetric"] = obs - req_sym
            row["gap_barrier"] = obs - req_bar
            row["feasible_symmetric"] = bool(obs >= req_sym)
            row["feasible_barrier"] = bool(obs >= req_bar)
        rows.append(row)
    return pd.DataFrame(rows)


def any_feasible(feasibility: pd.DataFrame) -> Dict[str, object]:
    """Summarise whether ANY horizon clears break-even (symmetric or barrier)."""
    out: Dict[str, object] = {"feasible_horizons_symmetric": [], "feasible_horizons_barrier": []}
    if "feasible_symmetric" in feasibility:
        out["feasible_horizons_symmetric"] = feasibility.loc[
            feasibility["feasible_symmetric"] == True, "horizon_bars"].tolist()  # noqa: E712
    if "feasible_barrier" in feasibility:
        out["feasible_horizons_barrier"] = feasibility.loc[
            feasibility["feasible_barrier"] == True, "horizon_bars"].tolist()  # noqa: E712
    out["any_feasible_symmetric"] = len(out["feasible_horizons_symmetric"]) > 0
    out["any_feasible_barrier"] = len(out["feasible_horizons_barrier"]) > 0
    return out
