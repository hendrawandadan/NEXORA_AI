# NEXORA AI — PREP-001 DUAL TARGET IMPLEMENTATION DESIGN

Design date: 2026-11-08
Role: Senior Quantitative Research Engineer / ML Systems Architect / Data Engineer / Trading Execution Validation Engineer
Scope: PREP-001 — EURUSD, M30, horizon h = 2, bar-open timestamps, T3 execution contract, dual target (T1 statistical + T3 execution-aligned), transaction cost DEFERRED.
Mode: **DESIGN + READ-ONLY INSPECTION ONLY.**
IMPLEMENTATION_DESIGN_STATUS: **AWAITING_OWNER_APPROVAL**

> This document is a design proposal. It is NOT an implementation. No source code, config,
> database, migration, execution log, plan, dataset, model, status, sign-off, or authorization
> was changed. No training, dispatch, validation, or promotion was run. Every claim below was
> verified by reading the repository; numeric samples were produced by read-only loads.

---

## 1. Executive Summary

The owner has fixed the execution contract as **T3** (`entry Open[t+1]`, `exit Open[t+h+1]`)
and requested a **dual-target** architecture keeping a **T1 statistical target** and a
**T3 execution-aligned target** completely separate (separate formula, version, hash, mask,
metadata, experiment identity, artifacts) so they can be trained and evaluated independently.

Findings from inspecting the code:

1. **Targets** are produced in one place: `nexora_learning/pipeline.py:16-19` (`prepare()`
   builds `fwd` close-to-close and `y=(fwd>0)`). There is no `target_type` and no
   `target_definition_version` threading. T3 is not implemented.
2. **The DB cannot hold two jobs for the same `(scope,symbol,timeframe,horizon)` without a
   migration:** `uq_training_job_tuple ON (scope, ifnull(symbol,''), timeframe, horizon)`
   (migration 003) collides T1 vs T3 for EURUSD/M30/h2. `job_key` is UNIQUE and could carry
   the target type, but the tuple index still forbids coexistence.
3. **The authorization gate is single-target:** `authorization.py` hardcodes one
   `PREP001_JOB_KEY`, one `PREP001_EXECUTION_ID`, and binds to one frozen target version. It
   **cannot currently distinguish T1 from T3**. Documented gap, not fixed here.
4. **Purge geometry must change for T3:** T3's label is known at `Open[t+h+1]`, so its
   effective information horizon is **h+1**, not h. The current `purge=horizon`
   (`pipeline.py:38`) is insufficient for T3. The conservative rule
   `purge_bars = max(effective_target_horizon, embargo_bars)` with effective = h for T1 and h+1
   for T3 must be enforced. At h>=24 this changes behaviour (h=24 -> T3 purge 25, not 24).
5. **Cost modeling stays DEFERRED:** dataset has a sparse integer `<SPREAD>` (88.8% zeros,
   point-size UNRESOLVED), no wired slippage/commission/swap. The design keeps a pure
   gross-return evaluation extension point but activates nothing.

Recommended (pending approval) shape: **two independent experiment tracks
(`target_type` in {T1,T3}) sharing the same feature dataset**, each with its own
label/version/hash/mask and target-namespaced artifacts, with the authorization gate extended
to be target-type aware. Persisting *two* `training_jobs` per (scope,symbol,tf,h) would require
a schema change (migration v5) — the design presents options and recommends **not** migrating
now (Option C: artifacts + `strategy_experiments` identity, no production-DB writes).

---

## 2. Owner Decisions (fixed — NOT to be re-asked)

| Decision | Value |
|---|---|
| Instrument | EURUSD |
| Timeframe | M30 |
| Horizon | 2 |
| Timestamp convention | bar-open |
| Decision time | after candle t completes |
| Execution entry | `Open[t+1]` |
| Execution exit | `Open[t+h+1]` |
| Execution contract | **T3** |
| Target architecture | **Dual target (T1 + T3)** |
| Transaction cost modeling | **DEFERRED / LATER** |

