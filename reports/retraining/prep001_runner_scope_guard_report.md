# PREP-001 Runner Scope Guard — Implementation Report

Date: 2026-11-07
Scope: TASK A — implement `--execution-id` so PREP-001 is provably isolated from all other jobs, with
**no fallback to batch-wide execution**.

## 1. Problem (verified in source before change)

`batch1_execution_runner.py::load_batch_rows()` selected **every** row of the chosen batch from
`reports/retraining/batch_execution_log.csv`. The batch contains **37 Batch-1 jobs (PREP-001…PREP-037)**.
The only narrowing flag was `--limit N`, which truncates **by plan order**, not by job id. So a `--execute`
run (even with `--limit 1`) acted on *whatever job happened to be first*, with no guarantee it was PREP-001.

## 2. Change (production file, guarded by tests written first)

File: `batch1_execution_runner.py`

| Addition | Behaviour |
|---|---|
| `parse_execution_ids(value)` | Normalizes `None` / `"PREP-001"` / `"PREP-001,PREP-003"` / iterable → `set` or `None`. |
| `load_batch_rows(..., execution_ids=None)` | When a set is given: keep **only** rows whose `execution_id` ∈ set; compute `missing = set − present`; if any missing → `raise ValueError("...refusing batch-wide fallback")`. |
| `RunnerConfig.execution_ids` | New optional field (default `None`) — backward compatible for all existing constructions. |
| `run_runner()` | Passes `cfg.execution_ids` into `load_batch_rows`. |
| `--execution-id` CLI flag | Comma-separated ids; wired into `RunnerConfig`. |
| Usage help | Documented that unknown ids **raise** rather than fall back. |

Key invariant: **if `--execution-id` is supplied, selection = intersection only, and an unknown id is a hard
error — the runner never silently widens to the batch.**

## 3. Tests (written BEFORE implementation, isolated, dry-run only)

File: `tests/test_runner_scope_guard.py` — **9 passed**.
Uses `tmp_path` CSV fixtures (no production files), full schema via `ensure_schema`, **never** `--execute`,
and monkeypatches `run_production_pipeline_to_staging` to raise if training is ever reached.

| Test | Asserts |
|---|---|
| `test_parse_execution_ids_from_arg` | None/""/"PREP-001"/"A,B"/list → correct set/None |
| `test_batch_wide_when_no_scope` | No scope → all 3 fixture rows (documents old behaviour) |
| `test_scope_selects_only_requested` | Scope {PREP-001} → only PREP-001 |
| `test_scope_rejects_unknown_id_no_fallback` | Unknown id → `ValueError` (no fallback) |
| `test_scope_with_limit_never_leaks_other_jobs` | Scope {PREP-003} + limit → only PREP-003 |
| `test_runnerconfig_has_execution_ids_field` | Dataclass field present |
| `test_run_runner_dry_run_scoped_to_prep001` | Dry-run reports only PREP-001; training path raises if hit |
| `test_run_runner_unknown_scope_raises` | `run_runner` with unknown id raises |
| `test_parser_exposes_execution_id_flag` | `--execution-id PREP-001` parsed |

## 4. Live proof on real data (dry-run, production log untouched)

Real log + plan copied to a temp dir (production files NOT used as the working copy):

```
> python batch1_execution_runner.py --log <temp>\log.csv --plan <temp>\plan.csv --dry-run --execution-id PREP-001
PREP-001: DRY_RUN_QUEUED          # exactly ONE line, despite 37 Batch-1 rows
```

Unknown-id guard:

```
> python batch1_execution_runner.py ... --dry-run --execution-id PREP-999
ValueError: requested execution_id not found in batch 'Batch 1': ['PREP-999'] (refusing batch-wide fallback)
```

`--help` exposes `[--execution-id EXECUTION_ID]`.

## 5. Safety confirmation

- Only `--dry-run` was executed; **`--execute` was never run**.
- Production `batch_execution_log.csv` / `batch_retraining_plan.csv` / datasets were **read-only** (hashes
  unchanged — see implementation summary §Proofs).
- No PLANNED→QUEUED, no queue, no training.

## 6. Residual note (NOT in scope, flagged)

`--limit` still truncates by plan order and is independent of `--execution-id`. That is fine because the
scope filter already restricts candidates; but operators should always pass `--execution-id PREP-001` (not
`--limit`) to be provably isolated. This is documented in help text.
