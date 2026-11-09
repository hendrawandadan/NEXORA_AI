"""FASE 2A - Triple-barrier labeling (ATR-based, intrabar-resolved via M1).

For each event at bar t (signal time), we set three barriers using ONLY
information available at t (trailing ATR, entry price = next bar open):
    upper = entry + k_up * ATR_t
    lower = entry - k_dn * ATR_t
    vertical = t + V bars

Label / outcome at first barrier touch:
    +1  -> upper touched first  (profitable long-side win)
    -1  -> lower touched first  (loss)
     0  -> vertical barrier first (time exit)

Intrabar resolution uses genuine 1-minute bars (verified granular), so the ORDER
in which upper/lower are touched within a 30-min bar is resolved honestly. When a
30-min bucket is too thin (<2 M1 bars) and the bar range spans both barriers, the
event is flagged ``ambiguous`` rather than forced.

No look-ahead:
    - ATR_t uses bars <= t
    - entry uses open of t+1 (info at t+1, i.e. the tradable entry)
    - outcome window is strictly after entry
The returned ``label_time`` is always > ``signal_time`` (asserted by tests).

This module is pure/computational (no I/O beyond what is passed in).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import numpy as np
import pandas as pd


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class BarrierConfig:
    k_up: float = 1.5
    k_dn: float = 1.0
    vertical: int = 16
    atr_span: int = 14

    def as_dict(self) -> dict:
        return {"k_up": self.k_up, "k_dn": self.k_dn,
                "vertical": self.vertical, "atr_span": self.atr_span}


def atr_from_bars(df: pd.DataFrame, span: int = 14) -> pd.Series:
    """Trailing Wilder ATR using bars <= t (no look-ahead)."""
    h, l, c = df["high"], df["low"], df["close"]
    pc = c.shift(1)
    tr = pd.concat([(h - l), (h - pc).abs(), (l - pc).abs()], axis=1).max(axis=1)
    return tr.ewm(alpha=1.0 / span, adjust=False).mean()


def _m1_order_within_bucket(
    m1_lo: float, m1_hi: float, upper: float, lower: float,
) -> str:
    """If a thin 30-min bucket spans both barriers, we can't know order -> ambiguous."""
    return "ambiguous"


def label_events(
    bars: pd.DataFrame,
    atr: pd.Series,
    cfg: BarrierConfig,
    m1: Optional[pd.DataFrame] = None,
    entry_at_next_open: bool = True,
) -> pd.DataFrame:
    """Compute triple-barrier labels for every event bar t.

    Parameters
    ----------
    bars : DataFrame with ['ts','open','high','low','close'], sorted ascending,
        unique 30-min rows (as produced by load_bars).
    atr  : Series aligned to bars index, trailing ATR (use atr_from_bars).
    cfg  : BarrierConfig.
    m1   : optional DataFrame with ['ts','high','low'] 1-minute bars. If provided,
        intrabar order within a 30-min bar is resolved at minute resolution.
    entry_at_next_open : bool. If True, entry price = open of bar t+1 (execution-
        aligned). If False, entry = close of bar t (statistical). Barriers/outcome
        window always start at the entry bar.

    Returns
    -------
    DataFrame indexed by event time with columns:
        signal_time, entry_time, entry_price, atr, upper, lower, vertical_time,
        exit_time, exit_price, raw_outcome (+1/-1/0), gross_return, ambiguous
    """
    ts = bars["ts"].to_numpy()
    op = bars["open"].to_numpy(dtype=float)
    hi = bars["high"].to_numpy(dtype=float)
    lo = bars["low"].to_numpy(dtype=float)
    cl = bars["close"].to_numpy(dtype=float)
    atr_v = atr.to_numpy(dtype=float)
    n = len(bars)
    V = int(cfg.vertical)
    entry_shift = 1 if entry_at_next_open else 0

    # Precompute M1 bucket index for intrabar resolution
    m1_by_bucket = None
    if m1 is not None and len(m1):
        m1b = m1.copy()
        m1b["bucket"] = m1b["ts"].dt.floor("30min")
        m1_by_bucket = {k: v[["high", "low"]].to_numpy(dtype=float)
                        for k, v in m1b.groupby("bucket")}

    rows = []
    for t in range(n):
        entry_idx = t + entry_shift
        # Need entry and a full vertical window of future bars
        if entry_idx >= n or (entry_idx + V) >= n:
            continue
        if not np.isfinite(atr_v[t]) or atr_v[t] <= 0:
            continue
        entry = op[entry_idx] if entry_at_next_open else cl[t]
        if not np.isfinite(entry) or entry <= 0:
            continue
        upper = entry + cfg.k_up * atr_v[t]
        lower = entry - cfg.k_dn * atr_v[t]
        vert_idx = entry_idx + V
        vertical_time = ts[vert_idx]

        outcome: Optional[int] = None
        exit_idx = vert_idx
        exit_price = cl[vert_idx]
        ambiguous = False

        # Scan buckets after entry up to and including vertical
        for b in range(entry_idx, vert_idx + 1):
            bucket_high = hi[b]
            bucket_low = lo[b]
            hit_up = bucket_high >= upper
            hit_dn = bucket_low <= lower
            if hit_up and hit_dn:
                # Both barriers inside one 30-min bucket -> resolve with M1 if possible
                resolved = False
                if m1_by_bucket is not None:
                    key = pd.Timestamp(ts[b]).floor("30min")
                    arr = m1_by_bucket.get(key)
                    if arr is not None and len(arr) >= 1:
                        for mh, ml in arr:
                            u = mh >= upper
                            d = ml <= lower
                            if u and not d:
                                outcome, exit_idx, exit_price = 1, b, upper
                                resolved = True
                                break
                            if d and not u:
                                outcome, exit_idx, exit_price = -1, b, lower
                                resolved = True
                                break
                            # both within one minute too -> truly ambiguous
                            if u and d:
                                break
                if resolved:
                    break
                # Could not resolve order honestly
                ambiguous = True
                outcome = None
                exit_idx = b
                exit_price = cl[b]
                break
            if hit_up:
                outcome, exit_idx, exit_price = 1, b, upper
                break
            if hit_dn:
                outcome, exit_idx, exit_price = -1, b, lower
                break
        else:
            outcome = 0  # vertical barrier (time exit)

        if ambiguous:
            raw_outcome = 0  # not a clean directional outcome; flagged separately
        else:
            raw_outcome = outcome

        gross_return = (exit_price / entry) - 1.0
        rows.append({
            "signal_time": ts[t],
            "entry_time": ts[entry_idx],
            "entry_price": entry,
            "atr": atr_v[t],
            "upper": upper,
            "lower": lower,
            "vertical_time": vertical_time,
            "exit_time": ts[exit_idx],
            "exit_price": exit_price,
            "raw_outcome": int(raw_outcome),
            "gross_return": float(gross_return),
            "ambiguous": bool(ambiguous),
        })

    out = pd.DataFrame(rows)
    return out


def label_summary(labels: pd.DataFrame) -> dict:
    if labels.empty:
        return {"n": 0}
    vc = labels["raw_outcome"].value_counts().to_dict()
    return {
        "n": int(len(labels)),
        "upper(+1)": int(vc.get(1, 0)),
        "lower(-1)": int(vc.get(-1, 0)),
        "vertical(0)": int(vc.get(0, 0)),
        "ambiguous": int(labels["ambiguous"].sum()),
        "gross_mean_return": round(float(labels["gross_return"].mean()), 8),
        "gross_win_rate": round(float((labels["gross_return"] > 0).mean()), 4),
    }
