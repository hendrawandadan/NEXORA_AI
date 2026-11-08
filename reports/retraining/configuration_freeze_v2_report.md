# NEXORA AI v2 — Configuration Freeze V2 Report (PREP-001)

Audit timestamp: 2026-11-07
Mode: static + isolated-runtime. **No training, no `train_one()`, no `model.fit()`, no production runner.**
No change to production DB, CSV, dataset, model, backup, or historical config (`config/research.json` is read-only).
Continuation of `reports/retraining/execution_safety_configuration_freeze_report.md`.

Tooling (isolated, read-only): `nexora_audit/configuration_freeze.py`,
tests in `tests/test_nexora_config_freeze_v2.py`. CLI: `python -m nexora_audit freeze`.

---

## 0. Outcome summary

The configuration freeze **pins every parameter that has adequate evidence** and **refuses to invent the
rest**. The manifest hash is reproducible but reported `complete:false` because three items still require a
human/contract decision:

| Item | State | Why |
|---|---|---|
| `max_depth` | REQUIRES_DECISION | Code never set it; LightGBM default `-1` was incidental, not chosen |
| `l1_regularization` (reg_alpha) | REQUIRES_DECISION | Code never set it; default `0.0` was incidental |
| `decision_time_policy` | REQUIRES_DECISION | Depends on the timing contract (Part B) being ratified |

Result: **CONFIG_READY stays FAIL** on purpose. Freezing `max_depth`/`reg_alpha` to arbitrary numbers would
violate the task rule "jangan membekukan parameter yang tidak mempunyai bukti memadai".

Freeze hash (`nexora-cfg-freeze-v2`):
```
9432cc25e4476da3e7deabfbca92fb38e6da02f2e6f46f976a85d2fead24c4cf
```

---

## 1. Evidence matrix (VERIFIED / INFERRED / UNRESOLVED)

Every value is traced to source. FROZEN = settled with evidence; REQUIRES_DECISION = no evidence to freeze.

### 1.1 Engine & objective (Part A: pin only with supporting evidence)

| Parameter | Frozen value | Origin | Evidence |
|---|---|---|---|
| engine | `lightgbm` | VERIFIED (made explicit) | `create_model('auto')` selected lightgbm when importable; freeze makes it explicit |
| engine_version | `4.7.0` | VERIFIED | installed runtime 4.7.0; import verified with sklearn 1.9.1 / pandas 3.1.1 / numpy 2.5.4 |
| objective | `binary` | VERIFIED (made explicit) | dataset target is binary direction `y=(fwd>0)`; lightgbm would infer it, now explicit |

**Why pin `lightgbm==4.7.0` is justified:** the installed interpreter is 3.14.8 (CPython) with
`lightgbm 4.7.0`, `scikit-learn 1.9.1`, `pandas 3.1.1`, `numpy 2.5.4`, `joblib 1.6.0`. `lightgbm` imports
successfully. `requirements.txt` only pins `lightgbm>=4.0`, so the repository's dependency evidence *supports*
(does not contradict) a 4.7.0 pin. The freeze asserts 4.7.0 explicitly and is guarded: `_assert_engine_compatible`
raises if runtime is not 4.7.0 or a dependency version is unavailable.

### 1.2 Tree / optimization parameters

| Parameter | Frozen value | Origin | Evidence |
|---|---|---|---|
| learning_rate | 0.03 | VERIFIED | `model.py learning_rate=.03` |
| num_leaves | 15 | VERIFIED | `model.py num_leaves=15` |
| min_child_samples | 100 | VERIFIED | `model.py min_child_samples=100` |
| feature_fraction | 0.8 | VERIFIED | `model.py colsample_bytree=.8` |
| bagging_fraction | 0.8 | VERIFIED | `model.py subsample=.8` |
| bagging_frequency | 1 | VERIFIED | `model.py subsample_freq=1` |
| l2_regularization | 5.0 | VERIFIED | `model.py reg_lambda=5` |
| max_iter / n_estimators | 300 | VERIFIED | `research.json training.max_iter=300`; runner rejects full training if != 300 |
| random_seed | 42 | VERIFIED | `research.json training.seed=42` → `random_state` |
| early_stopping | false | INFERRED (accepted) | no eval_set/callback; HistGradientBoosting explicit `False` |
| boosting_type | gbdt | INFERRED (accepted) | LightGBM default; not set |
| metric | binary_logloss (unused by project) | INFERRED (accepted) | project reports custom `nexora_evaluator.metrics` |

### 1.3 Split / windowing

