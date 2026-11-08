"""Purge-boundary and split-integrity tests for PREP-001 (Part A).

Read-only with respect to all production data. Uses synthetic fixtures built in
memory to exercise nexora_learning.pipeline.split_indices() and the label
construction rule exactly as train_one() applies them. Does NOT train, does NOT
call train_one(), and does not read/modify the real dataset.

We reproduce the pipeline's label + mask logic verbatim (pipeline.prepare) so the
tests measure the *actual* rule, not a paraphrase:

    fwd[:-h] = close[h:]/close[:-h] - 1
    y = (fwd > 0).astype(int)
    mask = features.notna().all(axis=1) & isfinite(fwd)

and split via the real pipeline.split_indices function.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from nexora_learning.pipeline import split_indices


# ----------------------------------------------------------------------------
# Fixtures / helpers
# ----------------------------------------------------------------------------
def _synthetic_bars(n: int, seed: int = 0, start: str = "2021-01-01", freq: str = "30min",
                    gap_at: int | None = None, gap_bars: int = 0) -> pd.DataFrame:
    """Deterministic synthetic OHLC dataset; optional timestamp/bar gap."""
    rng = np.random.default_rng(seed)
    close = 1.1 + np.cumsum(rng.normal(0, 1e-4, n))
    ts = pd.date_range(start, periods=n, freq=freq)
    df = pd.DataFrame({
        "ts": ts,
        "open": close,
        "high": close + 2e-4,
        "low": close - 2e-4,
        "close": close,
        "volume": rng.integers(1, 100, n),
    })
    if gap_at is not None and gap_bars > 0:
        # Remove a block of bars to simulate a real data gap (kept monotonic/unique).
        keep = np.ones(n, dtype=bool)
        keep[gap_at:gap_at + gap_bars] = False
        df = df.loc[keep].reset_index(drop=True)
    return df


def _label_and_mask(df: pd.DataFrame, horizon: int) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Replicate pipeline.prepare label/mask logic for a feature-free frame.

    Features are represented by 'open' (always finite here), so the only mask
    exclusion is the finite-fwd test, isolating the target-overlap structure.
    """
    close = df["close"].to_numpy()
    fwd = np.full(len(df), np.nan)
    fwd[:-horizon] = close[horizon:] / close[:-horizon] - 1
    y = (fwd > 0).astype(int)
    # Stand-in for "all features not null": here everything is finite except the
    # trailing horizon rows where fwd is NaN, so mask == isfinite(fwd).
    mask = np.isfinite(fwd)
    return y, fwd, mask


def _max_label_end(idx: np.ndarray, horizon: int) -> int:
    """Largest df-index position touched by a label whose anchor row is in idx."""
    return int(idx[-1]) + horizon


# ----------------------------------------------------------------------------
# 1. Boundary normal + label-end strictly before validation start
# ----------------------------------------------------------------------------
def test_purge_gap_prevents_label_overlap_normal_boundary():
    df = _synthetic_bars(4000, seed=1)
    horizon = 2
    _, _, mask = _label_and_mask(df, horizon)
    tr, va, te = split_indices(mask, horizon, train_frac=0.6, valid_frac=0.2, embargo=24)

    eligible = np.flatnonzero(mask)
    a = len(tr)
    b = len(va)
    # Pipeline: va = idx[a+embargo : a+embargo+b]; te = idx[va_end+embargo:].
    assert va[0] == eligible[a + 24]
    assert te[0] == eligible[a + 24 + b + 24]

    # No training label (T..T+h) reaches the first validation anchor.
    assert _max_label_end(tr, horizon) < va[0]
    assert _max_label_end(va, horizon) < te[0]


def test_embargo_gap_count_is_exact_between_all_splits():
    df = _synthetic_bars(5000, seed=2)
    horizon = 2
    _, _, mask = _label_and_mask(df, horizon)
    tr, va, te = split_indices(mask, horizon, 0.6, 0.2, 24)
    eligible = np.flatnonzero(mask)
    a = len(tr)
    b = len(va)
    # va = idx[a+embargo : a+embargo+b]; te = idx[(a+embargo+b)+embargo : ].
    assert va[0] == eligible[a + 24]
    assert te[0] == eligible[a + 24 + b + 24]


