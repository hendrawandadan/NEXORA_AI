# PREP-001 — SIGN-OFF PAYLOAD TEMPLATE & PROCEDURE

**Document type:** Template + procedure ONLY.
**Nothing here is signed, executed, or written into `config/governance/`.**
No HMAC key is created. No ratification file is created by these materials.
The human owner performs the signing step.

> This template prepares a sign-off so the owner can review and sign it. Creating the
> signed `config/governance/prep001_ratification.json` is a SEPARATE, HUMAN action and is
> the only remaining step to move `TIMING_READY` / `ACTUAL_AUTHORIZATION` from UNRESOLVED.

---

## 0. What the gate actually validates (read this first)

`nexora_audit.authorization.authorize_execution()` requires ALL of these to pass before it
returns `authorized=True`:

| Check | Bound value source | Notes |
|---|---|---|
| `signoff_present` / `signoff_valid` | `config/governance/prep001_ratification.json` | must exist + structurally valid |
| `signoff_ratified` | `integrity.status == "VERIFIED"` | HMAC-SHA256 with `NEXORA_GOVERNANCE_KEY` |
| `config_hash_binding` | **`canonical_config_hash(proposal)["hash"]`** (v1, `nexora-cfg-v1`) | **NOT** the freeze hash |
| `timing_contract_binding` | `governance.ratified_contract_hash(...)` | must equal `timing_contract_hash` in file |
| `contract_versions_binding` | `feature/target/split` **ids**: row-supplied **target-aware** ids if present, else frozen defaults | see §0.1 / §3 |
| `target_type_binding` | `target.target_type` in file matches row | T1 or T3 |
| `target_hash_binding` | `target_definition_version_for(target).hash` | TargetSpec hash |
| `experiment_candidate_binding` | `experiment_configuration.candidate` in {A,B,C} (and row candidate if supplied) | |
| `readiness_decision` | `run_all_gates(...)` == READY_FOR_TRAINING | needs TIMING_READY + DATASET_READY etc. |

### 0.1 Target-aware split identity (IMPORTANT — updated)

The split policy has **three distinct ids**; they are NOT interchangeable:

| Split id | Value | Where it comes from |
|---|---|---|
| **default (legacy)** | `split-27dd116e49698640` | `split_policy_version()` (no target) |
| **T1-aware** | `split-ae9a1a9b551884ce` | `split_policy_version_for("T1", 2)` |
| **T3-aware** | `split-4d4a794c0cc217d9` | `split_policy_version_for("T3", 2)` (effective horizon h+1) |

The runner now **threads the target-aware version ids** (`feature_set_version`,
`target_definition_version`, `split_policy_version`) plus `target_type` and
`experiment_candidate` into the row it submits to `authorize_execution`. The gate binds the
**row-supplied** ids when present, otherwise the frozen default. Therefore:

- A **T3 sign-off MUST** carry `split_policy_version = split-4d4a794c…` and
  `target_definition_version = target-…(T3-aware id)`.
- A **T1 sign-off MUST** carry `split_policy_version = split-ae9a1a9b…`
  (T1-aware is NOT the default `split-27dd116e…`).
- Dispatch MUST pass `--target-type T3` (and `--candidate A`). Without `--target-type`,
  `training_config` defaults to `"T1"` and a T3 sign-off will be rejected.

Generate these ids with `split_policy_version_for(tt, 2)` and
`target_definition_version_for(tt, 2)` — do not hardcode the default.

**Critical gotcha (verified):** `config_hash` (v1) includes `dataset_identity.absolute_path`
as a STRING, so the hash differs by path form (`.` vs absolute `D:\NEXORA_AI_v2`). You MUST
compute the `config_hash` with the **exact same `project_root` string** the runner will use.
Two observed values for the same repo:
- root `.` → `0db85bb939bc16b546f7cb7e76ec7ec743d6803c72abd015cea919d56307f95e`
- root `D:\NEXORA_AI_v2` (absolute) → `af380460cda95287fe5bd63a161efc7208359cc2c182da2f570676514b37862e`

Use the **absolute** form consistently (recommended) unless the runner is invoked with `.`.

---

## 1. Live binding values (recompute immediately before signing)

These were read from the current tree. **Recompute right before signing** with the same
`project_root` the runner uses, because the config hash is path-sensitive (see §0).

| Field | Example value (root `.`) | How to obtain |
|---|---|---|
| `config_hash` | `0db85bb9…` (root `.`) / `af380460…` (abs) | `canonical_config_hash(build_prep001_proposal(ROOT))["hash"]` |
| `feature_set_version` | `feat-e12cda69dfe04e45` | `feature_set_version()["id"]` |
| `target_definition_version` (T3) | `target_…` (T3-aware id) | `target_definition_version_for("T3",2)["id"]` |
| `target_definition_version` (T1) | `target-b9c8f231d7fb8dbe` (legacy id kept) | `target_definition_version_for("T1",2)["id"]` |
| `split_policy_version` (T3) | `split-4d4a794c0cc217d9` | `split_policy_version_for("T3",2)["id"]` |
| `split_policy_version` (T1) | `split-ae9a1a9b551884ce` | `split_policy_version_for("T1",2)["id"]` |
| `target.target_type` | `T3` | your choice (T3 recommended first) |
| `target.target_hash` (T3) | `d5f2c43434aa7c41eda5da11e3fae1d9ef896a12b5ad62bda7ca2d049595ff5d` | `target_definition_version_for("T3",2)["hash"]` |
| `target.target_hash` (T1) | `414c2147b5d59e111800fe7da1fd434bf033a816cbb8fbb5c94f101bbc3867a3` | `target_definition_version_for("T1",2)["hash"]` |
| `timing_contract_hash` | `d91ee608…`→ recomputed as *ratified* hash | see §2 two-pass |
| `experiment_configuration.candidate` | `A` | your choice A/B/C |

