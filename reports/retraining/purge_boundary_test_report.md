# NEXORA AI v2 — Purge Boundary Test Report (Part A)

Audit timestamp: 2026-11-07
Test module: `tests/test_purge_boundary.py`
Mode: read-only. Synthetic in-memory fixtures + read-only inspection of the real dataset.
**No training. No `train_one()`. Real CSV/dataset/model/backup/config untouched.**
Related: `execution_timing_contract.md` (Part B timing contract), `walk_forward_reconciliation_report.md`.

Result: **11 passed** (part of full suite **136 passed**).

---

## 1. Implementation audit (what the code actually does)

### 1.1 Split — `nexora_learning/pipeline.py::split_indices`
```python
def split_indices(mask, horizon, train_frac=.6, valid_frac=.2, embargo=None):
    if embargo is None: embargo = horizon
    idx = np.flatnonzero(mask); n = len(idx)
    a = int(n*train_frac); b = int(n*valid_frac)
    va_start = a + embargo
    va_end   = va_start + b
    tr = idx[:a]
    va = idx[va_start:va_end]
    te = idx[va_end+embargo:]
    if min(len(tr),len(va),len(te)) < 100:
        raise ValueError("Insufficient rows after split/embargo")
    return tr, va, te
```
- `idx` = df-index positions of **eligible** rows (mask = finite fwd AND all features non-null).
- `train` = first `a` eligible rows.
- `validation` = eligible rows `[a+embargo : a+embargo+b]`.
- `test` = eligible rows from `(a+embargo+b)+embargo` to end.
- **Purge** = `embargo` *eligible rows* between consecutive split windows (train→val and val→test).
- Production call: `split_indices(mask, h, 0.6, 0.2, max(horizon, cfg["embargo_bars"]))` →
  PREP-001 `embargo = max(2, 24) = 24`.

### 1.2 Training / validation window
Chronological holdout: `train=0.6`, `validation=0.2`, `test=remainder` of **eligible** rows, separated by
`embargo` eligible rows each side.

### 1.3 Prediction horizon & label — `pipeline.prepare`
```python
close = df.close.to_numpy(); fwd = np.full(len(df), np.nan)
fwd[:-horizon] = close[horizon:]/close[:-horizon] - 1
y = (fwd > 0).astype(int)
mask = X.notna().all(axis=1).to_numpy() & np.isfinite(fwd)
```
- Label at bar `t` uses `close[t+h]/close[t]-1` → information from bar `t+h`.
- The last `h` rows have `NaN` fwd → masked out. Label never used as a feature.

### 1.4 Feature calculation — `nexora_vision/features.py`
Only trailing operators (`.shift(k)` k>0, `.rolling(n)`, `.ewm(...)` back-looking). Feature row for bar `t`
uses bars ≤ `t`. (Proven separately in `test_features_have_no_future_dependency`.)

### 1.5 `min_train_fraction`
- Pipeline walk-forward uses `initial = max(int(n*.50), 1000)` — **hardcoded 0.50**, `n = len(eligible)`.
- Config key `walk_forward.min_train_fraction = 0.5` is **not read anywhere in code**.
- This is detailed in `walk_forward_reconciliation_report.md`.

---

## 2. Test cases and what each proves

