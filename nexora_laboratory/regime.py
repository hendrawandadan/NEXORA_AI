"""Trailing volatility regime segmentation (FASE 2A, leakage-safe).

Classifies each bar t into a volatility regime using ONLY information available at
or before t (trailing realized volatility ranked against its own trailing history).
This is used ONLY to bucket out-of-sample events for the per-regime robustness
check in the ATR-vs-adaptive experiment; it never feeds a barrier prediction.

Definition (no look-ahead):
    rv_t      = trailing realized volatility (std of log returns over `window`)
    pct_t     = percentile rank of rv_t within a trailing `lookback` window
    regime_t  = "calm"  if pct_t <= lo_q
                "high"  if pct_t >= hi_q
                "mid"   otherwise

Because pct_t uses [t-lookback+1 .. t] only, regime_t is known at signal time.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

CALM = "calm"
MID = "mid"
HIGH = "high"


@dataclass(frozen=True)
class RegimeConfig:
    window: int = 96        # ~2 days of M30 for realized vol
    lookback: int = 96 * 20  # ~40 days for the ranking window
    lo_q: float = 0.33
    hi_q: float = 0.67

    def as_dict(self) -> dict:
        return {"window": self.window, "lookback": self.lookback,
                "lo_q": self.lo_q, "hi_q": self.hi_q}


def trailing_regime(bars: pd.DataFrame, cfg: RegimeConfig = RegimeConfig()) -> pd.Series:
    """Per-bar regime label from trailing realized vol percentile (<= t only)."""
    close = bars["close"].to_numpy(dtype=float)
    logret = np.diff(np.log(close), prepend=np.nan)
    lr = pd.Series(logret)
    rv = lr.rolling(cfg.window, min_periods=cfg.window).std()
    # percentile rank of the current rv within its trailing lookback window
    span = max(int(cfg.lookback), int(cfg.window) + 1)

    def _pct(arr: np.ndarray) -> float:
        cur = arr[-1]
        valid = arr[np.isfinite(arr)]
        if not np.isfinite(cur) or len(valid) < cfg.window:
            return np.nan
        return float((valid <= cur).mean())

    pct = rv.rolling(span, min_periods=cfg.window).apply(_pct, raw=True)
    out = pd.Series(MID, index=bars.index, dtype=object)
    out[pct <= cfg.lo_q] = CALM
    out[pct >= cfg.hi_q] = HIGH
    out[pct.isna()] = None
    return out
