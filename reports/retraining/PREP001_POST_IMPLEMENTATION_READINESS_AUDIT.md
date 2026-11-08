# PREP-001 — Post-Implementation Safety & Readiness Audit

**Scope:** Audit of the completed PREP-001 **Dual-Target (T1/T3)** implementation and
**migration v5**.
**Mode:** Read-only verification. All database work was performed on **temporary
SQLite fixtures** built from the repository migrations. The production database,
CSV, models, checkpoints, signals, and backups were **never written**.

- Audit date: (run-time) 2026
- Implementation state audited: `216 passed` full test suite
- Audited modules: `nexora_learning/targets.py`, `nexora_learning/pipeline.py`,
  `nexora_state_db/migrations/005__dual_target_training_jobs.sql`,
  `nexora_audit/{authorization,configuration_freeze,readiness,timing_contract,safety_probe}.py`,
  `nexora_evaluator/t3_evaluation.py`, `batch1_execution_runner.py`,
  `tests/test_dual_target_prep001.py`, `tests/test_dual_target_artifacts.py`

---

## 0. Absolute prohibitions — compliance

| Prohibition | Result |
|---|---|
| No `model.fit` executed | **COMPLIED** — only pure functions (`compute_target`, `split_indices`, `purge_bars`, `build_target_mask`) and SQL fixtures were run. The one place `model.fit` exists (inside `walk_forward_scores`/`train_one`) was **not called** during the audit. |
| No training executed | **COMPLIED** — `TRAINING_EXECUTED = NO` |
| No batch runner with `--execute` | **COMPLIED** — runner exercised only via in-process `run_runner` with a **patched training function that raises** to prove fail-closed. |
| No job dispatch | **COMPLIED** — `DISPATCH_EXECUTED = NO` |
| No sign-off / HMAC key created for production | **COMPLIED** — sign-offs only written into temp roots via the existing test harness; no production `config/governance` file created. |
| No promotion | **COMPLIED** — `PROMOTION_EXECUTED = NO` |
| No production DB change | **COMPLIED** — prod DB SHA-256 unchanged (see §8). |
| No CSV/model/checkpoint/backup change | **COMPLIED** |
| No PREP-001 status change to pass readiness | **COMPLIED** — readiness evaluated against repository truth only. |

---

## 1. Migration v5 (temporary databases only)

**File:** `nexora_state_db/migrations/005__dual_target_training_jobs.sql`
**Tests:** `tests/test_dual_target_prep001.py` + direct SQL audit script (temp dirs).

### 1.1 v4 → v5 applied on a temporary DB with 3 legacy jobs
| Check | Result | Evidence |
|---|---|---|
| v4 baseline version | 4 | `SELECT max(version)` on temp v4 DB |
| Migration applied | `[5]` | `MigrationManager(...).migrate()` |
| DB hash before | `53cb00cc351496fd0fceb458823b8ec32b1df7db0ebc366426812a79177cc0c8` | sha256 of temp file |
| DB hash after | `20ec5bb6639b6ce4e2addced142ee35bc1d1e0b939d6fab79e8bcfb97681003e` | sha256 (changed → migration wrote as expected) |
| Legacy rows backfilled | **all → T1** | `h1/h2/h4` rows all `target_type='T1'` |
| `target_type` column present | True | `PRAGMA table_info(training_jobs)` |
| `integrity_check` | `ok` | `PRAGMA integrity_check` |
| `foreign_key_check` | `[]` (clean) | `PRAGMA foreign_key_check` |
| Triggers preserved | 6 triggers present | `sqlite_master WHERE type='trigger'` |
| `training_job_datasets` links preserved | 3 rows | `SELECT count(*)` |

### 1.2 T1 and T3 coexist on the same tuple
- Inserted a T3 job sharing `(individual, EURUSD, M30, horizon=2)` with an existing T1 job.
- `SELECT count(*) ... WHERE horizon=2` → **2** (both live). **PASS.**