Design approval != approval to change code or run training.

---

## 3. Existing Architecture Audit

### 3.1 Target / label production
`pipeline.prepare(path,horizon,symbol,global_mode)` — `pipeline.py:11-19`:

```python
close=df.close.to_numpy(); fwd=np.full(len(df),np.nan)
fwd[:-horizon]=close[horizon:]/close[:-horizon]-1          # T1 close->close
y=(fwd>0).astype(int)
mask=X.notna().all(axis=1).to_numpy() & np.isfinite(fwd)
return df,X,y,fwd,mask
```

Single target only, keyed off `close`, **no target_type**, **no T3**.

### 3.2 Feature generation
`features.build_features(df)` — `features.py:3-40`: trailing-only (`.shift/.rolling/.ewm`),
29 columns incl `spread_relative` (feature-level only). Target-agnostic -> reusable unchanged.

### 3.3 Split & walk-forward
- `pipeline.split_indices(mask,horizon,...)` — `pipeline.py:22-29`: 0.6/0.2 chronological,
  `embargo=max(horizon,24)` at both boundaries (`:26`, `:28`).
- `pipeline.walk_forward_scores(...,purge=None)` — `pipeline.py:32-53`: expanding folds=3,
  `purge = horizon if purge is None else max(purge, horizon)` (`:38`).
- `train_one` wires `wf_purge=max(horizon,embargo)` (`:66`) and
  `split_indices(...,max(horizon,embargo))` (`:58`). All assume a single horizon = h (T1
  endpoint). **Not T3-safe.**

### 3.4 Direction / realized return artifacts
`pipeline.py:74` direction band `margin=.03`; `:76` `realized_forward_return=fwd[te]` (T1).
Written to `signals/<symbol>/<tf>/h<horizon>/<kind>_signals.csv` and
`reports/<kind>/<symbol>/<tf>/h<horizon>/report.json` — **no target-type namespace -> T1/T3
would collide on path.**

### 3.5 Evaluation
- `metrics.metrics(y,p)` — accuracy/balanced/brier/logloss/AUC (gross, target-agnostic).
- `trading.evaluate_signals_frame(df,round_trip_cost_bps=0.0)` — can subtract a constant cost
  (`trading.py:86`) but **not wired to `train_one`**; future cost extension (DEFERRED).

### 3.6 DB schema (v4)
- `training_jobs`: `job_key UNIQUE`; `UNIQUE(scope,ifnull(symbol,''),timeframe,horizon)`
  (`uq_training_job_tuple`, migration 003); free-form `config_json`.
- `training_runs`: `training_config_json` free-form; `UNIQUE(job_id,run_index)`; partial unique
  `uq_one_active_run_per_job`.
- `model_artifacts(artifact_type IN {model,report,signals,metadata,manifest,other})`,
  `UNIQUE(run_id,artifact_type,artifact_path)`.
- `strategy_experiments(experiment_key UNIQUE, config_json, result_json, run_id)` — natural
  home for the T1/T3 x A/B/C matrix.
- **No target_type column anywhere.** `config_json` is the only free-form slot.

### 3.7 Authorization gate
`authorization.authorize_execution(...)` binds a single execution id to the single frozen
target version, config hash, timing hash, candidate. No target_type dimension.

### 3.8 Runner
`batch1_execution_runner.process_run` -> `guard_execution_authorized(row,cfg)` (fail-closed)
before STARTED/train; `execution_ids` scope enforced; job-scoped to PREP-001.

---

## 4. T1 Specification (Statistical Direction Target)

- Formula: `return_t1[t] = Close[t+h]/Close[t] - 1` -> h=2: `Close[t+2]/Close[t] - 1`.
- Label: `y_t1[t] = 1 if return_t1[t] > 0 else 0`.
- Information endpoint: `Close[t+h]` (known at bar t+h close).
- Effective information horizon (bars ahead of t): **h (=2)**.
- Label availability: `Close[t+h]` = `ts[t+h] + 30min`.
- Purpose: statistical directional learning, baseline, historical direction analysis.
- **Not** realized execution PnL (assumes close-to-close fill).
- Version id: `target-t1-<hash>` (hash = sha256 of T1 payload, section 10).
- Mask: row t labelled iff `isfinite(Close[t+h])` and all features notna (last h rows excluded).

