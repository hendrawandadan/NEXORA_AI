# NEXORA AI v2 — Schema V4 Regression Audit Report

Audit timestamp: 2026-11-07
Scope: the nine previously-failing legacy SQLite tests, all of which asserted schema **v3** behaviour while the
on-disk migrations now include `004__execution_safety_guards.sql` (schema **v4**).
Mode: read-only analysis + test runs. No production DB touched. No migrations modified.

---

## 0. Summary

| | Count |
|---|---|
| Legacy tests failing before this audit | 9 |
| Confirmed **stale (v3 assumptions)** | 9 |
| Confirmed **real regressions** | 0 |

Every one of the 9 failures was a **outdated test assumption**, not a code regression. Each test was updated
to assert the **correct v4 behaviour** — no assertion was weakened to force a pass; several were made
*stricter/more explicit* (e.g. asserting retry must carry a `retry_queue` audit; asserting the synchronized
lifecycle instead of a bare status write).

Result after fixes: the related regression suites run **41 passed**, and the whole test tree runs
**125 passed**.

---

## 1. What changed between v3 and v4 (the behaviour under test)

`004__execution_safety_guards.sql` introduces:

- `uq_one_active_run_per_job` — partial unique index: at most one active (QUEUED/STARTED) run per job.
- `training_runs_insert_guard` — a run can be inserted **only** when its job status is `QUEUED`
  (replaces the narrower `training_runs_reject_planned_job` that only blocked `PLANNED`).
- `training_runs_claim_guard` — a `QUEUED→STARTED` run update requires a `QUEUED` job.
- `training_jobs_status_transition` rewritten — `RETRY_PENDING→QUEUED` now **requires** a `retry_queue`
  audit row (parallel to `PLANNED→QUEUED` requiring `explicit_queue`).
- `training_runs_status_transition` rewritten — `RETRY_PENDING` runs are terminal (retry = new run).
- `checkpoints_transition_guard` dropped the `RETRY_PENDING→STARTED` checkpoint allowance.

The repository `append_checkpoint()` also now **synchronizes the job row** on each run transition
(`run_lifecycle_sync` audit); this was already present, but v3 schema tests did not exercise it.

---

## 2. Per-test analysis

Legend: **V3 assumption** = what the test expected; **V4 behaviour** = current truth; **Verdict**.

### 2.1 `tests/test_sqlite_foundation.py`

#### `test_07_checkpoint_transition_validation`
- V3 assumption: seed a QUEUED job+run, then `append_checkpoint(run,"STARTED")` then `("TRAIN_DONE")` should work.
- V4 behaviour: `append_checkpoint("TRAIN_DONE")` synchronizes the job to `TRAIN_DONE`, which requires the job
  to be `RUNNING`. A bare QUEUED job (no claim) is not RUNNING → `ValueError: Job … is not synchronized`.
- Verdict: **STALE**. Correct fix: claim the run first (job → RUNNING), then advance to TRAIN_DONE. Kept the
  invalid-transition assertion (`TRAIN_DONE→QUEUED` must raise).

#### `test_08_promoted_terminal_state`
- V3 assumption: same bare seed, walk QUEUED→STARTED→TRAIN_DONE→VALIDATED→PROMOTED by checkpoints alone.
- V4 behaviour: same job-sync requirement as 07; plus PROMOTED terminal enforced.
- Verdict: **STALE**. Fix: claim first, then TRAIN_DONE→VALIDATED→PROMOTED; terminal assertions kept.

#### `test_12_audit_log_integrity`
- V3 assumption: 2 audits for the run (STARTED, TRAIN_DONE) written directly by `append_checkpoint`.
- V4 behaviour: `STARTED` now arrives via the **claim** (checkpoint + audit), so writing STARTED again via
  `append_checkpoint` is not the chosen path; instead claim writes STARTED, then TRAIN_DONE.
- Verdict: **STALE**. Fix: claim first (produces the STARTED audit), then append TRAIN_DONE; still exactly
  2 run audits, still STARTED then TRAIN_DONE.

> Note: none of these three tests were weakened — the terminal/invalid-transition guarantees are preserved and
> now exercised on the *correct* lifecycle.

### 2.2 `tests/test_sqlite_schema_v3.py`

#### `test_v2_migration_preserves_rows_and_foreign_keys`
- V3 assumption: after migrating a v2 DB, `max(schema_migrations.version) == 3`.
- V4 behaviour: migrations now reach version **4**.
- Verdict: **STALE (version bump)**, not a regression — all data-preservation assertions still pass.
  Fix: expect `4`.