### 1.3 Duplicate within the same target rejected
- Second T1 job on the same tuple → `sqlite3.IntegrityError` on `uq_training_job_tuple`. **PASS.**

### 1.4 Invalid target rejected
- `target_type='T2'` → `sqlite3.IntegrityError` (CHECK constraint). **PASS.**

### 1.5 Failure atomicity (broken v5)
- A deliberately broken v5 (`SELECT * FROM nonexistent_boom_table`) raised `OperationalError`.
- After failure: `version=4`, **`target_type` column absent** → the failed migration rolled
  back cleanly and left no partial schema. **PASS.**

### 1.6 Manual rollback (documented) is viable
- DROP new indexes → recreate v4 unique index → delete `schema_migrations(version=5)`.
- Result: `version=4`, `integrity=ok`, the v4 single-target uniqueness invariant restored
  (a second job on the same tuple — any target — is again rejected). **PASS.**

---

## 2. Target integrity

**File:** `nexora_learning/targets.py`
**Tests:** `tests/test_dual_target_prep001.py`

| Check | Result | Evidence |
|---|---|---|
| T1 formula `Close[t+h]/Close[t]-1` | **PASS** | hand-verified for all t; NaN tail = h |
| T3 formula `Open[t+1+h]/Open[t+1]-1` | **PASS** | exact match at t=0,1,5,50,100; NaN tail = h+1 = 3 |
| T1 binary label | PASS | `y = (fwd>0)` where finite; `-1` sentinel elsewhere (2 tail) |
| T3 binary label | PASS | same rule; `-1` sentinel on 3 tail rows |
| Target masks independent | **PASS** | on 3000 bars: T1 mask=2799, T3 mask=2798; T3 ≤ T1 and trailing diff ≥ 1 (the extra h+1 row) |
| Target hashes distinct & deterministic | **PASS** | T1 `414c2147…`, T3 `d5f2c434…`; stable across calls; horizon-sensitive |
| Version ids distinct | **PASS** | `target-t1-…` vs `target-t3-…` |
| **No shared mutable target vector** | **PASS** | after mutating T3 output to 999, T1 output is byte-identical (NaN-safe compare). `fwd1 is not fwd3`, `np.shares_memory=False`. |
| T3 effective horizon = h+1 | **PASS** | `effective_horizon(T3,h)=3`, `effective_horizon(T1,h)=2` |

> Audit note: an initial `np.array_equal` check produced a **false alarm** because
> the T1 tail contains `NaN` and `NaN != NaN`. Re-run with `equal_nan=True` confirmed
> there is **no aliasing** between T1 and T3 arrays. This is a test-methodology note,
> not a product defect.

---

## 3. Leakage & temporal validation

**File:** `nexora_learning/pipeline.py` (`purge_bars`, `split_indices`, `walk_forward_scores`)

### 3.1 Purge = `max(effective_horizon, embargo)`
| h | T1 purge `max(h,24)` | T3 purge `max(h+1,24)` |
|---|---|---|
| 2 | 24 | 24 |
| 24 | 24 | **25** |
| 48 | 48 | **49** |

T3 never reuses the T1 `max(h,24)` rule. **PASS.**

### 3.2 Embargo 0 and 24 — no train/validation overlap
| Target / embargo | train label end < val start | val label end < test start | gap (val_start − last_train) |
|---|---|---|---|
| T1 / 0 | True | True | 3 (= h+1 clamp) |
| T1 / 24 | True | True | 25 |
| T3 / 0 | True | True | 4 (= (h+1)+1 clamp) |
| T3 / 24 | True | True | 25 |

Even with `embargo=0`, `split_indices` clamps the floor to the effective horizon, so no
label crosses the boundary. **PASS — no information overlap.**

### 3.3 Walk-forward boundary & timestamps
- Purge used: `max(effective_horizon, embargo)` (T3 uses h+1).
- Emulated folds (no fit): fold-1 train_last=3999 / test_start=4024; fold-2 5332/5357;
  fold-3 6665/6690 — **all strictly ordered** (test_start > train_last). **PASS.**