## 5. T3 Specification (Execution-Aligned Target)

- Formula: `return_t3[t] = Open[t+h+1]/Open[t+1] - 1` -> h=2: `Open[t+3]/Open[t+1] - 1`.
- Label: `y_t3[t] = 1 if return_t3[t] > 0 else 0`.
- Information endpoint: `Open[t+h+1]` (known at start of bar t+h+1, after bar t+h closes).
- Effective information horizon (bars ahead of t): **h+1 (=3)** — purge-critical.
- Label availability: `Open[t+h+1]` = `ts[t+h+1]` (bar-open label of that bar).
- Purpose: execution-aligned directional learning, gross execution research, future strategy
  evaluation. **Primary target for NEXORA execution research.**
- Version id: `target-t3-<hash>`.
- Mask: row t labelled iff `Open[t+1]` and `Open[t+h+1]` are finite and > 0 and all features
  notna (last **h+1** rows excluded because `Open[t+h+1]` must exist).

Rationale for h+1 endpoint: entering `Open[t+1]` and exiting `Open[t+h+1]` needs the open of
bar t+h+1, which only exists at the START of bar t+h+1 — one bar after `Close[t+h]`. Any train
row whose label reads `Open[t+h+1]` therefore reaches h+1 bars forward.

---

## 6. Dual Target Architecture

Recommended (simplest, safest): **two independent experiment tracks with a shared feature
dataset and per-target label pipelines.** Do NOT build a multi-output model or merge labels.

### 6.1 Target contract object (new, pure, read-only)

```
TargetSpec(target_type, formula, label_fn, required_columns, effective_horizon,
           version_payload, mask_fn)
T1 = TargetSpec("T1", "close_to_close", needs=["close"], effective_horizon=h, ...)
T3 = TargetSpec("T3", "open_to_open",   needs=["open"],  effective_horizon=h+1, ...)
```

`prepare(path,horizon,symbol,target="T1"|"T3")` returns the same 5-tuple `(df,X,y,fwd,mask)`
with target-specific `fwd`/`y`/`mask`; `X` unchanged. **Backward compatible:** default
`target="T1"` reproduces current behaviour exactly.

### 6.2 Isolation guarantees (per target)

| Dimension | T1 | T3 | Isolation |
|---|---|---|---|
| Formula | close->close | open->open | separate TargetSpec |
| target_definition_version | `target-t1-<hash>` | `target-t3-<hash>` | separate hash payload |
| target_hash | sha256(T1) | sha256(T3) | distinct |
| mask | needs Close[t+h] | needs Open[t+1],Open[t+h+1] | separate mask_fn |
| metadata path | `.../t1/` | `.../t3/` | path namespace |
| experiment identity | `PREP-001-T1-{A,B,C}` | `PREP-001-T3-{A,B,C}` | experiment_key |
| artifacts | `signals/reports/models/.../t1/h2/` | `.../t3/...` | path namespace |
| purge effective horizon | h | h+1 | per-target |

No shared mutable target vector, no overwrite: every artifact path and version/hash is
namespaced by `target_type`. Evaluation/comparison is fully independent.

### 6.3 Why not multi-output / merged target
Merging loses distinct information endpoints (h vs h+1) -> purging forced to max, silently
weakening T1; label semantics become ambiguous. Two tracks keep each model honest and each
report interpretable, preserving statistical-vs-executable comparison.

### 6.4 Feature reuse
`build_features(df)` is target-agnostic -> compute **once**, reuse for both tracks. Pin
identical `feature_set_version` across T1/T3 (fair comparison); only target version differs.

---

## 7. Timestamp Contract

Preserved: `ts[t]` = bar-OPEN time of candle t. Candle t closes at `ts[t] + 30min` (M30).

