"""Horizon Discovery: which (timeframe, horizon) has move large enough vs cost.

Combines:
    moves.forward_move_stats       -> move distribution per horizon
    cost_engine.CostComponents     -> explicit spread/slippage/commission (pips)
    break_even.break_even_accuracy_*-> required directional accuracy

Outputs per candidate a row with:
    median/mean move (pips), movement-to-cost ratio, required accuracy
    (symmetric + barrier), implied linear net expectancy under each scenario,
    plus per-year and per-vol-regime stability summaries.

Net expectancy here is a *conditional diagnostic*, NOT a model result:
    For a directional bet with up-accuracy p and symmetric payoff sized to the
    median move s:  E_net = p*s - (1-p)*s - cost  = (2p-1)*s - cost  (in pips).
    We report it as a function of assumed p (breakeven p* gives E_net=0). This
    does NOT imply a model achieves p; it only maps required-hit to economics.

No look-ahead: forward moves are realised future data used descriptively only.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional

import numpy as np
import pandas as pd

from ..break_even import break_even_accuracy_symmetric, break_even_accuracy_barrier
from .moves import forward_move_stats


# ---- pip factors per instrument (documented; NOT a universal constant) ---------
# EURUSD/GBPUSD 5-digit: 1 pip = 0.0001. USDJPY 3-digit: 1 pip = 0.01.
# XAUUSD 2-digit: convention here treats 1 "pip" = 0.10 (industry XAU pip), but we
# ALSO report price-unit move so the reader can re-derive with any convention.
def pip_size_for(symbol: str) -> float:
    s = symbol.upper()
    if "JPY" in s:
        return 0.01
    if "XAU" in s or "GOLD" in s:
        return 0.10  # 1 XAUUSD "pip" = 0.10 USD (common XAU convention)
    return 0.0001  # standard 5-digit FX


@dataclass
class Scenario:
    name: str
    spread_pips: float
    slippage_pips: float
    commission_pips: float = 0.0

    @property
    def round_trip_pips(self) -> float:
        return self.spread_pips + self.slippage_pips + self.commission_pips


def _vol_regimes(bars: pd.DataFrame, window: int = 100) -> pd.Series:
    """Classify each bar by rolling return-volatility tercile (LOW/MID/HIGH).

    Uses ONLY trailing information (shift(1)) to avoid look-ahead. Returns a
    per-bar label aligned to bars.index.
    """
    ret = bars["close"].pct_change().abs()
    vol = ret.rolling(window).mean().shift(1)  # trailing only
    lab = pd.Series(index=bars.index, dtype=object)
    ok = vol.notna()
    if ok.sum() >= 3:
        q1, q2 = vol[ok].quantile([1 / 3, 2 / 3])
        lab[ok] = np.where(vol[ok] <= q1, "LOW",
                           np.where(vol[ok] <= q2, "MID", "HIGH"))
    return lab


def _year_of(bars: pd.DataFrame) -> pd.Series:
    return bars["ts"].dt.year.astype("Int64")


def horizon_economics(
    bars: pd.DataFrame,
    horizons: List[int],
    scenarios: List[Scenario],
    pip_size: float,
    *,
    k_up: float = 1.5,
    k_dn: float = 1.0,
    mfe_mae: bool = True,
) -> Dict[str, object]:
    """Compute per-horizon economics under each scenario + stability slices."""
    # Base move stats (absolute) for sizing.
    base_rows = []
    for h in horizons:
        st = forward_move_stats(bars, h, pip_size).as_dict()
        base_rows.append(st)
    base = pd.DataFrame(base_rows)

    out_rows = []
    for _, r in base.iterrows():
        h = int(r["horizon_bars"])
        med_pip = float(r["median_pips"])
        for sc in scenarios:
            cost = sc.round_trip_pips
            ratio = med_pip / cost if cost > 0 else float("nan")
            req_sym = break_even_accuracy_symmetric(med_pip * pip_size, cost * pip_size)
            req_bar = break_even_accuracy_barrier(cost * pip_size, med_pip * pip_size,
                                                  k_up, k_dn)
            out_rows.append({
                "horizon_bars": h,
                "scenario": sc.name,
                "cost_pips": round(cost, 4),
                "median_move_pips": round(med_pip, 4),
                "mean_move_pips": round(float(r["mean_pips"]), 4),
                "move_to_cost_ratio": round(ratio, 4) if np.isfinite(ratio) else None,
                "p90_move_pips": round(float(r["p90_pips"]), 4),
                "required_acc_symmetric": round(req_sym, 4),
                "required_acc_barrier": round(req_bar, 4),
                "frac_up": round(float(r["frac_up"]), 4),
                "ret_mean_pips": round(float(r["ret_mean_pips"]), 4),
                "ret_std_pips": round(float(r["ret_std_pips"]), 4),
                "mfe_up_pips": round(float(r["mfe_up_pips"]), 4),
                "mae_up_pips": round(float(r["mae_up_pips"]), 4),
            })
    econ = pd.DataFrame(out_rows)

    # ---- Stability: per-year median move + per-year move-to-cost ----
    years = _year_of(bars)
    by_year = []
    for y in sorted(years.dropna().unique().tolist()):
        mask = (years == y).to_numpy()
        sub = bars.loc[mask].reset_index(drop=True)
        if len(sub) < 50:
            continue
        row = {"year": int(y), "n_bars": int(len(sub))}
        # only use scenarios[0] as reference (baseline spread) for ratio
        ref_cost = scenarios[0].round_trip_pips
        for h in horizons:
            st = forward_move_stats(sub, h, pip_size)
            row[f"h{h}_median_pips"] = round(st.median_pips, 3)
            row[f"h{h}_ratio"] = (round(st.median_pips / ref_cost, 3)
                                  if ref_cost > 0 else None)
        by_year.append(row)
    by_year_df = pd.DataFrame(by_year)

    # ---- Regime stability: per-vol-regime median move for first scenario ----
    reg = _vol_regimes(bars)
    by_regime = {}
    for label in ("LOW", "MID", "HIGH"):
        mask = (reg == label).to_numpy()
        sub = bars.loc[mask].reset_index(drop=True)
        if len(sub) < 50:
            by_regime[label] = {"n_bars": int(len(sub))}
            continue
        d = {"n_bars": int(len(sub))}
        ref_cost = scenarios[0].round_trip_pips
        for h in horizons:
            st = forward_move_stats(sub, h, pip_size)
            d[f"h{h}_median_pips"] = round(st.median_pips, 3)
            d[f"h{h}_ratio"] = (round(st.median_pips / ref_cost, 3)
                                if ref_cost > 0 else None)
        by_regime[label] = d

    return {
        "base_moves": base.to_dict("records"),
        "economics": econ.to_dict("records"),
        "stability_by_year": by_year_df.to_dict("records"),
        "stability_by_regime": by_regime,
        "n_horizons": len(horizons),
        "n_scenarios": len(scenarios),
    }