- Timestamps are strictly increasing in all split tests (`test_purge_boundary.py`).

---

## 4. Authorization

**File:** `nexora_audit/authorization.py`, `batch1_execution_runner.py`
**Tests:** `tests/test_execution_authorization.py`, `tests/test_dual_target_prep001.py`, plus direct matrix audit.

| Scenario | Result | Codes |
|---|---|---|
| T1 sign-off → T1 row | **authorized path** | `OK_TARGET_PRESENT`, `OK_TARGET_MATCH`, `OK_TARGET_HASH` |
| T1 sign-off → **T3** row | **REJECTED** | `TARGET_TYPE_MISMATCH` |
| T3 sign-off → T3 row | **no target mismatch** (target binding OK) | — |
| T3 sign-off → **T1** row | **REJECTED** | `TARGET_TYPE_MISMATCH` |
| Correct type, **wrong target hash** | **REJECTED** | `TARGET_HASH_MISMATCH` |
| **Missing target type** | **REJECTED** | `TARGET_TYPE_MISSING` |
| Runner, no sign-off, `execute=True` | **raise AuthorizationError**, training dispatch **never reached** (patched fn would have raised) | fail-closed |

The runner invokes `guard_execution_authorized()` **before** any STARTED transition /
training / validation / promotion; it is fail-closed by construction. **PASS.**

---

## 5. Execution safety (temporary databases)

**File:** `nexora_audit/safety_probe.py` (built on `create_dev_database` → temp DB only)

| Probe | Result | Evidence |
|---|---|---|
| Atomic single-active-attempt | **PASS** | partial unique index blocks a 2nd active run; `active_runs=1` |
| One active attempt per RUNNING job | **PASS** | `second_create_ok=False`, `second_claim=None`, `started_runs=1` |
| Lifecycle synchronization | **PASS** | run=`TRAIN_DONE` ⇔ job=`TRAIN_DONE` |
| Crash recovery | **PASS** | first=`recovered`, second=`already-promoted` (idempotent); no duplicate active run; no duplicate artifact; PROMOTED preserved |
| Aggregate `all_passed` | **True** | `run_claim_and_lifecycle_probes()` |

> Retry behavior is exercised by `test_retry_*` / checkpoint flow tests in the suite
> (all passing). Duplicate-dispatch prevention is enforced by the partial unique
> index (`uq_one_active_run_per_job`).

---

## 6. Configuration freeze & parameter status

**File:** `nexora_audit/configuration_freeze.py`, `canonical_config.py`, `timing_contract.py`
**Config hash:** `9432cc25e4476da3e7deabfbca92fb38e6da02f2e6f46f976a85d2fead24c4cf`
**Freeze complete:** **False** (`requires_decision = [max_depth, l1_regularization, decision_time_policy]`)

| Area | Parameter | Status |
|---|---|---|
| Feature configuration | `feature_set_version` = `feat-e12cda69dfe04e45` (29 cols) | **VERIFIED** (FROZEN) |
| Target definition version | `target_definition_version` (legacy T1) | **VERIFIED** (FROZEN) |
| Split policy | `split_policy_version`, `train/val_fraction`, `embargo_bars=24`, `walk_forward_folds=3` | **VERIFIED** (FROZEN) |
| Model configuration | engine=lightgbm, engine_version=4.7.0, objective=binary, learning_rate=0.03, num_leaves=15, min_child_samples=100, feature_fraction=0.8, bagging_fraction=0.8 | **VERIFIED** (FROZEN) |
| Model configuration (uncertain) | metric=binary_logloss, boosting_type=gbdt, early_stopping=false, walk_forward_min_train_fraction=0.5 | **INFERRED** (FROZEN) |
| Model configuration (**no evidence**) | `max_depth`, `l1_regularization` | **REQUIRES_DECISION** |
| Random seed | `random_seed = 42` | **VERIFIED** (FROZEN) |
| Decision timestamp policy | `decision_time_policy` | **UNRESOLVED** (REQUIRES_DECISION) |
| Dataset hash | `sha256_recomputed = e6729c4596f872f503cc04c7611375419395ab9cc92f9d918121609cdb282945` | **VERIFIED** (dataset manifest matches; DATASET_READY=PASS) |
| Target hash | T1 `414c2147…`, T3 `d5f2c434…` | **VERIFIED** (deterministic, distinct) |