| Event | Definition | t=100, h=2 |
|---|---|---|
| Decision | after candle t closes | after `Close[100]` (ts 100 + 30m) |
| Feature availability | after candle t closes | after `Close[100]` |
| Prediction | after candle t closes | after `Close[100]` |
| Earliest executable | `Open[t+1]` | `Open[101]` |
| T3 exit price | `Open[t+h+1]` | `Open[103]` |
| T3 holding | h=2 M30 bars (open->open) | bars 101,102 |
| T3 label available | at `Open[103]` | start of bar 103 |

Downstream consumers MUST treat `ts` as bar-open, not bar-close:

1. Document the convention at `loader.load_bars` and in `features`/`pipeline`.
2. Consumers needing "close time" add `timeframe_minutes(tf)` (exists in `loader`).
3. A guard/test asserts `ts` spacing == timeframe minutes (already true: 67,033/70,694 M30).
4. Signals CSV keeps `time` = bar-open `ts[te]`; optional `bar_open_ts`/`bar_close_ts` columns
   can be emitted for clarity (design).

Numeric confirmation (read-only real CSV, t=100, h=2):

```
Close[102]/Close[100]-1 = 0.0103667599   (T1)
Open[103] /Open[101] - 1 = 0.010367      (T3, matched h=2 open->open)
```

---

## 8. Target Masking

### 8.1 Boundary requirements
- T1 needs `Close[t+h]` -> last **h** rows unlabelled.
- T3 needs `Open[t+1]` and `Open[t+h+1]` -> last **h+1** rows unlabelled.

### 8.2 Validation checks (fail-closed; drop row otherwise)
- `np.isfinite` on all required prices (no NaN/Inf).
- `price > 0` (no zero/negative price).
- OHLC present for required rows (missing candle -> NaN -> excluded).
- Duplicate timestamps already removed by `loader.drop_duplicates("ts")`; assert monotonic ts.
- Non-finite labels excluded.
- Alignment: `X.index` is `df.index` (0..N-1); `y`/mask positional-aligned; build on `df.index`
  and index with the same positions `split_indices` uses (`np.flatnonzero(mask)`).
- **Row index preservation:** never reset/drop inside target computation.

### 8.3 Worked index example (proves labels come from the correct prediction row)

```
t=100, h=2
T1: y_t1[100] = 1 if Close[102]/Close[100]-1 > 0  ; endpoint Close[102] ; needs 102 <= N-1
T3: y_t3[100] = 1 if Open[103] /Open[101] -1 > 0  ; endpoints Open[101],Open[103] ; needs 103 <= N-1
```

T1 valid t in [0, N-1-h]; T3 valid t in [0, N-1-(h+1)]. T3 mask always excludes one more
trailing row than T1 — the exact index boundary the tests must lock.

---

## 9. Purge and Walk-Forward Design

Current code purges by `horizon` (=T1 endpoint h). T3's endpoint is h+1, so purge must be
conservative:

```
effective_label_horizon(T1) = h
effective_label_horizon(T3) = h + 1
purge_bars(target)          = max(effective_label_horizon(target), 24)
```

Design:
- Thread `target_effective_horizon` into `split_indices`/`walk_forward_scores` (or pass an
  explicit `purge` = computed value).
- `split_indices`: `embargo_eff = max(effective_horizon, embargo)`; validation start
  `a + embargo_eff`; test start `va_end + embargo_eff`.
- `walk_forward_scores`: `purge = max(int(purge), int(effective_horizon))`.
- Leakage invariant per fold: `tr[-1] + effective_horizon < te[0]` (positional). T1: +h; T3: +(h+1).

Test matrix (h in {1,2,4,8,12,24, >24}) for BOTH targets:
- Synthetic eligible indices size N; run split/wf; assert `max(train)+effective_horizon <
  min(test)` (or empty) for every fold.
