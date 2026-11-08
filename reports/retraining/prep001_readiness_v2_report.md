# NEXORA AI v2 — PREP-001 Readiness V2 Report

Audit timestamp: 2026-11-07
Mode: `python -m nexora_audit readiness` (read-only; probes use temporary SQLite DBs; **no training**).
Continuation of `execution_safety_configuration_freeze_report.md` and `configuration_freeze_v2_report.md`.

---

## 0. Decision

**BLOCKED** — `ready_for_training: false`.

| Gate | Status | Reason |
|---|---|---|
| CONFIG_READY | **FAIL** | Max_depth, reg_alpha (no evidence) and decision-time policy undecided |
| DATASET_READY | **PASS** | SHA-256 matches, schema/interval/row-count verified |
| TIMING_READY | **UNRESOLVED** | Timing contract proposed but **not ratified** (6 NEW_DESIGN fields) |
| RUNNER_READY | **PASS** | Atomic single-active-attempt + synchronized lifecycle verified |
| RECOVERY_READY | **PASS** | Crash recovery idempotent; PROMOTED preserved; no duplicate artifact/run |

Blocking gates: **CONFIG_READY, TIMING_READY**. No training was run; no gate was forced to pass.

---

## 1. Actual CLI output

Command: `python -m nexora_audit readiness`

```json
{
  "freeze_hash": {
    "hash": "9432cc25e4476da3e7deabfbca92fb38e6da02f2e6f46f976a85d2fead24c4cf",
    "hash_version": "nexora-cfg-freeze-v2",
    "complete": false,
    "requires_decision": ["max_depth", "l1_regularization", "decision_time_policy"]
  },
  "timing_contract": {
    "hash": "f460fa9fa77c5d652be068dd6cb8c8428d94325ccfb2d97cddbe9ba482b0111f",
    "hash_version": "nexora-timing-v1",
    "ratified": false,
    "new_design_fields": [
      "decision_timestamp", "earliest_executable_timestamp", "execution_price_model",
      "spread_usage", "slippage_usage", "cost_usage"
    ],
    "unresolved_fields": [
      "decision_timestamp", "earliest_executable_timestamp",
      "spread_usage", "slippage_usage", "cost_usage"
    ]
  },
  "readiness": {
    "gates": {
      "CONFIG_READY": "FAIL",
      "DATASET_READY": "PASS",
      "TIMING_READY": "UNRESOLVED",
      "RUNNER_READY": "PASS",
      "RECOVERY_READY": "PASS"
    },
    "ready_for_training": false,
    "decision": "BLOCKED",
    "blocking_gates": ["CONFIG_READY", "TIMING_READY"]
  }
}
```

---

## 2. Gate-by-gate explanation

### CONFIG_READY — FAIL
The freeze manifest (`configuration_freeze_v2_report.md`) pins 26 evidenced parameters but reports
`complete:false` because three items are undecided:
- `max_depth` — never set in code (LightGBM default `-1`), so freezing it would invent a value.
- `l1_regularization` (reg_alpha) — never set (default `0.0`).
- `decision_time_policy` — depends on the timing contract being ratified.

This is a deliberate, correct failure: the task forbids freezing parameters without evidence.

### DATASET_READY — PASS
- File exists: `data/raw/EURUSD/EURUSD_M30_202001020000_202611062130.csv`.
- SHA-256 recomputed: `e6729c4596f872f503cc04c7611375419395ab9cc92f9d918121609cdb282945`.
- Matches the audit manifest: `schema_valid=true`, `interval_check=PASS`, `rows_valid_unique=70694`.
- No dataset file was modified.

### TIMING_READY — UNRESOLVED
The timing contract (`execution_timing_contract.md`) proves the no-future-information part (features trailing,
label masked, split purged) but leaves 6 execution-policy fields as NEW_DESIGN (decision clock, earliest
execution time, execution price, spread, slippage, cost). Because the contract is `ratified:false`, this gate
cannot pass. These are genuine design decisions, not inferable facts.

### RUNNER_READY — PASS
Isolated probes against temporary DBs built from the repo migrations confirm:
- `single_active_attempt_enforced` — partial unique index + claim guard allow ≤ 1 active attempt/job.
- `running_job_claim_rejected` — a RUNNING job cannot be claimed again.
- `lifecycle_synchronized` — checkpoint transitions update run and job together.
Proven at the SQLite (schema/trigger) boundary, not merely in Python pre-checks.

### RECOVERY_READY — PASS
Isolated crash-recovery probe (moved file, crash before DB commit, recovery run twice):
- `idempotent:true`, `no_duplicate_active_run:true`, `no_duplicate_artifact:true` (ACTIVE=1),
  `promoted_terminal_preserved:true`.

> Scope caveat: RUNNER/RECOVERY PASS reflect **isolated probes**, not a production-integration run. They prove
> the schema/trigger and recovery algorithm, not a shipped production runner end-to-end.

---

## 3. Test results (actual)

```
tests/  → 125 passed
```

Breakdown of relevant suites:
- Config freeze + timing + readiness + probes: `tests/test_nexora_config_freeze_v2.py` (12) +
  `tests/test_nexora_execution_safety_freeze.py` (18).
- Schema v4 regression suites: 41 passed (see `schema_v4_regression_report.md`).
- Dashboard + others: included in the 125 total.

---

## 4. What must happen to reach READY_FOR_TRAINING

1. **CONFIG**: a human decides explicit `max_depth` and `reg_alpha` (or records explicit acceptance of the
   defaults), then the freeze `complete` flag flips. Optionally reconcile `walk_forward.min_train_fraction`
   (config says 0.5; pipeline hardcodes 0.50 — no behavioural change, but should be signed).
2. **TIMING**: ratify the execution timing contract — accept/override the 6 NEW_DESIGN fields and add the
   purge-boundary + execution-price tests listed in `execution_timing_contract.md §5`.
3. Re-run `python -m nexora_audit readiness` until all five gates PASS.
4. Obtain **explicit approval** before any training or production runner integration.

---

## 5. Boundaries honoured

- No training; `train_one()` / `model.fit()` never called.
- Production DB not modified; probes used temporary DBs only.
- CSV, dataset, model, backup, and `config/research.json` unchanged.
- Production runner not enabled; PLANNED status not changed to QUEUED.
- Isolated probes are reported as probes, not as production integration evidence.

**Final: BLOCKED.** Halting after audit and testing, awaiting explicit approval.
