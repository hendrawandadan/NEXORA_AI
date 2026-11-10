"""STAGE 2 — Bar data quality metrics (pure, read-only).

Computes the quantitative quality fields required by Instrument Discovery:
missing-time coverage, duplicate timestamps, granularity break, spread sparsity,
and basic volatility/return descriptors. Reuses ``granularity_break`` so the
daily-prefix problem is reported consistently with STAGE 1.

No look-ahead: only describes the data, never predicts.
"""

from __future__ import annotations

from typing import Dict, Optional

import numpy as np
import pandas as pd

from .granularity import granularity_break


def _expected_count(ts: pd.Series, expected_minutes: int) -> int:
    """Approx expected bars between first and last ts at the given cadence (24/5 FX)."""
    if len(ts) < 2:
        return 0
    span_min = (ts.iloc[-1] - ts.iloc[0]).total_seconds() / 60.0
    if span_min <= 0 or expected_minutes <= 0:
        return 0
    # FX trades ~5 days/week -> ~ (5/7) of calendar minutes are 'market open'.
    market_minutes = span_min * (5.0 / 7.0)
    return int(market_minutes // expected_minutes)


def bar_quality(bars: pd.DataFrame, expected_minutes: int) -> Dict[str, object]:
    """Return a dict of quality metrics for a bar frame (already loaded)."""
    if "ts" not in bars:
        raise ValueError("bars must have 'ts' column (load with load_bars)")

    n = len(bars)
    # duplicates / monotonicity (load_bars dedups, but verify raw here)
    n_dup_ts = int(bars["ts"].duplicated().sum())
    is_sorted = bool(bars["ts"].is_monotonic_increasing)

    # granularity
    brk = granularity_break(bars, expected_minutes)

    # missing coverage on the intraday segment (avoid the daily-prefix distortion)
    seg = bars.iloc[brk["intraday_start_index"]:].reset_index(drop=True)
    seg_ts = seg["ts"]
    expected = _expected_count(seg_ts, expected_minutes)
    missing_frac = None
    if expected > 0:
        missing_frac = round(max(0.0, 1.0 - len(seg) / expected), 4)

    # spread sparsity (only if a 'spread' column exists)
    spread_stats: Dict[str, object] = {"available": False}
    if "spread" in bars.columns:
        sp = pd.to_numeric(bars["spread"], errors="coerce")
        valid = sp.dropna()
        if len(valid):
            zero_frac = float((valid == 0).mean())
            nonzero = valid[valid > 0]
            spread_stats = {
                "available": True,
                "n": int(len(valid)),
                "pct_zero": round(zero_frac, 4),
                "median_nonzero": float(nonzero.median()) if len(nonzero) else None,
                "mean": float(valid.mean()),
                "reliable": bool(zero_frac < 0.5),
            }

    # return/volatility descriptors on close
    close = pd.to_numeric(seg["close"], errors="coerce")
    ret = close.pct_change().dropna()
    vol = {
        "n_returns": int(len(ret)),
        "std_pct": float(ret.std() * 100.0) if len(ret) else None,
        "mean_pct": float(ret.mean() * 100.0) if len(ret) else None,
        "abs_mean_pct": float(ret.abs().mean() * 100.0) if len(ret) else None,
    }

    return {
        "n_bars": int(n),
        "n_duplicate_ts": n_dup_ts,
        "is_sorted": is_sorted,
        "first_ts": str(bars["ts"].iloc[0]),
        "last_ts": str(bars["ts"].iloc[-1]),
        "granularity": brk,
        "intraday_rows": int(brk["segment_rows"]),
        "expected_rows_est": int(expected),
        "missing_frac_est": missing_frac,
        "spread": spread_stats,
        "volatility": vol,
    }


def quality_score(metrics: Dict[str, object]) -> Dict[str, object]:
    """Compute a simple 0..1 data-quality score + component flags.

    Transparent, rule-based (no black box). Starts at 1.0 and deducts penalties
    for: duplicates, granularity break, high missing, unreliable spread.
    """
    score = 1.0
    notes = []

    gran = metrics.get("granularity", {})
    if gran.get("has_daily_prefix"):
        score -= 0.15
        notes.append("daily-prefix present (excluded from stats)")

    miss = metrics.get("missing_frac_est")
    if isinstance(miss, (int, float)):
        if miss > 0.25:
            score -= 0.30
            notes.append(f"high missing {miss:.2f}")
        elif miss > 0.10:
            score -= 0.15
            notes.append(f"moderate missing {miss:.2f}")

    if metrics.get("n_duplicate_ts", 0) > 0:
        score -= 0.10
        notes.append("duplicate timestamps")

    sp = metrics.get("spread", {})
    if sp.get("available"):
        if not sp.get("reliable", True):
            score -= 0.20
            notes.append("spread column unreliable (mostly zero)")
    else:
        notes.append("no spread column in bars (spread = tick-derived or estimate)")

    score = max(0.0, min(1.0, round(score, 3)))
    grade = "A" if score >= 0.85 else "B" if score >= 0.70 else "C" if score >= 0.50 else "D"
    return {"score": score, "grade": grade, "notes": notes}