- Assert `purge == max(effective_horizon, 24)`.
- Assert chronological; T3 gap >= T1 gap.
- **Critical h>=24 subtlety:** h=24 -> T1 purge 24, **T3 purge 25**; h>24 -> T3 tracks h+1.
  Existing R3 tests use `max(h,24)` and would under-purge T3 at h>=24. Must add explicit T3
  purge tests at h in {24, 48} (no code changed now).

---

## 10. Experiment Identity and Config Hash

### 10.1 Identity

```
PREP-001-{T1|T3}-{A|B|C}
```

Naming proposal only (NOT inserted into production DB). Each experiment stores:
`experiment_id` (unique), `target_type`, `target_definition_version`, `target_hash`,
`feature_set_version`, `split_policy_version`, `timing_contract_version`, `model_config_hash`,
`dataset_hash`, `horizon`, `instrument`, `timeframe`.

### 10.2 Hash composition (deterministic)
- `target_hash = sha256(canonical_json({target_type, formula, horizon, timestamp_convention,
  effective_horizon}))` -> `target_definition_version = "<T1|T3>-<first16>"`.
- `model_config_hash = sha256(canonical_json(candidate_overrides + fixed_model_params))`
  (candidate A/B/C from `experiment_config` + `create_model` fixed kwargs).
- `dataset_hash` = existing `sha256_recomputed` (canonical_config).
- `timing_contract_version` = `nexora-timing-v1` (+ ratified variant when signed).
- `feature_set_version` = existing `feat-<hash>`; `split_policy_version` must be re-derived per
  target once effective horizon differs (new `split_policy_version_t3` encoding h+1).

All hashes reproducible (locked by determinism tests).

---

## 11. Evaluation Design

Two separate reports; never conflate gross with net; cost DEFERRED (extension point only).

### 11.1 T1 report (`.../t1/h2/report.json`)
Accuracy, balanced accuracy, AUC, Brier, log loss, positive_rate, n (reuse `metrics.metrics`).

### 11.2 T3 report (`.../t3/h2/report.json`)
- Classification: accuracy, balanced accuracy, AUC, Brier, log loss.
- Directional/gross (from `direction x return_t3` on active rows, GROSS only): signal count,
  long/short/neutral distribution, gross expectancy, gross profit factor, gross drawdown,
  exposure. Reuse `trading.evaluate_trade_returns`/`evaluate_signals_frame` with
  `round_trip_cost_bps=0.0`. Suffix all such numbers `_gross`.

### 11.3 Comparison (read-only, optional)
Separate `PREP001_COMPARE.md`/json reading both reports — no shared vector.

### 11.4 Cost extension point (DEFERRED)
`evaluate_signals_frame(df, round_trip_cost_bps=0.0)` exists; later a `CostModel`
(spread+slippage+commission+swap) plugs in via a new param. No default cost, no invented
numbers; spread point-size UNRESOLVED until provided.

---

## 12. Transaction Cost Deferred Plan

- `TRANSACTION_COST_STATUS = DEFERRED`. No spread->cost conversion, no point-size assumption,
  no slippage/commission numbers.
- Facts locked: `<SPREAD>` exists but 88.8% zeros, integer points, point-size UNVERIFIED;
  `spread_relative` remains a FEATURE only.
- Keep `round_trip_cost_bps=0.0` default and a documented `CostModel` seam.
- Future activation requires: (a) point-size/spread units, (b) slippage model, (c) commission
  schedule, (d) swap rule — all as an explicit ratification step.

---

## 13. Authorization Integration

Audited: `authorization.py`, `readiness.py`, `configuration_freeze.py`, `timing_contract.py`,
`batch1_execution_runner.py`.

**Current state:** gate binds ONE execution id (`PREP-001`) to ONE frozen
`target_definition_version`; **no target_type dimension** -> **cannot distinguish T1 vs T3**.
GAP CONFIRMED.

**Required (design only) changes to close the gap:**
1. `authorization` must accept and verify `target_type in {T1,T3}` and compare against the
   sign-off's `target_type` + `target_definition_version` + `target_hash`.