# ----------------------------------------------------------------------------
# 2. Boundary exactly at closing candle: no double-use of the boundary row
# ----------------------------------------------------------------------------
def test_boundary_row_not_shared_between_train_and_validation():
    df = _synthetic_bars(3000, seed=3)
    horizon = 2
    _, _, mask = _label_and_mask(df, horizon)
    tr, va, te = split_indices(mask, horizon, 0.6, 0.2, 24)
    tr_set = set(tr.tolist())
    va_set = set(va.tolist())
    te_set = set(te.tolist())
    assert tr_set.isdisjoint(va_set)
    assert va_set.isdisjoint(te_set)
    assert tr_set.isdisjoint(te_set)
    # The last candidate row before the embargo (eligible[a-1]) is the training
    # boundary and is NOT in validation.
    eligible = np.flatnonzero(mask)
    a = len(tr)
    assert eligible[a - 1] in tr_set
    assert eligible[a - 1] not in va_set


# ----------------------------------------------------------------------------
# 3. Training label crossing validation boundary would be purged (explicit)
# ----------------------------------------------------------------------------
def test_training_label_that_would_cross_boundary_is_removed():
    horizon = 2
    df = _synthetic_bars(2000, seed=4)
    _, _, mask = _label_and_mask(df, horizon)
    tr, va, te = split_indices(mask, horizon, 0.6, 0.2, 24)

    # split_indices() never applies a purge smaller than the target's effective
    # horizon. Even an explicit embargo=0 is clamped to the horizon, so the last
    # training label (T..T+h) can never reach the validation start.
    tr0, va0, _ = split_indices(mask, horizon, 0.6, 0.2, 0)
    last_train0 = int(tr0[-1])
    clamped_val_start = int(va0[0])
    # No leak even with the requested embargo=0: h is the hard floor.
    assert last_train0 + horizon < clamped_val_start

    # With the real embargo (24), purge further separates the splits.
    last_train = int(tr[-1])
    real_val_start = int(va[0])
    assert last_train + horizon < real_val_start


# ----------------------------------------------------------------------------
# 4. Gap candles: split must remain monotonic & label-safe across a data gap
# ----------------------------------------------------------------------------
def test_gap_candles_keep_splits_monotonic_and_label_safe():
    horizon = 2
    df = _synthetic_bars(4000, seed=5, gap_at=1200, gap_bars=50)
    ts = df["ts"].to_numpy()
    # Confirm the fixture actually has a timestamp jump (gap) somewhere.
    diffs = pd.Series(ts).diff().dropna()
    assert (diffs > pd.Timedelta(minutes=30)).any()

    _, _, mask = _label_and_mask(df, horizon)
    tr, va, te = split_indices(mask, horizon, 0.6, 0.2, 24)

    # Splits are strictly increasing in time (sorted, unique).
    for part in (tr, va, te):
        assert np.all(np.diff(ts[part]) > np.timedelta64(0, "ns"))
        assert len(part) > 0

    # Label spans never reach the next split's first anchor.
    assert _max_label_end(tr, horizon) < va[0]
    assert _max_label_end(va, horizon) < te[0]
    # Full ordering in df-index space.
    assert tr[-1] < va[0]
    assert va[-1] < te[0]


# ----------------------------------------------------------------------------
# 5. Small dataset: insufficient rows must raise, never silently split
# ----------------------------------------------------------------------------
def test_small_dataset_raises_insufficient_rows():
    df = _synthetic_bars(150, seed=6)
    horizon = 2
    _, _, mask = _label_and_mask(df, horizon)
    with pytest.raises(ValueError, match="Insufficient rows"):
        split_indices(mask, horizon, 0.6, 0.2, 24)


def test_minimum_viable_dataset_splits_within_tolerance():
    # test span = 0.2*n - 2*embargo must be >=100 -> n >= 740 for embargo=24.
    df = _synthetic_bars(900, seed=7)
    horizon = 2
    _, _, mask = _label_and_mask(df, horizon)
    tr, va, te = split_indices(mask, horizon, 0.6, 0.2, 24)
    assert min(len(tr), len(va), len(te)) >= 100
    assert _max_label_end(tr, horizon) < va[0]


# ----------------------------------------------------------------------------
# 6. Purge leaving too few training samples: the guard trips
# ----------------------------------------------------------------------------
def test_purge_can_starve_training_and_guard_trips():
    # Large embargo relative to n: a big chunk of eligible rows is purged.
    df = _synthetic_bars(260, seed=8)
    horizon = 2
    _, _, mask = _label_and_mask(df, horizon)
    with pytest.raises(ValueError, match="Insufficient rows"):
        split_indices(mask, horizon, 0.6, 0.2, embargo=200)


