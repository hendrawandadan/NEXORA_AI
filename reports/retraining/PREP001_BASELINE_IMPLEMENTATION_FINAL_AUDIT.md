# PREP-001 — BASELINE IMPLEMENTATION & FINAL READINESS AUDIT

**Document:** `reports/retraining/PREP001_BASELINE_IMPLEMENTATION_FINAL_AUDIT.md`
**Scope:** Implement the owner-approved baseline decisions (B1 model config, B2 timing
contract), fix the dead-code finding, and run a full readiness audit. Target: prepare
**PREP-001-T3-A EURUSD M30** to be *considered* for the first training run.
**Mode:** Implementation + read-only audit. **No training, dispatch, sign-off, HMAC,
promotion, or validation training.** Production DB/CSV/checkpoints/models/backups
untouched.

---

## 1. Executive Summary

The approved baseline was implemented without changing model behaviour and without
touching production. Configuration freeze is now **complete** and deterministic; the
timing contract is **owner-approved** (but *not* human-ratified, so TIMING_READY stays
UNRESOLVED); the T3 dead code was removed with numerically identical output; hash-domain
differences are documented; and T1/T3 freeze identities are complete and isolated.

- Full test suite: **231 passed** (217 prior + 14 new baseline tests; 3 stale test files
  updated to the new approved reality).
- `python -m nexora_audit all` exit code 0.
- **CONFIG_READY = PASS** (freeze complete, `requires_decision=[]`).
- **TIMING_READY = UNRESOLVED** (owner-approved ≠ human-ratified; no sign-off exists).
- **Overall decision = BLOCKED.** Training remains BLOCKED.

---

## 2. Approved Owner Decisions (implemented verbatim)

**B1 — Model configuration (frozen explicitly; runtime unchanged):**

| Parameter | Approved value | Runtime effective | Status |
|---|---|---|---|
| Engine | lightgbm | lightgbm 4.7.0 | frozen |
| max_depth | -1 | -1 | frozen (explicit) |
| l1_regularization / reg_alpha | 0.0 | 0.0 | frozen (explicit) |
| reg_lambda | 5 | 5 | frozen |
| num_leaves | 15 | 15 | frozen |
| learning_rate | 0.03 | 0.03 | frozen |
| min_child_samples | 100 | 100 | frozen |
| feature_fraction | 0.8 | 0.8 | frozen |
| bagging_fraction | 0.8 | 0.8 | frozen |
| random_state | 42 | 42 | frozen |
| n_estimators | 300 | 300 | frozen |
| objective | binary | binary (LGBMClassifier on binary target) | frozen |

No hyper-parameter optimisation was performed. `model.py` was **not** changed (the
baseline equals current-effective defaults, so no code edit was needed). Library versions
unchanged (lightgbm 4.7.0, scikit-learn 1.9.1).

**B2 — Execution timing contract (preserve formulas):**

| Field | Approved value |
|---|---|
| Timestamp convention | bar_open |
| decision_time_policy | bar_open |
| decision_timestamp | Open[t+1] |
| earliest_executable_timestamp | Open[t+1] |
| execution_price_model | Open price |
| T3 entry | Open[t+1] |
| T3 exit | Open[t+h+1] |
| spread_usage | deferred |
| slippage_usage | deferred |
| cost_usage | deferred |
| Initial T3 evaluation | gross |

Formulas preserved unchanged: **T1 = Close[t+h]/Close[t] − 1**; **T3 =
Open[t+h+1]/Open[t+1] − 1**. T1 stays statistical; T3 stays execution-aligned gross. No
cost is applied (no partial spread/slippage/commission). Results are **gross**, never
described as net profitability.

**No look-ahead:** the decision occurs at the **start of bar t+1** using features from bar
t (known at close of t). The Open[t+1] price is **not** assumed known before bar t+1
begins; earliest executable instant equals the decision instant (bar t+1 open), so there
is no same-bar execution and no future information use.

---

## 3. Files Modified