2. One sign-off authorizes exactly one `(execution_id, target_type)`. A T3 sign-off must NOT
   authorize a T1 run and vice-versa (`TARGET_TYPE_MISMATCH`).
3. `configuration_freeze`/`canonical_config` must emit the correct `target_definition_version`
   for the requested target (currently frozen to T1 only).
4. `readiness.check_timing_ready` stays target-agnostic; TIMING contract should record the
   chosen contract (T3) explicitly.
5. `batch1_execution_runner` must pass `target_type` into `guard_execution_authorized`.

Gate is NOT disabled/bypassed; gap documented; its fix deferred to implementation with tests
(`TARGET_TYPE_MISMATCH`, cross-target rejection).

---

## 14. Database Compatibility

### 14.1 Can existing schema (v4) hold dual-target WITHOUT migration?
Partially — but NOT two jobs per (scope,symbol,timeframe,horizon).
- `job_key` is UNIQUE, free-text -> can encode target type
  (`legacy-plan-v3|T1|individual|EURUSD|M30|H2` vs `...|T3|...`). Distinguishable. OK.
- BUT `uq_training_job_tuple ON (scope, ifnull(symbol,''), timeframe, horizon)` (migration 003)
  -> **T1 and T3 for EURUSD/M30/h2 collide**; second insert ABORTS. **Cannot coexist.**
- `config_json` (jobs) / `training_config_json` (runs) are free-form -> can store target
  metadata, but do not enforce per-target uniqueness.
- `model_artifacts(artifact_type,...)` can hold `signals`/`report` for both, but
  `UNIQUE(run_id,artifact_type,artifact_path)` needs distinct path (target namespace solves it),
  and each needs its own run/job.
- `strategy_experiments(experiment_key UNIQUE, config_json, result_json, run_id)` can hold
  `PREP-001-T1-A` etc. as distinct experiment_keys (no migration for the matrix).

### 14.2 Options (owner decision; NO migration made here)
- **Option A (no migration):** store target tracks outside `training_jobs` (e.g. as
  `strategy_experiments` rows linked to distinct `run_id`s). Blocked by the tuple index unless
  only one target flows through `training_jobs` at a time.
- **Option B (requires migration v5, NOT executed):** relax/replace `uq_training_job_tuple` to
  include a `target_type` column (new column + index). Clean production shape but needs a new
  migration — explicitly out of scope.
- **Option C (artifact-first, no DB jobs yet):** run dual-target experiments as read-only
  research producing target-namespaced artifacts/signals under `reports/.../{t1,t3}/` and
  register identities in `strategy_experiments` only; do not create competing `training_jobs`.
  Lowest risk, defers schema decision.

**Recommendation (pending approval):** defer the DB/schema decision; prototype via **Option C**
(target-namespaced artifacts + `strategy_experiments` identity) so no migration and no
production-DB writes are needed. Promoting both targets to `training_jobs` requires migration v5
— a separate approved change.

---

## 15. File-by-File Implementation Plan

> "Proposed change" is DESIGN intent. Nothing is implemented in this task.