**Timing contract fields:**
- PROVEN: candle_close_timestamp, feature_availability_timestamp, prediction_timestamp, prediction_horizon, no_future_information_rule
- **NEW_DESIGN (unresolved):** decision_timestamp, earliest_executable_timestamp, execution_price_model, spread_usage, slippage_usage, cost_usage

**No status was upgraded to VERIFIED without evidence.** `max_depth`, `l1_regularization`,
and `decision_time_policy` remain REQUIRES_DECISION/UNRESOLVED.

> CONFLICT check: none found among the frozen parameters — all consumed values match
> the live `config/research.json` proposal.

---

## 7. Readiness matrix

| Gate | Status | Detail |
|---|---|---|
| **DATASET_READY** | ✅ **PASS** | file exists, SHA matches manifest, interval PASS, schema valid, rows 70694 |
| **TARGET_READY_T1** | ✅ **PASS** | T1 hash `414c2147…`, effective horizon = 2 |
| **TARGET_READY_T3** | ✅ **PASS** | T3 hash `d5f2c434…`, effective horizon = 3 (h+1) |
| **TIMING_READY** | ⛔ **UNRESOLVED** | 6 design fields need human sign-off; not ratified |
| **CONFIG_READY** | ⛔ **FAIL** | incomplete manifest: max_depth, l1_regularization, decision_time_policy |
| **SPLIT_READY** | ✅ **PASS** | target-aware purge/embargo; no overlap at embargo 0/24; WF strictly ordered |
| **RUNNER_READY** | ✅ **PASS** | atomic claim + synchronized lifecycle |
| **RECOVERY_READY** | ✅ **PASS** | idempotent crash recovery; PROMOTED preserved |
| **AUTHORIZATION_READY** | ⚠️ **MECHANISM PASS / ACTUAL UNRESOLVED** | matrix fail-closed verified; no human ratification sign-off present |
| **ARTIFACT_READY** | ✅ **PASS** | `t1/` vs `t3/` namespaces isolated; schema v5 supports target_type |

**Aggregate gate decision (repository truth): `BLOCKED`** —
blocking gates: **CONFIG_READY (FAIL)**, **TIMING_READY (UNRESOLVED)**.
Training is **NOT** ready.

---

## 8. Production-untouched proof

**Production DB:** `database/nexora_state.db`

| Measurement | Value |
|---|---|
| SHA-256 (before audit) | `e314244ed46099abd0025e982640b9be7711f608ac9a75ff5b44e4d43286d6c6` |
| SHA-256 (after audit) | `e314244ed46099abd0025e982640b9be7711f608ac9a75ff5b44e4d43286d6c6` |
| Prod schema version | **2** (NOT migrated to v5) |
| Prod `training_jobs.target_type` | **absent** (untouched) |

All migration/probe work ran on `tempfile.TemporaryDirectory()` fixtures via
`create_dev_database` / `SQLiteConnectionManager`. Temporary DB hashes were captured
and recorded per fixture (see §1.1); those files were deleted after each check.

Test suite re-run after audit: **216 passed**.

---

## 9. BLOCKER findings

| # | Severity | Finding | Impact | Required action |
|---|---|---|---|---|
| B1 | **BLOCKER** | `CONFIG_READY = FAIL`: `max_depth`, `l1_regularization`, `decision_time_policy` have no evidence and remain REQUIRES_DECISION. | Freeze manifest incomplete → training blocked by design. | Human must supply explicit values via signed ratification (e.g. candidate B: max_depth=4, reg_alpha=0.1) and ratify decision_time_policy. Do NOT invent values. |
| B2 | **BLOCKER** | `TIMING_READY = UNRESOLVED`: 6 execution-timing fields (decision_timestamp, earliest_executable_timestamp, execution_price_model, spread/slippage/cost usage) are NEW_DESIGN and unratified. | Cannot claim execution-aligned (T3) results are decision-time-honest without a ratified timing contract. | Human sign-off on `execution_timing_contract.md`. |
| B3 | **BLOCKER** | `AUTHORIZATION_READY` actual status UNRESOLVED: no production ratification sign-off exists; no PREP-001 (T1 or T3) target is signed. | Real dispatch will (correctly) fail closed. | A human must produce a signed ratification bound to the chosen target hash. |