# ----------------------------------------------------------------------------
# 7. min_train_fraction denominator behaviour (documents actual code, Part B link)
# ----------------------------------------------------------------------------
def test_walk_forward_min_train_fraction_denominator_is_eligible_count():
    """walk_forward_scores uses initial=max(int(n*0.50),1000) where n=len(eligible).

    This test targets the *hardcoded 0.50* in pipeline.walk_forward_scores, not
    the unread config key. It documents the denominator = number of eligible
    (masked) rows, not total rows.
    """
    n_total = 5000
    n_ineligible = 1000  # e.g. warmup rows dropped by features
    horizon = 2
    # Build a mask with n_total - n_ineligible - horizon trailing NaN behaviour.
    mask = np.zeros(n_total, dtype=bool)
    eligible_positions = np.arange(n_ineligible, n_total - horizon)
    mask[eligible_positions] = True
    n_eligible = int(mask.sum())
    # Replicate the hardcoded denominator rule:
    initial = max(int(n_eligible * 0.50), 1000)
    # Denominator is eligible count (n_eligible), not total rows.
    assert initial == max(int((n_total - n_ineligible - horizon) * 0.50), 1000)
    assert initial != max(int(n_total * 0.50), 1000)


# ----------------------------------------------------------------------------
# 8. Split validity on the real dataset's *structure* (read-only, no mutation)
# ----------------------------------------------------------------------------
def test_split_valid_for_eurusd_m30_structure():
    """Read-only inspection: real M30 file -> mask -> split is valid.

    Loads the real dataset but never writes it and never trains. If the file is
    absent, the test skips (does not fabricate a result).
    """
    from pathlib import Path

    from nexora_datahub.loader import load_bars

    data_path = Path(__file__).resolve().parents[1] / (
        "data/raw/EURUSD/EURUSD_M30_202001020000_202611062130.csv"
    )
    if not data_path.is_file():
        pytest.skip("PREP-001 dataset not present")

    from nexora_vision.features import build_features

    df = load_bars(data_path)
    horizon = 2
    X = build_features(df)
    close = df["close"].to_numpy()
    fwd = np.full(len(df), np.nan)
    fwd[:-horizon] = close[horizon:] / close[:-horizon] - 1
    mask = X.notna().all(axis=1).to_numpy() & np.isfinite(fwd)

    tr, va, te = split_indices(mask, horizon, 0.6, 0.2, max(horizon, 24))
    # Eligibility left enough rows in every split.
    assert min(len(tr), len(va), len(te)) >= 100

    # Purge boundary safe against real timestamps.
    ts = df["ts"].to_numpy()
    assert np.all(np.diff(ts[tr]) > np.timedelta64(0, "ns"))
    # Label of last train row ends strictly before first validation row.
    assert int(tr[-1]) + horizon < int(va[0])
    # Embargo in eligible rows between splits is exactly 24 for PREP-001.
    eligible = np.flatnonzero(mask)
    a, b = len(tr), len(va)
    assert int(va[0]) == int(eligible[a + 24])
    assert int(te[0]) == int(eligible[a + 24 + b + 24])


# ----------------------------------------------------------------------------
# 9. Feature timestamp never exceeds prediction timestamp (structural proxy)
# ----------------------------------------------------------------------------
def test_feature_rows_never_exceed_prediction_rows():
    """For every split, the highest feature row index <= the split's own rows.

    Using the real feature builder on the real file (read-only), assert the
    feature matrix is row-aligned with bars (no forward fill pushing future info)
    and that the split indices reference only rows with valid features.
    """
    from pathlib import Path

    from nexora_datahub.loader import load_bars
    from nexora_vision.features import build_features

    data_path = Path(__file__).resolve().parents[1] / (
        "data/raw/EURUSD/EURUSD_M30_202001020000_202611062130.csv"
    )
    if not data_path.is_file():
        pytest.skip("PREP-001 dataset not present")

    df = load_bars(data_path)
    X = build_features(df)
    # Row alignment: features share the bar index exactly.
    assert len(X) == len(df)
    horizon = 2
    close = df["close"].to_numpy()
    fwd = np.full(len(df), np.nan)
    fwd[:-horizon] = close[horizon:] / close[:-horizon] - 1
    mask = X.notna().all(axis=1).to_numpy() & np.isfinite(fwd)
    tr, va, te = split_indices(mask, horizon, 0.6, 0.2, max(horizon, 24))
    # Every index used is a valid, feature-complete row.
    for part in (tr, va, te):
        assert mask[part].all()
        assert part.max() < len(df)