#### `test_planned_job_does_not_become_queued_or_claimable`
- V3 assumption: creating a run for a PLANNED job raises message matching `"PLANNED job"`.
- V4 behaviour: `training_runs_reject_planned_job` was dropped; `training_runs_insert_guard` now blocks the
  run with message `"training run can be queued only for a QUEUED job"`. Behaviour (blocked) is identical.
- Verdict: **STALE (message change)**. Fix: match the v4 message. Behaviour still asserted blocked.

#### `test_explicit_queue_and_atomic_claim_require_run`
- V3 assumption: exactly **1** `training_job` audit after queue+claim.
- V4 behaviour: claim writes a second `training_job` audit (`claim`, QUEUED→RUNNING) in addition to
  `explicit_queue`. So the correct count is **2** — this is the *stronger* invariant (run+job+audit atomically).
- Verdict: **STALE**. Fix: assert **2** audits (explicit_queue + claim), with an explanatory comment.

#### `test_promoted_job_is_terminal_even_for_replay`
- V3 assumption: after FAILED→RETRY_PENDING, directly `create_run(...)` for the RETRY_PENDING job.
- V4 behaviour: `training_runs_insert_guard` requires the job to be `QUEUED`; `RETRY_PENDING→QUEUED`
  requires a `retry_queue` audit. Direct create is rejected.
- Verdict: **STALE**. Fix: added a `retry_queue` audit + job→QUEUED before creating the retry run; the test
  now additionally asserts that re-queueing **without** the audit is rejected
  (`retry requires explicit retry_queue audit`). Terminal PROMOTED assertions unchanged.

### 2.3 `tests/test_sqlite_production_bootstrap.py`

#### `test_bootstrap_empty_database_has_full_schema_and_pragmas`
- V3 assumption: `result.schema_version == 3`.
- V4 behaviour: fresh bootstrap applies migration 004 → version **4**.
- Verdict: **STALE (version bump)**. Fix: expect `4`. All table/index/PRAGMA assertions still pass.

### 2.4 `tests/test_sqlite_runner_integration_design.py`

#### `test_failure_retry_history_and_job_run_state_transitions`
- V3 assumption: FAILED→RETRY_PENDING then directly `create_run(...)` for retry.
- V4 behaviour: retry run requires the job be QUEUED (via `retry_queue` audit).
- Verdict: **STALE**. Fix: insert `retry_queue` audit and set job QUEUED, then create/claim the retry run.
  The assertions on run history (`RETRY_PENDING`, `TRAIN_DONE`), `runner_transition` audit count, and
  checkpoint count are preserved.

---

## 3. Test-run evidence (actual)

### 3.1 Related regression suites (after fixes)
```
tests/test_sqlite_schema_v3.py
tests/test_sqlite_foundation.py
tests/test_sqlite_foundation_integration.py
tests/test_sqlite_production_bootstrap.py
tests/test_sqlite_runner_integration_design.py
→ 41 passed
```

### 3.2 Whole test tree
```
tests/  → 125 passed
```

### 3.3 Before fixes (recorded for transparency)
```
9 failed, 32 passed
```
Failures and root causes:
1. `test_07_checkpoint_transition_validation` — job-sync requires RUNNING (needs claim).
2. `test_08_promoted_terminal_state` — same.
3. `test_12_audit_log_integrity` — same (STARTED via claim).
4. `test_v2_migration_preserves_rows_and_foreign_keys` — version 3→4.
5. `test_planned_job_does_not_become_queued_or_claimable` — v4 guard message.
6. `test_explicit_queue_and_atomic_claim_require_run` — 1 vs 2 audits.
7. `test_promoted_job_is_terminal_even_for_replay` — retry needs retry_queue.
8. `test_bootstrap_empty_database_has_full_schema_and_pragmas` — version 3→4.
9. `test_failure_retry_history_and_job_run_state_transitions` — retry needs retry_queue.

---

## 4. Conclusion (Part C)

- All 9 failures are **stale v3 assumptions**, confirmed against the v4 migration source and reproduced.
- **No regressions** were found; v4 adds stricter, intentional invariants (single active attempt, synchronized
  lifecycle, audited retry, terminal RETRY_PENDING runs).
- Tests were updated to assert correct v4 behaviour; assertions were not weakened (several strengthened:
  audit-count invariant, retry-audit requirement).
- Full tree: **125 passed**.

No production database, migration, CSV, dataset, model, or backup was modified by this audit.