## 10. Non-blocking findings / code quality

| # | Severity | Finding | Action |
|---|---|---|---|
| N1 | MINOR | `nexora_learning/targets.py:146` contains dead code: `fwd[: n - span] = op[1 : n - horizon] / op[0 : n - span - 0] if False else np.nan`. Functionally harmless (overwritten by the explicit loop), but confusing. | Remove the dead line. |
| N2 | INFO | Freeze `feature_set_version`/`feature hash` is computed on the **legacy T1** target version; this is correct for the production freeze but T3's freeze manifest has not been emitted. | Note T3 freeze is implied by `target_definition_version_for('T3')`; emit an explicit T3 manifest when T3 is promoted to frozen. |
| N3 | INFO | `target_hash` in freeze shows T1 legacy id (`target-b9c8f231…`) which differs from the runtime `TargetSpec.target_hash` (`414c2147…`) because the freeze uses `TARGET_DEFINITION` dict, while `targets.py` uses its own canonical payload. Both are deterministic; the two hash schemes are distinct domains. | Document that freeze-manifest target hash ≠ `targets.TargetSpec` hash (governance binding uses the latter inside authorization — verified consistent there). |

> N3 is important context: authorization consistently uses
> `target_definition_version_for()` (the `targets.py` domain), which is what the
> §4 matrix tested — so binding is self-consistent. The freeze manifest uses a
> separate legacy domain; that is a documentation/clarity item, not a leak.

---

## 11. Recommended next steps

1. **Resolve B1** — obtain a human, signed decision for `max_depth`, `l1_regularization`,
   and `decision_time_policy`; re-emit the freeze manifest with those values; re-run
   `CONFIG_READY`.
2. **Resolve B2** — ratify the execution timing contract (all 6 NEW_DESIGN fields).
3. **Resolve B3** — produce a signed ratification for PREP-001 bound to the intended
   target (`target_hash` for T1 or T3).
4. Fix N1 (dead code in `compute_return_t3`) before any T3 promotion.
5. Re-run this audit after B1–B3 are resolved; only then consider a (separately
   authorized) staging dry-run. **Do not** run `--execute` until all required gates PASS.

---

## 12. Final status block

```
AUDIT_STATUS                = COMPLETE
IMPLEMENTATION_STATUS       = DUAL-TARGET IMPLEMENTED (T1/T3 core, migration v5, auth, evaluator)
                              — 216 tests passing; mechanism-level verified
PRODUCTION_DATABASE_UNTOUCHED = YES
  prod_db_sha256            = e314244ed46099abd0025e982640b9be7711f608ac9a75ff5b44e4d43286d6c6 (unchanged)
  prod_schema_version       = 2 (not migrated to v5)
TRAINING_EXECUTED           = NO
DISPATCH_EXECUTED           = NO
PROMOTION_EXECUTED          = NO
SIGNOFF_CREATED             = NO
FINAL_TRAINING_READINESS    = BLOCKED
  blocking_gates            = CONFIG_READY (FAIL), TIMING_READY (UNRESOLVED),
                              AUTHORIZATION_READY (actual sign-off UNRESOLVED)
  passing_gates             = DATASET_READY, TARGET_READY_T1, TARGET_READY_T3,
                              SPLIT_READY, RUNNER_READY, RECOVERY_READY, ARTIFACT_READY
```

**Training is NOT ready. No training, dispatch, or promotion was performed. The
production database was not modified (SHA-256 identical; schema still v2).**
