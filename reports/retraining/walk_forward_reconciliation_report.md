# NEXORA AI v2 — Walk-Forward `min_train_fraction` Reconciliation Report (Part B)

Audit timestamp: 2026-11-07
Scope: trace **every** source that defines `walk_forward.min_train_fraction` and what the code actually uses.
Mode: read-only static analysis. No value chosen by guesswork; only reported what each component uses.
**No training; no config change; no historical config modified.**

---

## 0. Headline finding

**`walk_forward.min_train_fraction` is defined in config but read by NO code.** The walk-forward
implementation hardcodes a start fraction of **0.50** (`max(int(n*0.50), 1000)`). So:
- Config says `0.5`.
- Code uses `0.50` (same number today, but *by coincidence of the hardcode*, not by reading config).
- Any future config change to `min_train_fraction` would be **silently ignored**.

This is a latent config/code divergence. It does not change current behaviour (both are 0.50), but it must be
reconciled before the split policy is ratified.

---

## 1. Source-by-source trace

### 1.1 Source defaults (function signature / hardcode)
File: `nexora_learning/pipeline.py`
```python
def walk_forward_scores(X, y, mask, horizon, engine, seed, max_iter, folds=3):
    idx = np.flatnonzero(mask); n = len(idx); results = []
    initial = max(int(n*.50), 1000)          # <-- HARDCODED 0.50
    remaining = n - initial
    if remaining < folds*100: return results
    chunk = remaining // folds
    for k in range(folds):
        train_end = initial + k*chunk
        test_start = min(train_end + horizon, n)   # purge by horizon
        test_end = n if k == folds-1 else min(test_start + chunk, n)
        ...
        folds=folds
```
- **Effective `min_train_fraction` used = 0.50**, floor 1000 rows.
- `folds` default 3; overridden by config `walk_forward.folds`.
- Purge in walk-forward = `horizon` (not 24). Note: walk-forward purge uses `horizon`, whereas the
  holdout split (`split_indices`) uses `max(horizon, embargo_bars)=24`. Different purge sizes, both ≥ horizon.

### 1.2 Config defaults
File: `config/research.json`
```json
"walk_forward": { "folds": 3, "min_train_fraction": 0.5 }
```
- `folds` = 3 is **read** by pipeline: `wf_cfg.get("folds", cfg.get("walk_forward_folds", 3))`.
- `min_train_fraction` = 0.5 is **never read** (see §1.4 grep).

### 1.3 Historical configuration
- Active `config/research.json` is the only historical config file present; `min_train_fraction=0.5`.
- 37 historical run configs are **not available** (documented in `training_configuration_recovery_report.md`).
- Simulation metadata snapshots (`reports/retraining/simulations/.../metadata.json`) record
  `train_fraction`, `validation_fraction`, `embargo_bars`, `horizons`— but **not** `min_train_fraction`
  and are explicitly dummy/simulated, not historical training truth.

### 1.4 Split implementation
- Holdout split `split_indices` does **not** use `min_train_fraction` at all (it uses `train_frac`,
  `valid_frac`, `embargo`).
- Walk-forward `walk_forward_scores` uses the hardcoded `0.50`, not the config key.
- **grep for `min_train_fraction` across all code (excluding reports): zero hits.** The only in-code reader
  of any walk-forward config is `wf_cfg.get("folds", ...)`.

### 1.5 Existing tests
- No test reads or asserts `min_train_fraction`.
- New test `test_walk_forward_min_train_fraction_denominator_is_eligible_count`
  (`tests/test_purge_boundary.py`) documents the *actual* denominator (`n = eligible rows`) and the hardcoded
  `0.50`, proving the value is not sourced from config.

### 1.6 Runner
File: `batch1_execution_runner.py::prepare_training_config`
```python
"train_fraction": float(training_cfg.get("train_fraction", 0.6)),
"validation_fraction": float(training_cfg.get("validation_fraction", 0.2)),
"embargo_bars": int(training_cfg.get("embargo_bars", 24)),
"horizons": training_cfg.get("horizons", [1,2,4,8,12,24]),
```
- Reads train/validation fractions and embargo, and passes them to the pipeline— but **does not read
  `walk_forward`** at all. The runner has no notion of `min_train_fraction`.

---

## 2. Comparison table (value used by each component)

| Component | Reads `min_train_fraction`? | Effective start fraction | Floor | Source |
|---|---|---|---|---|
| `walk_forward_scores` (code) | **No** | **0.50** (hardcoded) | 1000 rows | `pipeline.py` |
| `config/research.json` | defines = `0.5` | — (unused) | — | config file |
| `split_indices` (holdout) | No | n/a (uses 0.6/0.2) | 100 rows/split | `pipeline.py` |
| Runner `prepare_training_config` | No | n/a | — | `batch1_execution_runner.py` |
| Historical run configs | unavailable (37 absent) | unknown | — | not present |
| Existing tests | No | — | — | none |
| New purge tests | document only | 0.50 (verified) | 1000 | `tests/test_purge_boundary.py` |

---

## 3. Conflicts found

| ID | Conflict | Severity | Behavioural impact today |
|---|---|---|---|
| C1 | Config `min_train_fraction=0.5` is never read; code hardcodes 0.50 | **Medium (latent)** | None now (both 0.50), but a future config edit silently has no effect |
| C2 | Walk-forward purge uses `horizon`; holdout purge uses `max(horizon, embargo_bars)=24` | Low | Both ≥ horizon so no leakage; inconsistent policy though |
| C3 | `walk_forward.min_train_fraction` floor is 1000 rows while holdout floor is 100/split | Low | Sizing semantics differ between the two schemes |
| C4 | Denominator = eligible rows (`n=len(mask.flatnonzero)`), not total bars | Info | Correct for leakage; must be stated in the frozen split policy |
| C5 | Historical per-run configs absent (37 jobs) | Info | Cannot confirm a historical value was ever different |

---

## 4. What each value "means" (no guessing)

- The **only** number the runtime uses is `0.50` (hardcoded). This is a fact from `pipeline.py`, not a choice.
- The config `0.5` is a **declaration with no consumer**. It is not proven to have ever driven a run.
- We do **not** assert that 0.50 is "the right" value — only that it is what the code does, and that config
  and code are not wired together for this key.

---

## 5. Recommended reconciliation (for human decision — not applied)

Options, all requiring sign-off (no value chosen here):

- **Option R1 (wire config to code):** change `walk_forward_scores` to accept `min_train_fraction` and read
  `walk_forward.min_train_fraction`, with the existing `max(int(n*frac), 1000)` floor. Behaviour identical at
  0.5, but config becomes authoritative.
- **Option R2 (remove the dead key):** delete `min_train_fraction` from config and document 0.50 as a fixed
  constant of the split policy version.
- **Option R3 (unify purge):** make walk-forward purge also use `max(horizon, embargo_bars)` to match the
  holdout, and record the chosen purge size in `split_policy_version`.

Whichever is chosen, the value/denominator must be written into the frozen `split_policy_version`
(currently `split-27dd116e49698640` records `initial=max(n*0.50,1000)`), so the hash reflects the real rule.

---

## 6. Conclusion (Part B)

- **No guesswork:** every component's value is reported from source.
- `min_train_fraction` config key is **dead**; code uses hardcoded **0.50** on the **eligible-row** denominator.
- Conflicts C1–C4 are real and must be resolved before TIMING/split ratification; none currently cause
  leakage (both purge sizes ≥ horizon), but the config/code divergence is a reproducibility risk.
- No configuration, dataset, model, or historical file was changed by this audit.
