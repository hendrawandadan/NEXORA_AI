"""Ensure the runner forwards readiness probes into authorize_execution.

Regression guard for the READINESS_BLOCKED(['RUNNER_READY','RECOVERY_READY']) bug:
the runner must run the isolated safety probes and pass their results, otherwise
those gates stay UNRESOLVED and dispatch is blocked even with a valid sign-off.

SAFETY: patches authorize_execution (no real gate run, no training). No files
except a temp root are touched.
"""
from __future__ import annotations

from pathlib import Path

import pytest

import batch1_execution_runner as runner


def _cfg(tmp_path: Path) -> runner.RunnerConfig:
    return runner.RunnerConfig(
        log_path=tmp_path / "log.csv",
        plan_path=tmp_path / "plan.csv",
        batch_name="Batch 1",
        dry_run=False,
        validate_only=False,
        execute=True,
        resume=False,
        limit=1,
        staging_root=tmp_path / "staging",
        backup_root=tmp_path / "backup",
        log_lock_timeout_seconds=1.0,
        log_lock_poll_seconds=0.05,
        execution_ids={"PREP-001"},
        authorization_root=tmp_path,
        target_type="T3",
        experiment_candidate="A",
    )


def test_guard_forwards_claim_and_recovery_probes(tmp_path, monkeypatch):
    captured = {}

    class _DummyDecision:
        authorized = True
        reasons = []
        bindings = {}

    def _fake_authorize(**kwargs):
        captured.update(kwargs)
        return _DummyDecision()

    monkeypatch.setattr(runner, "authorize_execution", _fake_authorize, raising=False)
    # require_authorized must accept the dummy decision.
    monkeypatch.setattr(runner, "require_authorized", lambda d: None, raising=False)

    row = {
        "execution_id": "PREP-001",
        "batch": "Batch 1",
        "scope": "individual",
        "symbol": "EURUSD",
        "timeframe": "M30",
        "horizon": "2",
    }
    runner.guard_execution_authorized(row, _cfg(tmp_path))

    # Probes MUST be present (not None) and reflect the real isolated results.
    claim = captured.get("claim_probe_result")
    recovery = captured.get("recovery_probe_result")
    assert claim is not None, "claim_probe_result not forwarded -> RUNNER_READY would block"
    assert recovery is not None, "recovery_probe_result not forwarded -> RECOVERY_READY would block"
    assert claim.get("single_active_attempt_enforced") is True
    assert claim.get("lifecycle_synchronized") is True
    assert claim.get("running_job_claim_rejected") is True
    assert recovery.get("no_duplicate_active_run") is True
    assert recovery.get("promoted_terminal_preserved") is True


def test_guard_fails_closed_if_probe_raises(tmp_path, monkeypatch):
    import nexora_audit.safety_probe as sp

    def _boom():
        raise RuntimeError("probe infrastructure broken")

    monkeypatch.setattr(sp, "run_claim_and_lifecycle_probes", _boom)
    monkeypatch.setattr(runner, "authorize_execution", lambda **k: pytest.fail("must not reach gate"))
    monkeypatch.setattr(runner, "require_authorized", lambda d: None, raising=False)

    row = {"execution_id": "PREP-001", "batch": "Batch 1", "scope": "individual",
           "symbol": "EURUSD", "timeframe": "M30", "horizon": "2"}
    with pytest.raises(runner.AuthorizationError):
        runner.guard_execution_authorized(row, _cfg(tmp_path))
