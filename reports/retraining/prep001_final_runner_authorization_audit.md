# PREP-001 Final Runner Authorization Audit

Date: 2026-11-07
Scope: TASK 1 — audit apakah `batch1_execution_runner.py` memvalidasi authorization sebelum claim & dispatch.
**No `--execute` was run.** Dry-run is NOT treated as end-to-end execution proof.

Method: source inspection of the runner and `nexora_audit/*`, plus isolated tests (already green, 34+34).
No training, no queue, no DB/CSV/dataset/model/backup mutation.

---

## 1. What the runner validates today (source-verified)

`batch1_execution_runner.py` validates exactly these inputs before acting:

| Control | Enforced? | Where |
|---|---|---|
| execution_id present | **Partial** — `--execution-id` filters rows and raises on unknown id | `parse_execution_ids()` + `load_batch_rows(execution_ids=…)` |
| Batch identity | **Yes (loose)** — `row["batch"] == batch_name` AND `run_key(row) in plan_map` | `load_batch_rows()` |
| Job identity (symbol/tf/horizon) | **Yes (plan-map join)** — row must map to a plan key | `run_key()` + `plan_map` |
| Job lifecycle status | **Yes** — `process_run()` transitions by `checkpoint_status` | `process_run()` |
| Retry/recovery scope | **Partial** — `--resume` skips PROMOTED; FAILED → manual review | `run_runner()` selection |
| max_iter gate | **Yes** — rejects full training if `max_iter != 300` | `run_runner()` |

## 2. What the runner does NOT validate (critical gap)

**The runner does not import or consult `nexora_audit` at all.** grep for
`nexora_audit|governance|readiness|config_hash|ratif` inside `batch1_execution_runner.py` returns **nothing**.
Therefore, before dispatch, the runner does **NOT** verify:

| Missing authorization binding | Consequence |
|---|---|
| **Governance sign-off** (`prep001_ratification.json`) | Runner will dispatch even if no human sign-off exists. |
| **Config hash** match | Runner will dispatch even if config drifted from a frozen/ratified hash. |
| **Timing contract version / ratified status** | Runner does not check TIMING_READY at all. |
| **Split/feature/target policy version** | Runner does not bind to the versioned split/feature/target IDs. |
| **Experiment candidate binding** | Runner does not check which A/B/C an execution is authorized under. |
| **RUNNER_READY probe result** | Runner does not require the claim/recovery probe to have passed. |

**Conclusion:** authorization binding is **INCOMPLETE**. The scope guard (Tugas A prior) correctly prevents
"wrong job" leakage, but it does **not** gate execution on human sign-off, config hash, timing ratification, or
the versioned contracts. There is a real path where `--execute --execution-id PREP-001` could run with **no
governance sign-off and no config-hash check.** (This is safe today only because there is no sign-off and
readiness is BLOCKED, but the runner itself does not enforce it.)

## 3. Can any path bypass the scope guard?

Scope guard is enforced in `load_batch_rows()` and is the **single funnel** every `run_runner()` call goes
through. There is no alternate selection path:

- `run_runner()` → `load_batch_rows(..., execution_ids=cfg.execution_ids)` (only selector).
- `process_run()` only ever receives rows from that filtered list.
- Tests `test_scope_rejects_unknown_id_no_fallback`, `test_run_runner_unknown_scope_raises` prove no batch-wide
  fallback.

So the **scope** portion cannot be bypassed. But scope ≠ authorization: the missing checks in §2 are simply
**not implemented**, not bypassable — they don't exist yet.

## 4. Recommendation (NOT implemented — needs human approval)

Add an explicit **authorization gate** at the top of `run_runner()` (before any `process_run`), that refuses to
dispatch unless **all** of the following match a signed ratification:

1. `job_identity` (job_key/PREP-001/symbol/tf/horizon) == ratified job in sign-off.
2. `batch_name` == ratified batch id.
3. `canonical_config_hash(proposal)["hash"]` == hash recorded in sign-off (and is `complete`).
4. `timing_contract` ratified hash == sign-off timing hash.
5. `split_policy_version` / `feature_set_version` / `target_definition_version` IDs == sign-off.
6. `experiment_candidate` (A/B/C) == sign-off candidate (as experiment only).
7. `readiness().decision == READY_FOR_TRAINING`.

Proposed signature (design only):

```python
def authorize_execution(cfg, plan_map, proposal, frozen, timing, ratification) -> None:
    """Raise AuthorizationError unless the run is fully bound to a valid sign-off."""
    # 1..7 above; any mismatch or absent sign-off => raise. Never defaults to allow.
```

## 5. Isolated test recommendations (to be written WITH the gate, not before sign-off exists)

- `test_runner_refuses_without_ratification`: no `prep001_ratification.json` → `run_runner(--execute)` raises
  `AuthorizationError` (use a temp log; never real log).
- `test_runner_refuses_on_config_hash_mismatch`: tamper proposal → mismatch → raises.
- `test_runner_refuses_on_timing_unratified`: timing `ratified:false` → raises.
- `test_runner_refuses_wrong_candidate`: sign-off candidate B but cfg requests A → raises.
- `test_runner_authorizes_only_fully_bound`: all 1..7 match → passes gate (still dry-run, no training).

These are **not yet added** because the gate must not be introduced as a production change without human
approval; and adding tests for a non-existent gate would be misleading. The **scope-guard** tests already exist
and pass (9 tests).

## 6. Dry-run is not execution proof

All prior evidence used `--dry-run` on temp logs. That proves **selection** and **that dry-run does not train**,
but it does **NOT** prove end-to-end authorization or execution. This audit explicitly does not equate the two.

## 7. Status

- Runner **scope** authorization: **PRESENT** (no bypass path).
- Runner **governance/config/timing** authorization: **ABSENT** → authorization binding **INCOMPLETE**.
- Recommendation and isolated-test plan provided. **No production code changed in this task.**
