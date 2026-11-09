# FASE 2A — ADAPTIVE BARRIER, APPROACH #1: VOLATILITY-TARGETED (pre-registration record)

**Status:** implementation + anti-leak tests landed. **No experiment run, no
training dispatched, no baseline/config/dataset/model touched.**
**Date:** 2026-11-08.
**Baseline comparator:** `fase2a-atr-baseline-frozen` (ATR 1.5/1.0×ATR, V=16) — UNCHANGED.
**Design source:** `reports/fase2a/ADAPTIVE_BARRIER_EXPERIMENT_DESIGN.md` §3.1 Option 1.

---

## 0. What this step is (and is not)

This is **Option 1 — Volatility-targeted barrier** from the design doc, the FIRST
of the three candidate formulations. It is deliberately the simplest / least
overfit-prone: predict forward volatility from `info ≤ t`, set the barrier as a
multiple of that prediction. No regime classification, no economic-optimal multiplier.

This step **does not** run an experiment and **does not** compare against ATR yet.
It only makes the module concrete, correct, and leakage-audited so the experiment
can be run under a fixed, pre-registered protocol.

---

## 1. Barrier definition (Option 1)

```
pred_vol_frac_t    = model.predict(features <= t)          # forward realized range / close
barrier_distance_t = k_vol * pred_vol_frac_t               # price units
upper_t = entry_t + barrier_distance_t                     # BUY profit / SELL loss
lower_t = entry_t - barrier_distance_t                     # BUY loss   / SELL profit  (symmetric)
vertical_t = V bars
```

- `k_vol` is a **pre-registered constant** (default 1.25), not tuned on test.
- Semantics: the barrier scales with predicted forward volatility — calmer regime
  → tighter barrier, choppier regime → wider barrier — instead of a fixed ATR multiple.

## 2. Apple-to-apple guarantee

Labeling is routed through the **frozen** `triple_barrier.label_events`, by passing
`atr = predicted_vol_price / k_vol` with `BarrierConfig(k_up=k_dn=k_vol,
vertical=cfg.vertical)`. Because the frozen labeller computes
`upper = entry + k_up*atr` and `lower = entry - k_dn*atr`, this reproduces
`upper/lower = entry ± k_vol*predicted_vol_price`. Execution (simulated bid/ask),
status logic, vertical exit, event attribution and cost application are therefore
**byte-for-byte identical** to the ATR baseline. The ONLY difference is the barrier
distance source.

## 3. Training target (hindsight, used only as a label)

`forward_realized_range(bars, H)` at bar `t` =
`(max(high[t+1..t+H]) − min(low[t+1..t+H])) / close[t]`.

- This is HINDSIGHT by construction and is used **only** as a supervised target.
- The predictor for the same row never sees it (features are trailing).
- Last `H` rows are `NaN` (no future available) and excluded from training.

## 4. Anti-leakage protocol enforced by unit tests (`tests/test_adaptive_barrier.py`)

1. `test_target_no_lookback` — altering bars `> t` changes the target at `t` (proves
   the target really depends on the future, i.e. is a genuine forward label), while
   altering bars `< t` does NOT change it.
2. `test_predict_does_not_see_future` — predicting barrier distance for a row is
   unchanged when bars after that row are altered (features are trailing only).
3. `test_barrier_distance_formula` — `distance == k * pred_vol` and upper/lower
   symmetry holds.
4. `test_label_uses_same_core` — `label_with_adaptive_barrier` produces the identical
   schema and status vocabulary as the frozen baseline.

These are the §4 "wajib" proofs from the design doc, implemented as code — not
claimed in prose only.

## 5. What is NOT done yet (requires separate sign-off)

- No purged walk-forward ATR-vs-adaptive experiment.
- No bootstrap CI, no per-regime breakdown, no stress-scenario comparison.
- No GO/NO-GO verdict. Per design §6, ATR remains the baseline until the experiment
  passes **all** pre-registered criteria.

## 6. Honesty note

Literature and the design doc (§2) both expect ATR to be hard to beat OOS after
costs. A NO-GO result (adaptive ≤ ATR) is a **valid** outcome that closes the
hypothesis; this step makes no performance claim either way.
