# PREP-001 — BLOCKER RESOLUTION DECISION SHEET

**Document type:** Read-only analysis and decision proposal.
**Purpose:** Define the options to close blockers **B1 (model config)**, **B2 (execution
timing contract)**, and **B3 (authorization sign-off)** from
`reports/retraining/PREP001_POST_IMPLEMENTATION_READINESS_AUDIT.md`.
**Mode:** READ-ONLY. No configuration, database, authorization, or readiness status is
changed by this document. **No implementation. No training. No dispatch. No sign-off.**

> Nothing in this sheet authorises training. The recommended baseline is a *proposal*
> for the owner to approve — the example values mentioned in the audit are **not**
> assumed approved here.

---

## 0. Current verified state (evidence-backed)

Environment (verified from the running venv):
- `lightgbm = 4.7.0`, `scikit-learn = 1.9.1`, Python 3.14.
- `create_model()` (`nexora_intelligence/model.py`) selects **lightgbm** when importable
  (it is). Fallback branch is sklearn `HistGradientBoostingClassifier`.

Effective runtime model parameters (`model.py` + LightGBM 4.7.0 defaults):

| Parameter | Effective runtime value | Basis |
|---|---|---|
| engine | `lightgbm` | inferred (importable) → frozen |
| objective | `binary` | inferred (LGBMClassifier auto) → frozen |
| n_estimators / max_iter | `300` | explicit config |
| learning_rate | `0.03` | explicit (`model.py`) |
| num_leaves | `15` | explicit `model.py=15` (**library default is 31 — overridden**) |
| min_child_samples | `100` | explicit |
| colsample (feature_fraction) | `0.8` | explicit `colsample_bytree=.8` |
| subsample (bagging_fraction) | `0.8` | explicit `subsample=.8`, `subsample_freq=1` |
| reg_lambda (l2) | `5` | explicit `reg_lambda=5` (**library default is 0.0 — overridden**) |
| **max_depth** | **`-1` (unlimited)** | **library default; never set in `model.py`** |
| **reg_alpha (l1)** | **`0.0`** | **library default; never set in `model.py`** |
| random_state | `42` | explicit config |
| early_stopping | none/false | no eval_set / fallback `early_stopping=False` |

`config/research.json` contains **no** `max_depth`, **no** `reg_alpha`, **no**
`decision_time_policy` keys.

Freeze/readiness current values (verified):
- Freeze `config_hash` = `9432cc25e4476da3e7deabfbca92fb38e6da02f2e6f46f976a85d2fead24c4cf`, `complete=false`, `requires_decision=[max_depth, l1_regularization, decision_time_policy]`.
- Readiness: `CONFIG_READY=FAIL`, `TIMING_READY=UNRESOLVED`, `RUNNER/RECOVERY/DATASET=PASS`, overall `BLOCKED`.

---

## B1 — Model configuration decision options

For each parameter: **current value**, **what is actually proven by source code**, and
the **default vs explicit vs inferred** distinction.

### B1.1 `max_depth`

- **Current effective value:** `-1` (unlimited depth).
- **Proven by source:** `model.py` never passes `max_depth` to `LGBMClassifier`. LightGBM
  4.7.0 default for `max_depth` is `-1` (verified: `LGBMClassifier().max_depth == -1`).
