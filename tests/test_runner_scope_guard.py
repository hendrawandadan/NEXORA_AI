"""Isolation tests for the PREP-001 runner scope guard (--execution-id).

SAFETY:
* Uses a TemporaryDirectory for the plan + log fixtures. Never touches the
  production CSV/dataset/model/backup.
* Dry-run only. NEVER passes --execute. NEVER calls train_one / model.fit.
* Verifies that when an execution-id scope is supplied, ONLY that row is
  selected and there is NO fallback to batch-wide execution.
"""
from __future__ import annotations

import csv
from pathlib import Path

import pytest

import batch1_execution_runner as runner

LOG_FIELDS = [
    "execution_id", "run_id", "batch", "checkpoint_group", "scope", "symbol", "timeframe",
    "horizon", "planned_action", "run_status", "checkpoint_status",
]


def _write_plan(path: Path) -> None:
    rows = [
        {"batch": "Batch 1", "order": "1", "scope": "individual", "symbol": "EURUSD", "timeframe": "M30", "horizon": "2"},
        {"batch": "Batch 1", "order": "2", "scope": "individual", "symbol": "EURUSD", "timeframe": "M30", "horizon": "4"},
        {"batch": "Batch 1", "order": "3", "scope": "individual", "symbol": "EURUSD", "timeframe": "M20", "horizon": "2"},
    ]
    with path.open("w", newline="", encoding="utf-8") as h:
        w = csv.DictWriter(h, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)


def _write_log(path: Path) -> None:
    rows = [
        {"execution_id": "PREP-001", "run_id": "PREP-001", "batch": "Batch 1", "checkpoint_group": "Batch 1::M30",
         "scope": "individual", "symbol": "EURUSD", "timeframe": "M30", "horizon": "2",
         "planned_action": "TRAIN", "run_status": "PENDING", "checkpoint_status": "QUEUED"},
        {"execution_id": "PREP-002", "run_id": "PREP-002", "batch": "Batch 1", "checkpoint_group": "Batch 1::M30",
         "scope": "individual", "symbol": "EURUSD", "timeframe": "M30", "horizon": "4",
         "planned_action": "TRAIN", "run_status": "PENDING", "checkpoint_status": "QUEUED"},
        {"execution_id": "PREP-003", "run_id": "PREP-003", "batch": "Batch 1", "checkpoint_group": "Batch 1::M20",
         "scope": "individual", "symbol": "EURUSD", "timeframe": "M20", "horizon": "2",
         "planned_action": "TRAIN", "run_status": "PENDING", "checkpoint_status": "QUEUED"},
    ]
    with path.open("w", newline="", encoding="utf-8") as h:
        w = csv.DictWriter(h, fieldnames=LOG_FIELDS)
        w.writeheader()
        w.writerows(rows)
    # Bring the fixture to the full expected schema WITHOUT touching production.
    from batch_checkpoint_manager import ensure_schema
    ensure_schema(path, write_if_changed=True, strict=False)


@pytest.fixture()
def fixture_paths(tmp_path: Path):
    plan = tmp_path / "plan.csv"
    log = tmp_path / "log.csv"
    _write_plan(plan)
    _write_log(log)
    return plan, log


def test_parse_execution_ids_from_arg():
    assert runner.parse_execution_ids(None) is None
    assert runner.parse_execution_ids("") is None
    assert runner.parse_execution_ids("PREP-001") == {"PREP-001"}
    assert runner.parse_execution_ids("PREP-001,PREP-003") == {"PREP-001", "PREP-003"}
    assert runner.parse_execution_ids(["PREP-001", "PREP-003"]) == {"PREP-001", "PREP-003"}


def test_batch_wide_when_no_scope(fixture_paths):
    plan, log = fixture_paths
    plan_map = runner.parse_plan(plan, "Batch 1")
    rows = runner.load_batch_rows(log, plan_map, "Batch 1")
    assert [r["execution_id"] for r in rows] == ["PREP-001", "PREP-002", "PREP-003"]


def test_scope_selects_only_requested(fixture_paths):
    plan, log = fixture_paths
    plan_map = runner.parse_plan(plan, "Batch 1")
    rows = runner.load_batch_rows(log, plan_map, "Batch 1", execution_ids={"PREP-001"})
    assert [r["execution_id"] for r in rows] == ["PREP-001"]


def test_scope_rejects_unknown_id_no_fallback(fixture_paths):
    plan, log = fixture_paths
    plan_map = runner.parse_plan(plan, "Batch 1")
    # Requesting an id not present must RAISE, never fall back to batch-wide.
    with pytest.raises(ValueError, match="requested execution_id"):
        runner.load_batch_rows(log, plan_map, "Batch 1", execution_ids={"PREP-999"})


def test_scope_with_limit_never_leaks_other_jobs(fixture_paths):
    plan, log = fixture_paths
    plan_map = runner.parse_plan(plan, "Batch 1")
    rows = runner.load_batch_rows(log, plan_map, "Batch 1", execution_ids={"PREP-003"})
    # Even with limit applied later, only PREP-003 is a candidate.
    selected = rows[:5]
    assert {r["execution_id"] for r in selected} == {"PREP-003"}


def test_runnerconfig_has_execution_ids_field(fixture_paths):
    plan, log = fixture_paths
    cfg = runner.RunnerConfig(
        log_path=log, plan_path=plan, batch_name="Batch 1",
        dry_run=True, validate_only=False, execute=False, resume=False, limit=0,
        staging_root=log.parent / "staging", backup_root=log.parent / "backup",
        log_lock_timeout_seconds=5.0, log_lock_poll_seconds=0.1,
        execution_ids={"PREP-001"},
    )
    assert cfg.execution_ids == {"PREP-001"}


def test_run_runner_dry_run_scoped_to_prep001(fixture_paths, monkeypatch):
    """Dry-run (no execute) with scope must only report PREP-001, and never train."""
    plan, log = fixture_paths
    # Guard: fail loudly if any training path is reached.
    def _boom(*a, **k):
        raise AssertionError("training must not run during scope-guard dry-run test")
    monkeypatch.setattr(runner, "run_production_pipeline_to_staging", _boom)

    cfg = runner.RunnerConfig(
        log_path=log, plan_path=plan, batch_name="Batch 1",
        dry_run=True, validate_only=False, execute=False, resume=False, limit=0,
        staging_root=log.parent / "staging", backup_root=log.parent / "backup",
        log_lock_timeout_seconds=5.0, log_lock_poll_seconds=0.1,
        execution_ids={"PREP-001"},
    )
    results = runner.run_runner(cfg)
    assert len(results) == 1
    assert results[0].startswith("PREP-001:")
    assert all("PREP-002" not in r and "PREP-003" not in r for r in results)


def test_run_runner_unknown_scope_raises(fixture_paths):
    plan, log = fixture_paths
    cfg = runner.RunnerConfig(
        log_path=log, plan_path=plan, batch_name="Batch 1",
        dry_run=True, validate_only=False, execute=False, resume=False, limit=0,
        staging_root=log.parent / "staging", backup_root=log.parent / "backup",
        log_lock_timeout_seconds=5.0, log_lock_poll_seconds=0.1,
        execution_ids={"PREP-999"},
    )
    with pytest.raises(ValueError, match="requested execution_id"):
        runner.run_runner(cfg)


def test_parser_exposes_execution_id_flag():
    parser = runner.build_parser()
    args = parser.parse_args(["--execution-id", "PREP-001"])
    assert args.execution_id == "PREP-001"