| File | Current behavior | Proposed change | Reason | Risk | Required tests |
|---|---|---|---|---|---|
| `nexora_learning/pipeline.py` | `prepare()` T1 only; split/wf purge by h | Add `target_type`+`TargetSpec`; T3 label `Open[t+h+1]/Open[t+1]-1`; effective horizon h+1 purge; target-namespaced paths | Core dual-target + T3 | HIGH | T1/T3 formula, mask, purge h in {1..48}, wf, leakage, artifact isolation, backward-compat |
| `nexora_vision/features.py` | target-agnostic trailing features | **No change** (reused) | Features shared | LOW | unchanged regression |
| `nexora_datahub/loader.py` | parses OHLC + sparse `<SPREAD>`; bar-open ts | Document bar-open; expose `bar_open_ts`/`bar_close_ts` helper | Prevent downstream phase bugs | LOW | ts semantics, spacing guard |
| `nexora_audit/experiment_config.py` | A/B/C params only | Add `experiment_id` `PREP-001-{T1\|T3}-{A\|B\|C}` + target-aware identity; keep A/B/C values | Experiment identity | LOW | identity uniqueness, hash determinism |
| `nexora_audit/timing_contract.py` | 11 fields, T3 not explicit | Add explicit T3 execution fields/values (entry Open[t+1], exit Open[t+h+1]) | Ratify T3 design | MEDIUM | hash stability, field presence |
| `nexora_audit/authorization.py` | single target version, single exec id | Add `target_type` binding + `TARGET_TYPE_MISMATCH`; per-(id,target) scope | Close T1/T3 gap | HIGH | cross-target rejection, mismatch |
| `nexora_audit/readiness.py` | timing gate target-agnostic | No logic change; surface target in evidence | Consistency | LOW | readiness unchanged |
| `nexora_audit/configuration_freeze.py` | freezes T1 target version | Emit per-target target version/hash; per-target split policy version | Correct versions | MEDIUM | version/hash determinism |
| `nexora_audit/canonical_config.py` | target version UNRESOLVED | Accept target_type; propose target version | Config completeness | MEDIUM | config hash completeness |
| `batch1_execution_runner.py` | gate before dispatch | Pass `target_type` to gate; target-aware guard | Enforce in-run | MEDIUM | runner refuses wrong target |
| `nexora_evaluator/trading.py` | gross + optional constant cost (unwired) | Wire gross-only T3 metrics; keep cost seam 0.0 | T3 report | LOW | gross correctness; cost=0 |
| `nexora_evaluator/metrics.py` | classification metrics | **No change** (reused) | Shared | LOW | unchanged |
| `tests/*` | existing suites | Add dual-target/isolation/purge/authorization tests | Safety | LOW | (see section 16) |

Note: NOT all listed files must change. `features.py` and `metrics.py` are expected to stay
untouched (reused). Minimum true surface: `pipeline.py` + `authorization.py` +
`experiment_config.py` + `configuration_freeze.py` + evaluator wiring + tests. This document
changes none of them.

---

## 16. Test Plan (isolated / temporary fixtures; no production state)

T1/T3 correctness
1. T1 formula == `Close[t+h]/Close[t]-1` (synthetic).
2. T3 formula == `Open[t+h+1]/Open[t+1]-1` (synthetic).
3. Binary labels `y=(ret>0)` for both.
4. Independent masks: T3 drops one extra trailing row vs T1.
5. Index alignment: label anchor row == prediction row (t=100 example).
6. Timestamp semantics: `ts` is bar-open; spacing == tf minutes.
7. Last-row masking: last h (T1) / h+1 (T3) unlabelled.
8. Missing OHLC / NaN / Inf / zero price -> row excluded (both).

Determinism and identity
9. `target_hash` determinism (same input -> same hash; T1 != T3).
10. Independent experiment identity `PREP-001-{T1,T3}-{A,B,C}` unique.

Purge / walk-forward (both targets)
11. Purge T1: `max(h,24)`, no leakage, h in {1,2,4,8,12,24,48}.
12. Purge T3: `max(h+1,24)`, no leakage, h in {1,2,4,8,12,24,48}; **explicitly h=24 -> purge 25**.
13. Walk-forward T1 and T3 geometry (chronological, expanding, purged).
14. No future leakage: `max(train)+effective_h < min(test)` per fold.

Isolation / integration
15. Artifact isolation: T1/T3 write distinct namespaced paths; no overwrite.
16. Authorization mismatch rejection: T3 sign-off cannot authorize T1 (and vice-versa);
    `TARGET_TYPE_MISMATCH` surfaced.
17. Backward compatibility: default `target="T1"` reproduces current `prepare` output.
18. (Isolated) DB compat: two `training_jobs` rows for same (scope,symbol,tf,h) violate
    `uq_training_job_tuple` — assert collision in a temp DB (proves Option B needed for
    coexistence; no production DB used).

