"""Forward-move statistics for horizon discovery.

For a bar series and a set of horizons ``h`` (in bars), compute the distribution
of *forward* movement ``open[t+h] - open[t]`` (and, separately, the open[t+1]
entry convention used by the live model) so we can size break-even requirements.

Everything here is DESCRIPTIVE: the forward move is realized future data, used
ONLY to characterise how large a move is available per horizon — never to predict
and never as a model input. Horizon work does not train anything.

Also computes, for the same entry/exit geometry:
    - signed / absolute move distributions (P25/50/75/90/95)
    - positive vs negative move split
    - Maximum Favorable Excursion (MFE) and Maximum Adverse Excursion (MAE)
      for an UP and a DOWN position over the horizon window.

All money figures are in PRICE units and PIPS (pip_size supplied per instrument).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List

import numpy as np
import pandas as pd

_PCTS = (25, 50, 75, 90, 95)


@dataclass(frozen=True)
class MoveStats:
    horizon_bars: int
    n: int
    # absolute forward move (open[t] -> open[t+h]) in pips
    median_pips: float
    mean_pips: float
    p25_pips: float
    p50_pips: float
    p75_pips: float
    p90_pips: float
    p95_pips: float
    # signed move split
    frac_up: float
    mean_up_pips: float
    mean_down_pips: float  # magnitude of negative moves (positive number)
    # directional return distribution (signed)
    ret_mean_pips: float
    ret_std_pips: float
    # excursions over the window [t, t+h] (high/low based)
    mfe_up_pips: float      # best favorable for a long (median)
    mae_up_pips: float      # worst adverse for a long (median)
    mfe_down_pips: float    # best favorable for a short (median)
    mae_down_pips: float    # worst adverse for a short (median)

    def as_dict(self) -> Dict[str, object]:
        return self.__dict__.copy()


def _entry_exit_arrays(bars: pd.DataFrame, h: int, entry_shift: int = 0):
    """Return (entry_price, exit_price, fwd_high, fwd_low, valid_mask) arrays.

    entry_shift=0 -> entry at open[t], exit at open[t+h] (generic move).
    entry_shift=1 -> entry at open[t+1] (live convention), exit at open[t+1+h].
    """
    o = bars["open"].to_numpy(dtype=float)
    hi = bars["high"].to_numpy(dtype=float)
    lo = bars["low"].to_numpy(dtype=float)
    n = len(o)
    e = entry_shift
    end = n - h - e
    if end <= 0:
        empty = np.array([])
        return empty, empty, empty, empty, np.array([], dtype=bool)
    idx = np.arange(e, e + end)
    entry = o[idx]
    exit_ = o[idx + h]
    # forward extremes over (idx, idx+h] — up to and including the exit bar
    fwd_high = np.empty(len(idx))
    fwd_low = np.empty(len(idx))
    # vectorised rolling max/min over [i+1 .. i+h]
    for k in range(len(idx)):
        i = idx[k]
        win_hi = hi[i + 1:i + h + 1]
        win_lo = lo[i + 1:i + h + 1]
        fwd_high[k] = win_hi.max() if len(win_hi) else entry[k]
        fwd_low[k] = win_lo.min() if len(win_lo) else entry[k]
    valid = np.isfinite(entry) & np.isfinite(exit_)
    return entry, exit_, fwd_high, fwd_low, valid


def forward_move_stats(
    bars: pd.DataFrame, h: int, pip_size: float, entry_shift: int = 0
) -> MoveStats:
    """Compute MoveStats for horizon ``h`` (bars) using given pip_size."""
    entry, exit_, fwd_hi, fwd_lo, valid = _entry_exit_arrays(bars, h, entry_shift)
    if valid.sum() < 10:
        # degenerate
        z = float("nan")
        return MoveStats(h, int(valid.sum()), *([z] * 15))

    sig = (exit_ - entry)[valid] / pip_size              # signed move in pips
    absm = np.abs(sig)
    up = sig[sig > 0]
    down = sig[sig < 0]

    q = {p: float(np.percentile(absm, p)) for p in _PCTS}

    e = entry[valid]
    # excursions in pips (magnitudes)
    mfe_up = (fwd_hi[valid] - e) / pip_size      # best long excursion
    mae_up = (e - fwd_lo[valid]) / pip_size      # worst long excursion
    mfe_dn = (e - fwd_lo[valid]) / pip_size      # best short excursion
    mae_dn = (fwd_hi[valid] - e) / pip_size      # worst short excursion

    return MoveStats(
        horizon_bars=int(h),
        n=int(valid.sum()),
        median_pips=float(np.median(absm)),
        mean_pips=float(np.mean(absm)),
        p25_pips=q[25], p50_pips=q[50], p75_pips=q[75],
        p90_pips=q[90], p95_pips=q[95],
        frac_up=float(len(up) / len(sig)) if len(sig) else float("nan"),
        mean_up_pips=float(np.mean(up)) if len(up) else 0.0,
        mean_down_pips=float(-np.mean(down)) if len(down) else 0.0,
        ret_mean_pips=float(np.mean(sig)),
        ret_std_pips=float(np.std(sig)),
        mfe_up_pips=float(np.median(mfe_up)),
        mae_up_pips=float(np.median(mae_up)),
        mfe_down_pips=float(np.median(mfe_dn)),
        mae_down_pips=float(np.median(mae_dn)),
    )


def move_stats_table(
    bars: pd.DataFrame, horizons: List[int], pip_size: float, entry_shift: int = 0
) -> pd.DataFrame:
    rows = [forward_move_stats(bars, h, pip_size, entry_shift).as_dict()
            for h in horizons]
    return pd.DataFrame(rows)