| File | Change | Why |
|---|---|---|
| `nexora_audit/canonical_config.py` | `max_depth`,`l1_regularization`,`decision_time_policy` → STATUS_VERIFIED with owner-approved evidence | B1/B2 freeze explicit |
| `nexora_audit/configuration_freeze.py` | `decision_time_policy` now flows to FROZEN when verified; added hash-domain docstring; added `build_target_freeze_identity()` | B1/B2 + Task D + Task E |
| `nexora_audit/timing_contract.py` | NEW `OWNER_APPROVED` status; six fields set to approved values; `ratified` stays False | B2 |
| `nexora_learning/targets.py` | Removed dead `if False else np.nan`; added hash-domain note | Task C + Task D |
| `tests/test_nexora_config_freeze_v2.py` | Updated 5 assertions to new approved (complete) reality | no-regression |
| `tests/test_nexora_execution_safety_freeze.py` | Updated 1 assertion (decision_time_policy no longer blocking in raw proposal) | no-regression |
| `tests/test_governance_ratification.py` | Reframed ratified-params tests onto a synthetic incomplete manifest | no-regression |
| `tests/test_prep001_baseline_implementation.py` | **New** 14 regression tests | Task C/B1/B2/E |
| `reports/retraining/PREP001_BASELINE_IMPLEMENTATION_FINAL_AUDIT.md` | This report | deliverable |

**Not modified:** `config/research.json`, `nexora_intelligence/model.py` (both byte-identical
to baseline). No production file changed.

---

## 4. Configuration Freeze Results

- New freeze hash (deterministic, v2): `3132cdd879628c0b7a131ceb3e445a7c44340aca7e13cc6f21988dead22bafed`
- **`complete = True`**, **`requires_decision = []`**.
- Explicitly FROZEN (origin VERIFIED): `max_depth=-1`, `l1_regularization=0.0`,
  `decision_time_policy=bar_open`, plus engine/objective/lr/leaves/etc.
- Runtime == frozen verified for all model params (test `test_frozen_manifest_matches_effective_runtime`).
- Fallback sklearn path: the freeze evidence for `l1_regularization` states the sklearn
  `HistGradientBoostingClassifier` has **no L1 parameter and does not honour the value** —
  no false claim of L1 support.
- `check_config_ready_freeze` → **PASS**.

> Note: the *raw canonical proposal* hash (`nexora-cfg-v1`, `af380460…`) remains
> incomplete on `feature_set_version/target_definition_version/split_policy_version`
> because those are resolved in the freeze manifest (v2), not the raw proposal. This is
> by design; readiness uses the freeze manifest and PASSes.

---

## 5. Timing Contract Results

- Contract hash (v1): `d91ee608571226ce9969f7893ab812bf9de304d8f1e33425df4d2926c8997c28`
- `owner_approved = True`, **`ratified = False`** (no HMAC sign-off), `new_design_fields = []`,
  `unresolved_fields = []`.
- Field status distinction honoured:
  - **PROVEN** (mechanically verifiable): candle_close_timestamp,
    feature_availability_timestamp, prediction_timestamp, prediction_horizon,
    no_future_information_rule.
  - **OWNER_APPROVED** (documented decision, NOT human-ratified): decision_timestamp,
    earliest_executable_timestamp, execution_price_model, spread_usage, slippage_usage,
    cost_usage.
- `check_timing_ready` → **UNRESOLVED** (correct: owner-approval without human ratification
  must not pass).

Status vocabulary used: *Implemented* (code), *Owner-approved* (this instruction),
*Mechanically verified* (tests), *Human-ratified* (**NOT done** — no sign-off created).

---

## 6. T1 / T3 Target Integrity

| Check | T1 | T3 |
|---|---|---|
| Formula | Close[t+h]/Close[t]−1 | Open[t+h+1]/Open[t+1]−1 |
| Unchanged? | YES | YES (verified against explicit formula for h=1,2,4,24) |
| effective horizon | h (2) | h+1 (3) |
| Target hash | `414c2147b5d59e11…` | `d5f2c43434aa7c41…` |
| Target definition version id | `target-b9c8f231d7fb8dbe` (legacy id) | `target-t3-d5f2c43434aa7c41` |
| Split policy version | `split-ae9a1a9b551884ce` | `split-4d4a794c0cc217d9` |
| Purge @ h=2 | 24 | 24 (max(h+1,24)) |
| Mask / no shared vector | correct / independent | correct / independent (extra trailing row) |

T1 and T3 hashes are unchanged from the previous audit. Formulas and masks not altered.

---

## 7. Hash Domain Documentation (Task D)

Two **distinct** hash domains are intentionally preserved:

1. **TargetSpec domain** (`nexora-target-v1`, `nexora_learning/targets.py`) — used by
   **authorization** and experiment identity:
   - T1 target hash = `414c2147b5d59e11…`
   - T3 target hash = `d5f2c43434aa7c41…`
2. **Freeze legacy domain** (`nexora-cfg-freeze-v2`,
   `nexora_audit/configuration_freeze.target_definition_version()`) — used only for the
   freeze manifest's backward-compatible id:
   - T1 id = `target-b9c8f231d7fb8dbe` (legacy, kept for continuity)

`target_definition_version_for()` returns the **legacy id** but the **TargetSpec hash** —
so `authorize_execution()` (which binds the *hash*) is internally consistent
(`414c2147…`/`d5f2c434…`). The two domains were **not** unified; no target hash, formula,
authorization binding, or experiment identity was changed to force ids to match.
Documented in code (docstrings) and here.

---

## 8. Dead Code Cleanup (Task C)

`nexora_learning/targets.py` — removed the dead line:
```python
fwd[: n - span] = op[1 : n - horizon] / op[0 : n - span - 0] if False else np.nan
```
The explicit loop is now the single source of truth for the T3 return. **Numeric output
unchanged** — regression tests `test_t3_dead_code_removed` and
`test_t3_formula_unchanged_matches_explicit_definition` prove it (h=1,2,4,24), and the
existing dual-target tests still pass.

---

## 9. Test Results

Full suite: **231 passed**, 40 warnings (pre-existing pandas deprecations), 0 failed.

New regression file `tests/test_prep001_baseline_implementation.py` (14 tests) covers:
- T3 dead code removed; T3 & T1 formulas unchanged; T3 effective horizon = h+1.
- Effective LightGBM config == frozen baseline (max_depth=-1, reg_alpha=0.0, reg_lambda=5, …).
- Freeze complete/deterministic; decision_time_policy=bar_open frozen.
- Timing owner-approved values; owner-approved-but-not-ratified; no look-ahead; open entry/exit.
- Costs deferred; T3 gross (no spread/commission/slippage in the return function).
- Per-target freeze identity isolated (T1 vs T3) and complete.

Updated (no-regression, to new reality): `test_nexora_config_freeze_v2.py` (5),
`test_nexora_execution_safety_freeze.py` (1), `test_governance_ratification.py` (2).

Authorization matrix: `tests/test_execution_authorization.py` **15 passed** (T1 sign-off
cannot authorize T3 and vice-versa; hash mismatch rejected; missing type rejected; runner
fail-closed without sign-off).

`python -m nexora_audit all` → exit code **0**.

---

## 10. Readiness Matrix

| Gate | Status | Evidence |
|---|---|---|
| **CONFIG_READY** | ✅ **PASS** | freeze complete, requires_decision=[] |
| **DATASET_READY** | ✅ **PASS** | sha `e6729c45…`, 70694 rows, interval PASS |
| **TARGET_READY_T1** | ✅ **PASS** | hash `414c2147…`, eff h=2 |
| **TARGET_READY_T3** | ✅ **PASS** | hash `d5f2c434…`, eff h=3 |
| **TIMING_READY** | ⛔ **UNRESOLVED** | owner-approved, **not human-ratified** |
| **SPLIT_READY** | ✅ **PASS** | target-aware purge (T3=h+1), no overlap, WF ordered |
| **RUNNER_READY** | ✅ **PASS** | atomic claim + synchronized lifecycle |
| **RECOVERY_READY** | ✅ **PASS** | idempotent crash recovery; PROMOTED preserved |
| **AUTHORIZATION_MECHANISM_STATUS** | ✅ **PASS** | T1↔T3 isolation + fail-closed verified |
| **ACTUAL_AUTHORIZATION_STATUS** | ⛔ **UNRESOLVED** | no ratification sign-off present |
| **ARTIFACT_READY** | ✅ **PASS** | `t1/` vs `t3/` isolated; experiment identity unique |

Per-target freeze identities:
- `PREP-001-T1-A`: target `414c2147…`, config `3132cdd8…`, feature `feat-e12cda69…`,
  split `split-ae9a1a9b…`, timing `d91ee608…`, dataset `e6729c45…`, ns `t1`, signoff=False.
