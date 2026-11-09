"""FASE 2A - Event attribution: net return, sample weights, overlap-aware purging.

CORRECTION (review items 3, 5, 6).

- ``net_return`` = gross_return (executable) - transaction cost fraction, using the
  ACTUAL entry price (no double counting; in executable mode spread is already in
  prices so only slippage/commission/swap are subtracted).
- ``meta_label`` = 1 if net_return > 0 else 0  (economic objective, not raw barrier).
- Event uniqueness: because label windows [event_start, event_end] overlap, we
  compute an average-uniqueness weight (Lopez de Prado style): for each bar, the
  number of events covering it; each event's uniqueness = mean(1/concurrency) over
  its own span. This is documented as ONE specific attribution method, not "done".
- Overlap-aware purging between splits: two events overlap if their
  [event_start, event_end] intervals intersect; overlapping train events are
  removed when they could share outcome info with a test/validation event.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from nexora_laboratory.cost_engine import (
    CostComponents,
    cost_fraction_from_pips,
)


def add_net_and_meta(
    labels: pd.DataFrame,
    comp: CostComponents,
    spread_already_in_prices: bool = True,
) -> pd.DataFrame:
    """Add transaction_cost (frac), net_return, meta_label to a label frame.

    In EXECUTABLE mode (default), spread is already embedded in the executable
    bid/ask prices, so only non-spread components are subtracted here.
    """
    out = labels.copy()
    pips = comp.total_pips(include_spread=not spread_already_in_prices)
    costs = np.array([
        cost_fraction_from_pips(pips, float(ep)) for ep in out["entry_price"].to_numpy()
    ])
    out["transaction_cost"] = costs
    out["net_return"] = out["gross_return"].to_numpy() - costs
    out["meta_label"] = (out["net_return"] > 0).astype(int)
    return out


def _overlap_matrix_intervals(starts: np.ndarray, ends: np.ndarray) -> np.ndarray:
    """Boolean pairwise overlap: row i overlaps col j if intervals intersect."""
    n = len(starts)
    lap = np.zeros((n, n), dtype=bool)
    for i in range(n):
        lap[i] = (starts <= ends[i]) & (ends >= starts[i])
    return lap


def average_uniqueness(labels: pd.DataFrame) -> pd.Series:
    """Average-uniqueness sample weights (Lopez de Prado attribution).

    concurrency[t] = # events whose [start,end] covers bar t; uniqueness of an
    event = mean(1/concurrency) across its span. Returned aligned to labels index.
    """
    starts = labels["event_start_time"].to_numpy()
    ends = labels["event_end_time"].to_numpy()
    # bar grid from min start to max end at 30-min resolution
    grid = pd.date_range(starts.min(), ends.max(), freq="30min")
    # event interval as closed bar range
    s_idx = np.searchsorted(grid.to_numpy(), starts, side="left")
    e_idx = np.searchsorted(grid.to_numpy(), ends, side="left")
    concurrency = np.zeros(len(grid), dtype=float)
    for s, e in zip(s_idx, e_idx):
        if e >= s:
            concurrency[s:e + 1] += 1.0
    concurrency = np.maximum(concurrency, 1.0)
    uniq = np.empty(len(labels), dtype=float)
    for i, (s, e) in enumerate(zip(s_idx, e_idx)):
        if e >= s:
            uniq[i] = float(np.mean(1.0 / concurrency[s:e + 1]))
        else:
            uniq[i] = 1.0
    return pd.Series(uniq, index=labels.index, name="uniqueness")


def purge_overlapping_between(train: pd.DataFrame, other: pd.DataFrame) -> pd.DataFrame:
    """Drop train events whose [start,end] overlaps ANY event in ``other``.

    Returns the purged train subset (overlap-aware purging for train vs val/test).
    """
    if train.empty or other.empty:
        return train
    ts = train["event_start_time"].to_numpy()
    te = train["event_end_time"].to_numpy()
    os_ = other["event_start_time"].to_numpy()
    oe = other["event_end_time"].to_numpy()
    keep = np.ones(len(train), dtype=bool)
    o_start_min, o_end_max = os_.min(), oe.max()
    for i in range(len(train)):
        # overlaps any other event?
        lap = (ts[i] <= oe) & (te[i] >= os_)
        if lap.any():
            keep[i] = False
    return train.loc[keep]