| # | Test | Proves |
|---|---|---|
| 1 | `test_purge_gap_prevents_label_overlap_normal_boundary` | Normal boundary: `va[0]==eligible[a+embargo]`, `te[0]==eligible[a+embargo+b+embargo]`; last train label end `< va[0]`; last val label end `< te[0]`. |
| 2 | `test_embargo_gap_count_is_exact_between_all_splits` | Exactly `embargo` eligible rows purged between every pair of splits. |
| 3 | `test_boundary_row_not_shared_between_train_and_validation` | Splits are mutually disjoint; the boundary row is train-only (boundary at closing candle). |
| 4 | `test_training_label_that_would_cross_boundary_is_removed` | With `embargo=0` a train label overlaps naive val start (leak demonstrated); with real embargo it is purged. |
| 5 | `test_gap_candles_keep_splits_monotonic_and_label_safe` | With a real data gap, splits stay strictly monotonic in time and labels never cross the next split. |
| 6 | `test_small_dataset_raises_insufficient_rows` | Small dataset → `ValueError("Insufficient rows…")`, never a silent bad split. |
| 7 | `test_minimum_viable_dataset_splits_within_tolerance` | Minimum viable size yields ≥100 rows per split and a safe boundary. |
| 8 | `test_purge_can_starve_training_and_guard_trips` | Oversized embargo that starves training is caught by the guard. |
| 9 | `test_walk_forward_min_train_fraction_denominator_is_eligible_count` | Denominator is eligible-row count (not total rows); documents the hardcoded 0.50. |
| 10 | `test_split_valid_for_eurusd_m30_structure` | On the real PREP-001 file (read-only): splits valid, monotonic, embargo=24 exact, label-safe. |
| 11 | `test_feature_rows_never_exceed_prediction_rows` | Feature matrix row-aligned with bars; every split index is a feature-complete row. |

### 2.1 Required cases coverage
- **Boundary normal** → #1.
- **Boundary exactly at closing candle** → #3 (boundary row belongs to train only, disjointness).
- **Training label crossing validation** → #4 (leak shown for embargo=0; removed with real embargo).
- **Gap candle** → #5 (synthetic 50-bar gap; monotonic + label-safe).
- **Small dataset** → #6.
- **Purge leaves too few training samples** → #8 (and #6).

---

## 3. Key assertions (structure, not paraphrased)

For every split the tests assert, in **df-index space**:
```
max(idx_train) + horizon  <  first(idx_validation)
max(idx_validation) + horizon  <  first(idx_test)
va[0] == eligible[a + embargo]
te[0] == eligible[a + embargo + b + embargo]
```
and mutual disjointness of the three index sets. Because `embargo (24) ≥ horizon (2)`, the number of eligible
rows between splits (24) always exceeds the label reach (2), so no training label can touch a validation anchor.

### 3.1 Real-data verification (PREP-001)
Read-only load of `EURUSD_M30_202001020000_202611062130.csv`:
- `len(features) == len(bars)` (row-aligned).
- `min(len(tr),len(va),len(te)) ≥ 100`.
- Timestamps strictly increasing within each split.
- `int(tr[-1]) + 2 < int(va[0])` — last train label ends before first validation row.
- `va[0] == eligible[a+24]`, `te[0] == eligible[a+24+b+24]` — embargo exactly 24 eligible rows.
- No dataset file was modified (load only). Test skips if the file is absent (never fabricates).

---

## 4. Findings / caveats (honest)

1. **Purge is measured in eligible rows, not wall-clock or raw-bar distance.** This is correct for
   overlapping label leakage (it needs `embargo ≥ horizon` in *row count*), and it adapts to gaps because
   ineligible rows are skipped consistently. It does **not** guarantee a minimum calendar-time separation
   across session breaks — the timing contract (Part B) must still ratify calendar/session semantics.
2. **No existing test previously exercised the purge boundary over dataset timestamps** (only a feature-tail
   leakage test existed). These 11 tests close that gap for the split/label structure.
3. **`walk_forward.min_train_fraction` is unread** (see reconciliation report); test #9 documents the
   *actual* denominator and constant, it does not "fix" the config mismatch.
4. Tests use synthetic fixtures + a **read-only** inspection of the real dataset; no real data is written,
   reordered, or re-saved.

---

## 5. Conclusion (Part A)

- The split/label/feature structure **does not leak future information** across train/validation/test in
  either synthetic adversarial cases or the real PREP-001 file, provided `embargo ≥ horizon` (24 ≥ 2 holds).
- The purge removes training samples whose `t+h` label would overlap the next split; demonstrated causally
  against an `embargo=0` baseline that leaks.
- Gaps and small/starved datasets are handled safely (monotonic, guarded).
- One open item for TIMING_READY: calendar/session-time separation and execution-clock ratification remain
  NEW_DESIGN (see `execution_timing_contract.md`).

Test evidence: `tests/test_purge_boundary.py → 11 passed`; full suite `136 passed`. No production artifact modified.