- `PREP-001-T3-A`: target `d5f2c434…`, config `3132cdd8…`, feature `feat-e12cda69…`,
  split `split-4d4a794c…`, timing `d91ee608…`, dataset `e6729c45…`, ns `t3`, signoff=False.

**Aggregate decision: BLOCKED** (blocking: TIMING_READY; ACTUAL_AUTHORIZATION UNRESOLVED).

---

## 11. Production Safety Proof

| Artifact | Before | After | Verdict |
|---|---|---|---|
| Prod DB SHA-256 | `e314244ed46099abd0025e982640b9be7711f608ac9a75ff5b44e4d43286d6c6` | `e314244ed46099abd0025e982640b9be7711f608ac9a75ff5b44e4d43286d6c6` | **UNCHANGED** |
| Prod schema version | 2 | 2 | **UNCHANGED** (not migrated to v5) |
| Prod `training_jobs.target_type` | absent | absent | **UNCHANGED** |
| Ratification file | absent | absent | **NOT CREATED** |
| `models/` | hash `dcfd0214…`, 249 files | same | **UNCHANGED** |
| `signals/` | hash `e3c0611a…`, 162 files | same | **UNCHANGED** |
| `backups/` | hash `d326c297…`, 65 files | same | **UNCHANGED** |
| `reports/retraining/staging` | absent | absent | **UNCHANGED** |
| `config/research.json` | sha `a2aa8d18…` | same | **UNCHANGED** |
| `nexora_intelligence/model.py` | sha `8391657d…` | same | **UNCHANGED** |

Only intended source files changed (timing_contract, configuration_freeze, canonical_config,
targets) + tests. All changes are on temp-DB fixtures only. No training artifacts created.

---

## 12. Remaining Blockers

1. **B3 / ACTUAL_AUTHORIZATION — UNRESOLVED.** No human ratification sign-off exists for
   PREP-001-T3-A (or T1-A). Required before any dispatch: owner writes and **HMAC-signs**
   `config/governance/prep001_ratification.json` binding the chosen `target_type` +
   `target_hash` (T3 = `d5f2c434…`), the complete `config_hash` (`3132cdd8…`), and the
   ratified timing contract hash (`d91ee608…`). **Not created here.**
2. **TIMING_READY — UNRESOLVED** until that human ratification exists (owner-approved ≠
   human-ratified). The timing gate will remain UNRESOLVED by design until a sign-off is
   present.

No other gates are blocking. CONFIG/DATASET/TARGET/SPLIT/RUNNER/RECOVERY/ARTIFACT pass.

---

## 13. Recommended Next Action

1. **Owner:** review this baseline; confirm the freeze manifest (`3132cdd8…`) and timing
   contract (`d91ee608…`) reflect the approved decisions.
2. **Owner:** produce the signed ratification for **PREP-001-T3-A** (target hash
   `d5f2c434…`) — this is the only remaining step to move TIMING_READY and
   ACTUAL_AUTHORIZATION from UNRESOLVED.
3. **Then (separately authorised):** re-run `python -m nexora_audit all`; only if all gates
   PASS may a (further-authorised) staged dry-run be considered. **Do not** run
   `--execute`/training until then.

---

## 14. Final Status Block

```
IMPLEMENTATION_STATUS        = BASELINE_IMPLEMENTED (B1/B2 applied; dead code fixed;
                               hash domains documented; T1/T3 freeze identities complete)
CONFIG_READY                 = PASS
TIMING_READY                 = UNRESOLVED   (owner-approved, not human-ratified)
DATASET_READY                = PASS
TARGET_READY_T1              = PASS
TARGET_READY_T3              = PASS
SPLIT_READY                  = PASS
RUNNER_READY                 = PASS
RECOVERY_READY               = PASS
AUTHORIZATION_MECHANISM_STATUS = PASS
ACTUAL_AUTHORIZATION_STATUS  = UNRESOLVED   (no ratification sign-off)
ARTIFACT_READY               = PASS

PRODUCTION_DATABASE_UNTOUCHED = YES
TRAINING_EXECUTED            = NO
DISPATCH_EXECUTED            = NO
PROMOTION_EXECUTED           = NO
SIGNOFF_CREATED              = NO
FINAL_TRAINING_READINESS     = BLOCKED
```

**Training remains BLOCKED.** The only path forward is the human-ratified sign-off for
PREP-001-T3-A; nothing in this work authorises training, dispatch, or promotion.
