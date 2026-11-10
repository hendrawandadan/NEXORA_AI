"""Detect the intraday/daily granularity break inside a bar series.

EURUSD MT5 exports contain a DAILY-granularity prefix (2020) followed by true
intraday bars. Treating "h bars" across that break mixes 24-hour bars with
30-minute bars and corrupts any horizon analysis. This module locates the first
index at which the *dominant* bar spacing is established and stays established,
so downstream horizon work can run on the homogeneous segment only.

Pure, read-only. No look-ahead concerns (this is a data-quality measurement).
"""

from __future__ import annotations

from typing import Dict

import numpy as np
import pandas as pd


def granularity_break(bars: pd.DataFrame, expected_minutes: int) -> Dict[str, object]:
    """Return the first index where intraday cadence (delta <= expected*tol) holds.

    We define "intraday cadence established" as the first index ``i`` such that the
    bar-to-bar gap is <= ``expected_minutes * 1.5`` (i.e. an on-time intraday bar,
    tolerating a skipped session/night gap only up to 1.5x). Weekend gaps are larger
    and are NOT counted as intraday.

    The returned ``intraday_start_index`` is the first bar belonging to the
    homogeneous intraday segment. Everything before it (the daily prefix) is
    excluded from horizon statistics and reported separately.
    """
    if "ts" not in bars:
        raise ValueError("bars must have a 'ts' column (use load_bars)")
    delta_min = bars["ts"].diff().dt.total_seconds().div(60)
    tol = expected_minutes * 1.5
    on_time = delta_min.le(tol) & delta_min.gt(0)

    # First on-time intraday gap -> the bar just AFTER it starts the segment.
    hits = np.flatnonzero(on_time.to_numpy())
    if len(hits) == 0:
        first_i = 0
        has_break = False
    else:
        first_i = int(hits[0])  # index of the second bar of the first intraday step
        # The prefix is everything strictly before the FIRST bar of that gap.
        # bars[first_i-1] and bars[first_i] form the first intraday step; the
        # segment should start at first_i-1 to include that first intraday open.
        first_i = max(0, first_i - 1)
        has_break = first_i > 0

    prefix = bars.iloc[:first_i]
    segment = bars.iloc[first_i:]

    # Sanity: fraction of on-time deltas within the segment (should be high).
    dseg = segment["ts"].diff().dt.total_seconds().div(60)
    on_time_seg = (dseg.le(tol) & dseg.gt(0))
    frac_on_time = float(on_time_seg.mean()) if len(dseg.dropna()) else float("nan")

    return {
        "expected_minutes": int(expected_minutes),
        "has_daily_prefix": bool(has_break),
        "prefix_rows": int(len(prefix)),
        "prefix_first": str(prefix["ts"].iloc[0]) if len(prefix) else None,
        "prefix_last": str(prefix["ts"].iloc[-1]) if len(prefix) else None,
        "intraday_start_index": int(first_i),
        "intraday_first": str(segment["ts"].iloc[0]) if len(segment) else None,
        "intraday_last": str(segment["ts"].iloc[-1]) if len(segment) else None,
        "segment_rows": int(len(segment)),
        "segment_ontime_fraction": frac_on_time,
    }