- **Classification:** **library default** (inferred). NOT explicit. NOT frozen.
- **Practical effect:** with `num_leaves=15`, `max_depth=-1` is effectively bounded by
  leaf count anyway (a tree can't exceed ~15 leaves). `max_depth` therefore mostly acts
  as a secondary guard.

| Option | Value | Consequence |
|---|---|---|
| A1 | keep `-1` (unlimited) | Matches current runtime exactly. Reproducible if frozen as `-1`. Leaf cap (15) already regularises. **Fewest moving parts.** |
| A2 | `max_depth=4` | Tighter, more conservative trees; changes the model vs current behaviour; requires re-baselining any prior T1 numbers. |
| A3 | `max_depth=6` | Middle ground; still changes behaviour vs today. |

> The audit *example* (`max_depth=4`) is **not** assumed approved; it is one of several
> choices, all requiring explicit owner sign-off.

### B1.2 `l1_regularization` / `reg_alpha`

- **Current effective value:** `0.0` (no L1).
- **Proven by source:** `model.py` never passes `reg_alpha`. LightGBM default is `0.0`
  (verified). The **sklearn fallback has no L1 parameter at all**.
- **Classification:** **library default** (inferred). NOT explicit. NOT frozen.
- **Critical caveat:** `create_model()` receives **no argument** to set `reg_alpha`, and the
  current `create_model(engine, seed, max_iter)` signature has **no slot** for it. Setting a
  non-zero L1 requires a **code change** to `model.py` (and would be lightgbm-only; the
  fallback cannot honour it).

| Option | Value | Consequence |
|---|---|---|
| A1 | `0.0` (keep default) | Matches runtime today; no code change; reproducible by freezing `0.0`. L2=`5` already regularises. |
| A2 | `0.1` | Adds sparsity; **requires `model.py` change** + fallback divergence; changes behaviour; re-baseline needed. |
| A3 | `0.5` | Stronger sparsity; same code-change cost as A2; higher risk of underfitting the 29-feature set. |

### B1.3 `decision_time_policy`

- **Current value:** none (UNRESOLVED). No contract in `config/research.json`.
- **Proven by source:** the pipeline labels at bar-close (`close[t]`), features at bar
  close, but there is **no explicit rule** for when a signal becomes a decision and when it
  is executable. This is a **design decision**, not derivable from code.
- **Classification:** **UNRESOLVED** (no evidence either way).
- It is tightly coupled to **B2** (timing contract). Its resolution should be the *same*
  decision as the B2 `decision_timestamp` field so the two do not diverge.

| Option | Value | Consequence |
|---|---|---|
| A1 | `bar_open` (decision at open of t+1) | Matches the T3 design (entry Open[t+1]). Makes T3 decision-time-honest. Must align with B2. |
| A2 | `bar_close` (decision at close of t) | Simple; but for T3 the executable price is Open[t+1], so a close-decision must record an explicit delay. |
| A3 | `next_bar_open` explicit delay | Equivalent to A1 phrased as a delay; clearest for audit. |

**Recommendation for B1.3:** choose **A1/A3 (bar-open decision, executable at Open[t+1])**
to stay consistent with the T3 contract; do **not** pick a value that contradicts B2.

---

## B2 — Execution timing contract decision table

Design constraints that **must be preserved** (owner's decisions — treat as fixed):
- Timestamp convention = **bar-open**.
- T3 entry = **Open[t+1]**; T3 exit = **Open[t+h+1]**.
- Transaction costs = **deferred**.
- Initial T3 evaluation = **gross**, not net profitability.
- **T1/T3 formulas must not change.**

Source: `nexora_audit/timing_contract.py` (fields `PROVEN` vs `NEW_DESIGN`) and
`reports/retraining/execution_timing_contract.md`.

| Field | Current status | Candidate decision (aligned to owner constraints) | Consequence | Needs human approval? |
|---|---|---|---|---|
| `decision_timestamp` | NEW_DESIGN | Decision evaluated at **bar-open of t+1** (i.e. the same open used for T3 entry). Features/label are from bars ≤ t. | Binds the signal to the first executable price; no look-ahead. | **YES** |
| `earliest_executable_timestamp` | NEW_DESIGN | **Open of t+1** (identical to T3 entry). | Guarantees the label and the trade entry use the same price; prevents same-bar execution fantasy. | **YES** |
| `execution_price_model` | NEW_DESIGN | **Open price** at `t+1` (entry) and `t+h+1` (exit) for T3. For T1 evaluation this field is **N/A (statistical only)**. | T3 is execution-aligned; T1 remains a direction probe. | **YES** |
| `spread_usage` | NEW_DESIGN | **Not applied in initial gross T3** (recorded as `deferred`). | Gross results overstate net; must be labelled gross. | **YES** (confirm deferral) |
| `slippage_usage` | NEW_DESIGN | **Not applied in initial gross T3** (deferred). | Same as spread; deferred to a later net-evaluation phase. | **YES** (confirm deferral) |
| `cost_usage` | NEW_DESIGN | **Deferred** — T3 headline metrics are **gross**. | No net-profitability claim may be made from initial T3. | **YES** (confirm deferral) |

Notes:
- `candle_close_timestamp`, `feature_availability_timestamp`, `prediction_timestamp`,
  `prediction_horizon`, `no_future_information_rule` are already **PROVEN** and unchanged.
- `decision_timestamp` must equal/exceed the latest feature availability timestamp; with
  bar-open-of-t+1 this holds (features from bars ≤ t are known before t+1 open).
- **All six NEW_DESIGN fields still require explicit human ratification.** This sheet only
  proposes consistent values; it does not ratify them.

---

## B3 — Authorization procedure (PREP-001-T3-A and PREP-001-T1-A)

**No sign-off, HMAC key, or ratification file is created here.** This section describes
*how* the owner would produce them (future, separately-authorised action).

### Target hashes that would be bound

These are the **`TargetSpec` hashes** (`nexora_learning.targets` domain), which is exactly
what `authorize_execution()` verifies via `target_definition_version_for()`:

| Job | `target_type` | `target_hash` (bound in sign-off) | `target_definition_version_for().id` | effective horizon |
|---|---|---|---|---|
| **PREP-001-T1-A** | T1 | `414c2147b5d59e111800fe7da1fd434bf033a816cbb8fbb5c94f101bbc3867a3` | `target-b9c8f231d7fb8dbe` (legacy id) | 2 |
| **PREP-001-T3-A** | T3 | `d5f2c43434aa7c41eda5da11e3fae1d9ef896a12b5ad62bda7ca2d049595ff5d` | `target-t3-d5f2c43434aa7c41` | 3 |

Also bound by the same sign-off (for reproducibility): the **config hash**
`9432cc25…` (must be re-emitted *complete* after B1 resolution), and the
**feature/split versions** (`feat-e12cda69dfe04e45`, split `split-ae9a1a9b551884ce` for T1
/ `split-4d4a794c0cc217d9` for T3).

> ⚠️ **ID/hash domain inconsistency to resolve first (see Findings F2):** for **T1**,
> `target_definition_version_for("T1",2)` returns a legacy id (`target-b9c8f231…`) but the
> **hash** of the TargetSpec domain (`414c2147…`). Authorization checks the **hash**, so
> binding is self-consistent, but the displayed id ≠ hash domain. The owner should decide
> whether to keep the legacy id for T1 backward-compatibility (current behaviour) or
> unify to `target-t1-…`. This choice must be frozen before signing.

### Procedure (per job)

1. **Prerequisite:** B1 and B2 resolved; freeze manifest re-emitted with `complete=true`
   (all `requires_decision` supplied) → new `config_hash`.
2. Owner writes a ratification payload binding **exactly one** `target_type` +
   `target_hash` above, plus the complete `config_hash`, feature/target/split versions,
   the ratified timing contract hash, and the chosen experiment candidate (`A`).
3. Payload is **HMAC-SHA256 signed** with a key held by the owner (`NEXORA_GOVERNANCE_KEY`),
   written to `config/governance/prep001_ratification.json`.
4. `authorize_execution()` is then run read-only to confirm `authorized=true` **before** any
   dispatch. A T1 sign-off must reject a T3 row and vice-versa (verified in audit §4).
5. **This sheet does not perform steps 2–4.** They require explicit human action.

---

## Findings (additional)

### F1 — Dead code at `nexora_learning/targets.py:146`
Current:
```python
if span < n:
    fwd[: n - span] = op[1 : n - horizon] / op[0 : n - span - 0] if False else np.nan
```
- The `if False else np.nan` makes the entire assignment **always write NaN** and then
  the explicit `for` loop overwrites the valid entries. Functionally harmless (tests pass)
  but misleading and a maintenance hazard.
- **Proposed fix (future, not applied):** delete the dead line entirely; keep only the
  explicit loop (the loop already correctly computes `fwd[t] = op[t+1+h]/op[t+1]-1`).
- **Impact:** none on results; improves clarity. Should be fixed before T3 promotion.

### F2 — `configuration_freeze` hash vs `TargetSpec` hash (two domains)
- **`configuration_freeze.target_definition_version()`** hashes a `TARGET_DEFINITION` dict
  (`{"fwd_definition": "fwd[:-h]=close[h:]/close[:-h]-1", ...}`) → domain
  `nexora-cfg-freeze-v2` → T1 hash `b9c8f231…`.
- **`nexora_learning.targets.TargetSpec.target_hash()`** hashes its own canonical payload
  (`{"formula": "close_to_close", ...}`, `nexora-target-v1`) → T1 `414c2147…`, T3 `d5f2c434…`.
- **`target_definition_version_for("T1")`** returns the **legacy id** but the **TargetSpec
  hash** — a deliberate hybrid for backward-compat. `authorize_execution` uses the
  **hash** field, so it binds to `414c2147…` consistently.
- **Impact on authorization:** none (authorization is internally consistent on the hash).
- **Impact on reproducibility:** the freeze manifest records `target_version
  id = target-b9c8f231…` while authorization binds hash `414c2147…`; a reader could be
  confused. **Recommendation:** document the two domains explicitly, and when T3 is
  frozen, emit an explicit T3 freeze manifest so both targets have unambiguous ids.
  Optionally unify T1 to `target-t1-…` if backward-compat is not required.

### F3 — `create_model` has no `reg_alpha`/`max_depth` slot
- Because `create_model(engine, seed, max_iter)` passes fixed literals, any **non-default**
  `max_depth`/`reg_alpha` decision **cannot be applied without editing `model.py`**. If the
  owner keeps defaults (`-1`, `0.0`), only the **freeze** needs to declare them explicitly
  (no code change) — the cleanest path to reproducible baseline.

---

## Recommended baseline (simple + reproducible, owner to approve)

> The goal is the **smallest change set** that yields a reproducible, defensible baseline
> without altering current model behaviour — so previously produced T1 artefacts remain
> comparable.

| Parameter | Recommended value | Rationale | Code change needed? |
|---|---|---|---|
| `max_depth` | **`-1`** (freeze the current default) | Match today's runtime; leaf cap 15 already bounds trees. | No — freeze only |
| `l1_regularization` | **`0.0`** (freeze the current default) | Match today; L2=5 already regularises; avoids `model.py` change & fallback divergence. | No — freeze only |
| `decision_time_policy` | **`bar_open`** (aligned with B2 `decision_timestamp` = Open[t+1]) | Decision-time-honest for T3; consistent with entry price. | Timing contract ratification |
| T3 evaluation mode | **gross** (costs deferred) | Matches owner constraint; must be labelled gross. | No (already gross) |
| Authorization | **T3 first** (`PREP-001-T3-A`), hash `d5f2c434…` | T3 is the execution-aligned target of interest; T1 remains statistical probe. | Sign-off (owner) |

This baseline:
- Requires **no `model.py` change** (all values are current-effective defaults frozen
  explicitly).
- Requires **B2 timing ratification** and **freeze re-emission** to reach `complete=true`.
- Keeps T1 artefacts comparable; T3 becomes the execution-aligned evaluation.

---

## Unresolved owner decisions (must be signed; cannot be auto-decided)

1. **B1 — `max_depth`:** keep `-1` (recommended) vs `4`/`6` (behaviour change).
2. **B1 — `l1_regularization`:** keep `0.0` (recommended) vs non-zero (needs `model.py` edit).
3. **B1/B2 — `decision_time_policy`:** `bar_open` (recommended, aligned with T3) vs bar_close.
4. **B2 — ratify all six timing fields** (decision_timestamp, earliest_executable_timestamp,
   execution_price_model, spread_usage, slippage_usage, cost_usage) consistent with the
   bar-open / Open[t+1] / Open[t+h+1] / costs-deferred / gross design.
5. **B2 — confirm cost deferral** (spread/slippage/cost = deferred; T3 = gross).
6. **B3 — sign PREP-001-T3-A** (and optionally T1-A) bound to the stated target hash,
   after B1/B2 produce a complete config hash.
7. **F2 — T1 id domain:** keep legacy `target-b9c8f231…` id (backward-compat) or unify to
   `target-t1-…`.

---

## Exact files that would need changes in a future implementation

*(Listed for planning only — NOT modified here.)*

| Change | File | Nature |
|---|---|---|
| Freeze `max_depth=-1`, `l1_regularization=0.0` explicitly (baseline) | `nexora_audit/configuration_freeze.py` / `config/research.json` | Add explicit values so `requires_decision` clears; re-emit manifest |
| If non-default `max_depth`/`reg_alpha` chosen | `nexora_intelligence/model.py` | Add params to `create_model` signature + pass to `LGBMClassifier` |
| Ratify timing contract (six fields) | `reports/retraining/execution_timing_contract.md`, `nexora_audit/timing_contract.py` | Update field statuses to ratified (after sign-off) |
| B3 sign-off (human) | `config/governance/prep001_ratification.json` | **Created by owner only**, HMAC-signed |
| Remove dead code | `nexora_learning/targets.py:146` | Delete dead `if False else np.nan` line |
| Optional: unify T1 target id domain | `nexora_audit/configuration_freeze.py` (`target_definition_version_for`) | Align id to `target-t1-…` if backward-compat not needed |

No production database change is required for any of the above; freeze/ratification are
file artefacts, and `model.py` change (if any) is code.

---

## Final status

```
DECISION_SHEET_STATUS = READY_FOR_OWNER_REVIEW
TRAINING              = BLOCKED
```
