# PREP-001 Walk-Forward R3 Impact Report

Date: 2026-11-07
Scope: TASK C — user approved **R3**: walk-forward purge = `max(horizon, embargo_bars)`; PREP-001 uses purge
**24**; holdout 0.6/0.2 unchanged. This report documents the R3 implementation, simulation, and leakage proof.

---

## 1. What R3 changes (source-verified before/after)

File: `nexora_learning/pipeline.py`

**Before** (hardcoded, purge = horizon):
```python
def walk_forward_scores(..., folds=3):
    ...
    test_start = min(train_end + horizon, n)   # purge = h (2 for PREP-001)
```

**After** (R3, backward-compatible default):
```python
def walk_forward_scores(..., folds=3, purge=None):
    purge = horizon if purge is None else max(int(purge), int(horizon))
    ...
    test_start = min(train_end + purge, n)      # R3: purge = max(h, embargo)
```
And `train_one` opts in:
```python
wf_purge = max(horizon, int(cfg.get("embargo_bars", horizon)))   # = max(2, 24) = 24 for PREP-001
wf = walk_forward_scores(..., purge=wf_purge)
```

- **Default `purge=None` preserves legacy behaviour** for any other caller (no silent global change).
- Only the training path (`train_one`) opts into R3 via config `embargo_bars`.
- **Holdout split (`split_indices`, 0.6/0.2) is NOT touched.** R3 affects only the expanding-window
  walk-forward purge gap.

## 2. Simulation methodology (isolated, no training)

File: `tests/test_walk_forward_r3_impact.py` — **6 passed**.
Pure replication of the fold geometry on an eligible-row index `0..n-1` with the same
`initial=max(int(n*0.5),1000)`, `chunk=remaining//folds` rule, run under both purge policies.
`n = 70694` (PREP-001 M30 H2 eligible rows). **No dataset/model/DB access; no `train_one`, no `model.fit`.**

## 3. Simulation results

| Scenario | purge | Fold geometry (conceptual) |
|---|---|---|
| Current (purge = horizon) | 2 | test_start = train_end + 2 |
| R3 (purge = max(h,24)) | 24 | test_start = train_end + 24 |

Assertions verified by the tests:

- `test_r3_purge_is_max_horizon_embargo`: every fold purge == **24**.
- `test_current_purge_is_horizon`: every fold purge == 2 (documents old behaviour).
- `test_r3_no_leakage`: for horizons 1,2,4,8,12,24 — `max(train) + horizon < min(test)` in **every** fold.
- `test_r3_and_current_both_leak_free_but_r3_larger_gap`: R3 gap ≥ current gap + (24 − h); both leak-free.
- `test_r3_reduces_test_coverage_slightly`: R3 test rows ≤ current test rows (larger purge ⇒ marginally less
  test coverage, as expected; never more).
- `test_r3_impact_on_holdout_unchanged`: locks holdout fractions 0.6/0.2 as untouched.

## 4. Leakage proof (why R3 is safe)

The label of a training row at index `t` uses `close[t+h]`. A test row starting at index `s` is safe iff
`t_last_train + h < s`. In the geometry:

- Current: `s = train_end + h` → `(train_end−1) + h = s − 1 < s`. Safe, gap = h.
- R3: `s = train_end + max(h,embargo)` = `train_end + 24` → `(train_end−1) + h ≤ s − 1`.
  Since `24 ≥ h`, the gap is **larger**, so `t_last_train + h < s` still holds with margin `≥ 24 − h ≥ 0`.

So R3 **strictly increases** the purge gap; it cannot introduce label overlap. Verified empirically by
`assert_no_leakage` across all horizons.

## 5. Wiring verification

File: `tests/test_r3_pipeline_wiring.py` — **3 passed**:
- `purge` parameter exists, default `None` (legacy preserved).
- `train_one` source contains `wf_purge`, `embargo_bars`, and `purge=wf_purge`.
- Calling `walk_forward_scores(..., purge=24)` on tiny input produces **no folds** and **never calls fit**.

## 6. Effect on current behaviour / metrics

- For PREP-001 (h=2, embargo=24): walk-forward folds now purge **24 bars** instead of 2. Each fold's test
  window starts 22 bars later than before → slightly fewer walk-forward test rows per fold. This is a research
  split change only; **no production metric file was regenerated** (no training run).
- Holdout (0.6/0.2, embargo max(h,24)) was already purge-24; R3 makes walk-forward **consistent** with it.

## 7. Safety

- Only simulation/wiring tests ran; **no `train_one`, no `model.fit`, no dataset write**.
- Config values (max_iter=300, fractions, embargo=24) unchanged.
- Production data/log/dataset hashes unchanged (see implementation summary §Proofs).