> `timing_contract_hash` is **not** the proposed hash. It must be the **ratified** hash
> computed by `governance.ratified_contract_hash(...)`, which folds in approver/decided_at
> and the chosen field values (see §2).

---

## 2. Two-pass timing hash (required)

Because `ratified_contract_hash` depends on `approver`, `decided_at`, `references`, and the
6 timing field values, you must:
1. Build the draft payload (without `timing_contract_hash`).
2. Load it via `governance.load_ratification` on the SAME root.
3. `ratified = governance.apply_timing_ratification(build_timing_contract(), rat)`
4. `info = governance.ratified_contract_hash(ratified, rat)` → use `info["hash"]` as
   `timing_contract_hash`.
5. Write it back into the payload, then HMAC-sign the whole payload.

A helper that performs this (computes the payload + signature given a key from the
environment) is provided below as a *template script*; it is NOT run for production and it
does NOT create a key.

---

## 3. Payload template (T3 recommended; replace approver/decided_at/candidate)

```json
{
  "approver": "<YOUR NAME>",
  "decided_at": "<2026-??-??T??:??:??Z>",
  "references": [
    "reports/retraining/execution_timing_contract.md",
    "reports/retraining/PREP001_BASELINE_IMPLEMENTATION_FINAL_AUDIT.md"
  ],
  "config_hash": "<RECOMPUTE with runner root; e.g. 0db85bb9... or af380460...>",
  "feature_set_version": "feat-e12cda69dfe04e45",
  "target_definition_version": "<target_definition_version_for('T3',2)['id']>",
  "split_policy_version": "split-4d4a794c0cc217d9",
  "timing_contract_hash": "<RATIFIED hash; see section 2>",
  "target": {
    "target_type": "T3",
    "target_hash": "d5f2c43434aa7c41eda5da11e3fae1d9ef896a12b5ad62bda7ca2d049595ff5d"
  },
  "timing_contract": {
    "decision_timestamp":             { "value": "bar_t+1_open" },
    "earliest_executable_timestamp":  { "value": "bar_t+1_open" },
    "execution_price_model":          { "value": "open_price" },
    "spread_usage":                   { "value": "deferred" },
    "slippage_usage":                 { "value": "deferred" },
    "cost_usage":                     { "value": "deferred" }
  },
  "walk_forward_reconciliation": "R1",
  "walk_forward_note": "<short note>",
  "experiment_configuration": {
    "candidate": "A",
    "production_freeze": false,
    "note": "PREP-001-T3-A first experiment; gross evaluation; costs deferred"
  },
  "integrity": {
    "mechanism": "hmac-sha256",
    "signature": "<hex HMAC-SHA256 over canonical_json(payload without 'integrity')>"
  }
}
```

Notes:
- `experiment_configuration.production_freeze` MUST be `false`.
- Do not add spread/slippage/commission as costs; they stay `deferred` (gross).
- `walk_forward_reconciliation` must be `R1`, `R2`, or `R3` (choose after reading
  `reports/retraining/walk_forward_reconciliation_report.md`).
- The `integrity.signature` is `hmac_sha256(key, canonical_json(payload_without_integrity))`
  where `canonical_json` = sorted keys, `separators=(",",":")`, no spaces
  (use `nexora_audit.canonical_config.canonical_json`).

---

## 4. Signing procedure (human performs; NOT done here)

1. Export the key in the shell session where you will verify (never commit it):
   - PowerShell: `$env:NEXORA_GOVERNANCE_KEY = "<your-secret>"`
2. Recompute the binding values on the SAME root the runner uses (absolute path recommended).
3. Fill the payload (§3), then compute the ratified `timing_contract_hash` (§2 two-pass).
4. Compute the HMAC signature over `canonical_json(payload without integrity)`.
5. Write the file to `config/governance/prep001_ratification.json`.
6. Verify (read-only, no dispatch):
   - `python -m nexora_audit all` → GOVERNANCE present/valid; `verify_signoff_integrity` status `VERIFIED`.
7. Re-run authorization dry-check to confirm `authorized=True` with NO training.

A verification-only snippet (does not sign, does not dispatch):

```python
import os, json
from pathlib import Path
from nexora_audit import governance, authorization as A
from nexora_audit.canonical_config import canonical_config_hash, build_prep001_proposal

ROOT = Path(r"D:\NEXORA_AI_v2")   # use the SAME root the runner uses (absolute)
rat = governance.load_ratification(ROOT)
print("present:", rat is not None, "valid:", rat.valid if rat else False,
      "problems:", rat.problems if rat else "-")
if rat:
    integ = A.verify_signoff_integrity(rat, ROOT)
    print("integrity:", integ["status"], integ["detail"])
    print("signed config_hash:", rat.get("config_hash"),
          "live:", canonical_config_hash(build_prep001_proposal(ROOT))["hash"])
```

> Reminder: a structurally valid JSON is NOT authorization. Only
> `integrity.status == "VERIFIED"` plus all bindings matching yields `authorized=True`.

---

## 5. What this template deliberately does NOT do

- Does not create `NEXORA_GOVERNANCE_KEY`.
- Does not write `config/governance/prep001_ratification.json`.
- Does not sign anything.
- Does not run training, dispatch, or promotion.
- Does not touch the production database.

Creating the signed ratification is the owner's decision and responsibility.