All fixtures in `TemporaryDirectory`; no `train_one`, no `model.fit`, no production DB/CSV.
Total: 18 test groups (formula x2, labels, masks x2, alignment, ts, last-row, missing-OHLC,
hash determinism, identity, purge T1/T3, wf x2, leakage, isolation, auth mismatch,
backward-compat, db-compat).

---

## 17. Risks and Open Questions

1. **Schema collision (HIGH):** dual-target cannot both occupy `training_jobs` for EURUSD/M30/h2
   without migration v5. Owner decision (Option A/B/C). No migration made here.
2. **Authorization gap (HIGH):** gate cannot distinguish T1/T3 today; must be extended before
   safe dispatch of either target.
3. **Purge correctness (HIGH):** T3 effective horizon h+1 > embargo at h>=24 -> old `max(h,24)`
   under-purges. Must fix with per-target purge.
4. **Spread metadata (UNRESOLVED):** point-size/units unknown; cost stays DEFERRED.
5. **Split policy version drift (MEDIUM):** split policy becomes target-dependent; version ids
   re-derived per target.
6. **Artifact path migration (MEDIUM):** adding `/t1/`,`/t3/` namespaces changes new paths;
   tooling that globs old paths must be checked.
7. **Signals CSV label column (MEDIUM):** `realized_forward_return` must reflect the target
   (T1 close->close vs T3 open->open); consumers must not assume T1 semantics.
8. **h > 24 horizons (MEDIUM):** T3 purge = h+1; verify no future horizons regress.

---

## 18. Implementation Sequence (post-approval)

1. Add `TargetSpec` + `prepare(target=...)`; keep default T1 (backward compatible). Tests: 1-10.
2. Add per-target purge (h for T1, h+1 for T3) to `split_indices`/`walk_forward_scores`.
   Tests: 11-14.
3. Target-namespaced artifact paths + T3 gross metrics in evaluator. Test: 15.
4. `experiment_config` identity + `timing_contract` T3 fields + hash determinism. Tests: 9-10.
5. Authorization `target_type` binding + `TARGET_TYPE_MISMATCH`; runner passes target_type.
   Test: 16 and runner-refusal.
6. (Separate, only if owner chooses Option B) migration v5 for `target_type` in
   `training_jobs` — NOT part of this design's execution.

Each step gated by its own tests and a fresh `readiness` run; still BLOCKED until a verified
sign-off and READY_FOR_TRAINING exist.

---

## 19. Approval Checklist

- [ ] Owner approves the dual-target design (T1 + T3) and T3 execution contract.
- [ ] Owner chooses DB strategy: **Option C (recommended, no migration)** / A / B(migration v5).
- [ ] Owner confirms split-policy becomes target-dependent (new per-target version ids).
- [ ] Owner confirms transaction cost stays DEFERRED (no spread->cost, no point-size assumed).
- [ ] Owner confirms authorization gate must be extended (target_type aware) before any dispatch.
- [ ] Owner approves the test plan (section 16) and implementation sequence (section 18).
- [ ] Only AFTER written approval, implementation begins; training remains BLOCKED until
      sign-off + readiness PASS.

---

## FINAL STATUS

- Recommended Contract: **T3** (`entry Open[t+1]`, `exit Open[t+h+1]`) + dual target **T1+T3**.
- T1 formula: `Close[t+h]/Close[t]-1` (h=2: `Close[t+2]/Close[t]-1`).
- T3 formula: `Open[t+h+1]/Open[t+1]-1` (h=2: `Open[t+3]/Open[t+1]-1`).
- Migration required: **NO** for Option C prototype; **YES (v5)** only if both targets must live
  in `training_jobs` simultaneously (Option B) — not executed.
- Authorization gate must be updated: **YES** (currently cannot distinguish T1/T3).
- Production database touched: **NO** (read-only inspection only).
- Training run: **NO**. Source code changed: **NO**. Config changed: **NO**. Status changed: **NO**.

IMPLEMENTATION_DESIGN_STATUS: **AWAITING_OWNER_APPROVAL**