| Parameter | Frozen value | Origin | Evidence |
|---|---|---|---|
| train_fraction | 0.6 | VERIFIED | `research.json`; `split_indices` |
| validation_fraction | 0.2 | VERIFIED | `research.json`; `split_indices` |
| embargo_bars | 24 | VERIFIED | `research.json`; pipeline uses `max(horizon, embargo)` |
| walk_forward_folds | 3 | VERIFIED | `research.json walk_forward.folds=3` |
| walk_forward_min_train_fraction | 0.5 | INFERRED | pipeline hardcodes `max(n*0.50,1000)`; config value not read |
| prediction_horizon | 2 | VERIFIED | PREP-001 tuple; label uses h=2 |
| min_bars | 5000 | VERIFIED | `research.json training.min_bars=5000` |

### 1.4 REQUIRES_DECISION (deliberately NOT frozen)

| Parameter | Default observed | Why not frozen |
|---|---|---|
| max_depth | -1 (unlimited) | Never set in code; infinite depth is a LightGBM default, not a chosen value. Freezing `-1` would silently bless an unbounded tree. |
| l1_regularization | 0.0 | `reg_alpha` never set; zero L1 is a default, not a decision. |
| decision_time_policy | none | Defined by the execution timing contract; unratified (§2, and `execution_timing_contract.md`). |

A human must pick explicit `max_depth` and `reg_alpha` values (or explicitly accept the defaults as a
recorded decision) to complete the freeze.

---

## 2. Versioned definitions (feature / target / split)

Each contract is hashed deterministically from its concrete definition (canonical JSON), so the id changes
if and only if the rule changes.

| Contract | Version id | Content basis |
|---|---|---|
| feature_set_version | `feat-e12cda69dfe04e45` | 29 ordered columns from `build_features()` |
| target_definition_version | `target-b9c8f231d7fb8dbe` | `fwd[:-h]=close[h:]/close[:-h]-1`, `y=(fwd>0)`, mask, h=2 |
| split_policy_version | `split-27dd116e49698640` | chronological 0.6/0.2 + embargo=max(h,24) + walk-forward folds=3, initial=max(n*.50,1000) |

Feature columns (exact, ordered):
`ret_1, ret_2, ret_4, ret_8, ret_16, ret_32, ret_64, atr_pct, range_atr, body_atr, upper_wick,
lower_wick, rsi14, dist_sma20, dist_sma50, dist_sma100, dist_sma200, ema_slope20, ema_slope50,
ema_slope100, ema_slope200, vol20, vol_ratio, volume_z, hour_sin, hour_cos, dow_sin, dow_cos,
spread_relative`.

> Note: `decision_time_policy` is intentionally left out of the group above until the timing contract is
> ratified (see Part B). The freeze records `split_policy_version` even though `walk_forward.min_train_fraction`
> in `research.json` is not actually read by the pipeline (the pipeline hardcodes 0.50); this mismatch is
> surfaced as INFERRED and should be reconciled when the split policy is formally signed.

---

## 3. Dataset identity (recomputed, unchanged)

```
relative_path: data/raw/EURUSD/EURUSD_M30_202001020000_202611062130.csv
sha256:        e6729c4596f872f503cc04c7611375419395ab9cc92f9d918121609cdb282945
bars_expected: 70694
```

The dataset file was hashed read-only; nothing was modified.

---

## 4. Manifest & hash determinism

- `config_hash.hash` = `9432cc25…`, `hash_version = nexora-cfg-freeze-v2`.
- Recomputed twice in `test_freeze_hash_reproducible_and_incomplete` → identical.
- `complete:false` with `requires_decision = [max_depth, l1_regularization, decision_time_policy]`.
- Hash covers job identity, dataset sha256, runtime lightgbm/python, all frozen values, and the three
  version ids — so any value change re-hashes.

Freeze JSON is written only when the caller chooses a non-production path
(`write_freeze_manifest(project_root, out_path)`); the CLI prints it and writes nothing.

---

## 5. Test results (actual)

`tests/test_nexora_config_freeze_v2.py` → **12 passed** (part of full run below). Key assertions:
- engine/objective/max_iter frozen; lightgbm pinned to 4.7.0; import verified.
- `max_depth` and `l1_regularization` are REQUIRES_DECISION and **not** in the frozen set.
- feature/target/split ids deterministic and content-derived.
- freeze hash reproducible and `complete:false` with the expected 3 decisions.
- config gate returns FAIL on the incomplete freeze.

Full suite: **125 passed** (see `prep001_readiness_v2_report.md`).

---

## 6. Conclusion (Part A)

- Evidenced parameters: **frozen** (26 entries).
- Unsupported parameters (`max_depth`, `reg_alpha`): **not frozen**; raised as REQUIRES_DECISION.
- Historical configuration: **unchanged** (`config/research.json` read-only).
- `lightgbm==4.7.0`: **pinned** with verified import + dependency evidence.

CONFIG_READY remains **FAIL** until `max_depth`, `reg_alpha` and the decision-time policy are decided.
That is the correct, honest state — see `prep001_readiness_v2_report.md`.
