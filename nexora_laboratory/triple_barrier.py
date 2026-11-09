"""FASE 2A - Triple-barrier labeling v2 (side-aware, executable, no leakage).

CORRECTION (review items 1-6). Key changes vs v1:

  1. EXECUTABLE bid/ask pricing. OHLC are treated as MID prices. An assumed
     half-spread (in price units) is applied to reconstruct tradable quotes:
         ask = mid + half_spread ; bid = mid - half_spread
     BUY : entry=ask, exit=bid
     SELL: entry=bid, exit=ask
     Barrier detection uses the EXECUTABLE EXIT-SIDE quote (what you can actually
     exit at), not mid. Results are SIMULATED EXECUTION (no historical bid/ask
     exists in the data; spread is an explicit assumption).

  2. SIDE-AWARE. side = +1 (BUY) or -1 (SELL). All gross/net returns follow the
     position direction. For a BUY the upper barrier is the profit target; for a
     SELL the lower barrier is the profit target. Barrier *touch* detection uses
     the exit-side executable price, so the same physical barrier means opposite
     things for BUY vs SELL.

  3. VERTICAL EXIT ECONOMICS. A vertical (time) exit yields the actual executable
     return of unwinding at that bar -- it can be a net profit or net loss. Raw
     barrier outcome is NEVER equated with profit/loss.

  4. EVENT STATUS kept distinct. Ambiguous is NOT converted into vertical exit.

  5. EVENT ATTRIBUTION. event_start_time / event_end_time stored so overlapping
     events can be purged and weighted downstream.

No look-ahead: ATR_t uses bars <= t; entry uses the next bar's quote; the outcome
window is strictly after entry; event_end_time >= entry_time > signal_time.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import numpy as np
import pandas as pd

# Event statuses (review item 4)
UPPER_HIT = "UPPER_HIT"
LOWER_HIT = "LOWER_HIT"
VERTICAL_EXIT = "VERTICAL_EXIT"
AMBIGUOUS = "AMBIGUOUS"
INVALID = "INVALID"


@dataclass(frozen=True)
class BarrierConfig:
    k_up: float = 1.5
    k_dn: float = 1.0
    vertical: int = 16
    atr_span: int = 14

    def as_dict(self) -> dict:
        return {"k_up": self.k_up, "k_dn": self.k_dn,
                "vertical": self.vertical, "atr_span": self.atr_span}


@dataclass(frozen=True)
class ExecutionConfig:
    """Simulated execution assumptions (review item 1)."""

    half_spread_price: float = 0.0   # price units added/subtracted per side
    entry_at_next_open: bool = True

    def as_dict(self) -> dict:
        return {"half_spread_price": self.half_spread_price,
                "entry_at_next_open": self.entry_at_next_open,
                "note": "SIMULATED EXECUTION; OHLC treated as mid; half_spread is an assumption"}


def atr_from_bars(df: pd.DataFrame, span: int = 14) -> pd.Series:
    """Trailing Wilder ATR using bars <= t (no look-ahead)."""
    h, l, c = df["high"], df["low"], df["close"]
    pc = c.shift(1)
    tr = pd.concat([(h - l), (h - pc).abs(), (l - pc).abs()], axis=1).max(axis=1)
    return tr.ewm(alpha=1.0 / span, adjust=False).mean()


def _profit_barrier_touched(exit_quote: float, upper: float, lower: float, side: int) -> bool:
    return exit_quote >= upper if side == 1 else exit_quote <= lower


def label_events(
    bars: pd.DataFrame,
    atr: pd.Series,
    cfg: BarrierConfig,
    exec_cfg: ExecutionConfig,
    side: int,
    m1: Optional[pd.DataFrame] = None,
) -> pd.DataFrame:
    """Triple-barrier labels for one position side.

    Parameters
    ----------
    side : +1 (BUY) or -1 (SELL). For BUY, upper=profit/lower=loss. For SELL,
        lower=profit/upper=loss. Barrier touch uses exit-side executable quote.
    exec_cfg : ExecutionConfig with assumed half-spread and entry timing.
        spread_already_in_prices is implied by price reconstruction.
    m1 : optional 1-minute bars ('ts','high','low') to resolve intrabar order.

    Returns columns:
        signal_time, entry_time, entry_price, exit_time, exit_price,
        event_start_time, event_end_time, atr, upper, lower, vertical_time,
        barrier_outcome, event_status, side, ambiguous, gross_return, exec_mid_gross_return
    """
    if side not in (1, -1):
        raise ValueError("side must be +1 (BUY) or -1 (SELL)")

    ts = bars["ts"].to_numpy()
    op = bars["open"].to_numpy(dtype=float)
    hi = bars["high"].to_numpy(dtype=float)  # mid highs
    lo = bars["low"].to_numpy(dtype=float)   # mid lows
    cl = bars["close"].to_numpy(dtype=float)  # mid closes
    atr_v = atr.to_numpy(dtype=float)
    n = len(bars)
    V = int(cfg.vertical)
    entry_shift = 1 if exec_cfg.entry_at_next_open else 0
    hs = float(exec_cfg.half_spread_price)

    # exit-side executable mid offset for barrier detection:
    #  - BUY exits at bid (mid - hs)
    #  - SELL exits at ask (mid + hs)
    exit_offset = -hs if side == 1 else +hs

    m1_by_bucket = None
    if m1 is not None and len(m1):
        m1b = m1.copy()
        m1b["bucket"] = m1b["ts"].dt.floor("30min")
        m1_by_bucket = {k: v[["high", "low"]].to_numpy(dtype=float)
                        for k, v in m1b.groupby("bucket")}

    rows = []
    for t in range(n):
        entry_idx = t + entry_shift
        if entry_idx >= n or (entry_idx + V) >= n:
            continue
        if not np.isfinite(atr_v[t]) or atr_v[t] <= 0:
            continue
        mid_entry = op[entry_idx] if exec_cfg.entry_at_next_open else cl[t]
        if not np.isfinite(mid_entry) or mid_entry <= 0:
            continue

        # executable entry quote
        entry_price = mid_entry + hs if side == 1 else mid_entry - hs
        # barriers are defined on the executable price using entry's own ATR
        upper = entry_price + cfg.k_up * atr_v[t]
        lower = entry_price - cfg.k_dn * atr_v[t]
        vert_idx = entry_idx + V

        status: Optional[str] = None
        exit_idx = vert_idx
        exit_price = None

        def exit_quote_at(idx: int, use_highlow: bool = False) -> float:
            # executable exit quote at a given bar (bar close, shifted by exit side)
            return cl[idx] + exit_offset

        for b in range(entry_idx, vert_idx + 1):
            # executable exit-side extremes for this bar
            if side == 1:   # exiting at bid -> bid high/low = mid high/low - hs
                ex_high = hi[b] - hs
                ex_low = lo[b] - hs
            else:           # exiting at ask -> ask high/low = mid high/low + hs
                ex_high = hi[b] + hs
                ex_low = lo[b] + hs

            # For BUY: profit=upper (price up -> bid up), loss=lower
            # For SELL: profit=lower (price down -> ask down), loss=upper
            if side == 1:
                hit_profit = ex_high >= upper
                hit_loss = ex_low <= lower
            else:
                hit_profit = ex_low <= lower
                hit_loss = ex_high >= upper

            if hit_profit and hit_loss:
                # resolve order with M1 (exit-side quotes)
                resolved = False
                if m1_by_bucket is not None:
                    key = pd.Timestamp(ts[b]).floor("30min")
                    arr = m1_by_bucket.get(key)
                    if arr is not None and len(arr) >= 1:
                        for mh, ml in arr:
                            eh = mh + exit_offset
                            el = ml + exit_offset
                            if side == 1:
                                p = eh >= upper
                                ls = el <= lower
                            else:
                                p = el <= lower
                                ls = eh >= upper
                            if p and not ls:
                                status, exit_idx, exit_price = UPPER_HIT if side == 1 else LOWER_HIT, b, (upper if side == 1 else lower)
                                resolved = True
                                break
                            if ls and not p:
                                status, exit_idx, exit_price = LOWER_HIT if side == 1 else UPPER_HIT, b, (lower if side == 1 else upper)
                                resolved = True
                                break
                            if p and ls:
                                break
                if resolved:
                    break
                status, exit_idx, exit_price = AMBIGUOUS, b, exit_quote_at(b)
                break
            if hit_profit:
                if side == 1:
                    status, exit_price = UPPER_HIT, upper
                else:
                    status, exit_price = LOWER_HIT, lower
                exit_idx = b
                break
            if hit_loss:
                if side == 1:
                    status, exit_price = LOWER_HIT, lower
                else:
                    status, exit_price = UPPER_HIT, upper
                exit_idx = b
                break
        else:
            status = VERTICAL_EXIT
            exit_price = exit_quote_at(vert_idx)

        if status is None:
            status = VERTICAL_EXIT
            exit_price = exit_quote_at(vert_idx)

        # gross return follows side: (exit - entry) * side / entry
        gross_return = side * (exit_price - entry_price) / entry_price

        # barrier_outcome: +1 if profit barrier reached, -1 if loss barrier, 0 vertical/ambiguous
        if status in (UPPER_HIT, LOWER_HIT):
            profit_status = UPPER_HIT if side == 1 else LOWER_HIT
            barrier_outcome = 1 if status == profit_status else -1
        else:
            barrier_outcome = 0

        # mid gross return (for reconciliation / cost double-count check)
        mid_exit = cl[exit_idx]
        mid_gross = side * (mid_exit - mid_entry) / mid_entry

        rows.append({
            "signal_time": ts[t],
            "entry_time": ts[entry_idx],
            "entry_price": float(entry_price),
            "exit_time": ts[exit_idx],
            "exit_price": float(exit_price),
            "event_start_time": ts[entry_idx],
            "event_end_time": ts[exit_idx],
            "atr": float(atr_v[t]),
            "upper": float(upper),
            "lower": float(lower),
            "vertical_time": ts[vert_idx],
            "barrier_outcome": int(barrier_outcome),
            "event_status": status,
            "side": int(side),
            "ambiguous": status == AMBIGUOUS,
            "gross_return": float(gross_return),
            "exec_mid_gross_return": float(mid_gross),
        })

    return pd.DataFrame(rows)


def label_summary(labels: pd.DataFrame) -> dict:
    if labels.empty:
        return {"n": 0}
    vc = labels["event_status"].value_counts().to_dict()
    n = int(len(labels))
    return {
        "n": n,
        "status_pct": {k: round(v / n * 100, 3) for k, v in vc.items()},
        "gross_mean_return": round(float(labels["gross_return"].mean()), 8),
        "gross_win_rate": round(float((labels["gross_return"] > 0).mean()), 4),
    }
