"""Isolation tests for the PREP-001 execution authorization gate.

SAFETY:
* Builds a synthetic project root in a TemporaryDirectory (config, dataset,
  audit manifest, governance sign-off). Never touches the production
  DB/CSV/dataset/model/backup.
* Never calls train_one / model.fit. Never flips PLANNED->QUEUED.
* Proves fail-closed behavior: absent/invalid/unverified sign-off, wrong job,
  wrong batch, wrong candidate, config-hash mismatch, timing unratified,
  readiness blocked, multi-row / unscoped dispatch, and in-runner gating.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import shutil
from pathlib import Path
from typing import Dict

import pytest

from nexora_audit import governance
from nexora_audit.authorization import (
    AuthorizationError,
    authorize_execution,
    require_authorized,
    verify_signoff_integrity,
)
from nexora_audit.canonical_config import (
    build_prep001_proposal,
    canonical_config_hash,
    canonical_json,
)
from nexora_audit.configuration_freeze import build_frozen_manifest, target_definition_version_for
from nexora_audit.safety_probe import probe_crash_recovery, run_claim_and_lifecycle_probes
from nexora_audit.timing_contract import build_timing_contract

PROJECT_ROOT = Path(__file__).resolve().parents[1]

DATASET_REL = Path("data") / "raw" / "EURUSD" / "EURUSD_M30_202001020000_202611062130.csv"

_TIMING_FIELDS = (
    "decision_timestamp",
    "earliest_executable_timestamp",
    "execution_price_model",
    "spread_usage",
    "slippage_usage",
    "cost_usage",
)


def _row(execution_id: str = "PREP-001", batch: str = "Batch 1", horizon: str = "2", **extra) -> dict:
    base = {
        "execution_id": execution_id,
        "batch": batch,
        "scope": "individual",
        "symbol": "EURUSD",
        "timeframe": "M30",
        "horizon": horizon,
        "target_type": "T1",
    }
    base.update(extra)
    return base


def _build_base_root(tmp_path: Path) -> Path:
    """Create a synthetic project root with config + dataset + audit manifest."""
    root = tmp_path / "proj"
    (root / "config").mkdir(parents=True)
    shutil.copy2(PROJECT_ROOT / "config" / "research.json", root / "config" / "research.json")
    ds = root / DATASET_REL
    ds.parent.mkdir(parents=True)
    ds.write_text("time,open,high,low,close,volume\n2020.01.02 00:00,1,1,1,1,1\n", encoding="utf-8")
    (root / "reports" / "audit").mkdir(parents=True)
    manifest = root / "reports" / "audit" / (ds.stem + ".json")
    manifest.write_text(
        json.dumps(
            {
                "file": ds.name,
                "interval_check": {"status": "PASS"},
                "schema_valid": True,
                "rows_valid_unique": 70694,
                "gap_count": 0,
            }
        ),
        encoding="utf-8",
    )
    return root


def _proposal_and_freeze(root: Path):
    proposal = build_prep001_proposal(root)
    frozen = build_frozen_manifest(root)
    return proposal, frozen


def _signed_payload(root: Path, candidate: str = "B", sign: bool = True, key: str = "test-key") -> Dict:
    """Build a fully-bound sign-off payload (optionally HMAC-signed)."""
    proposal, frozen = _proposal_and_freeze(root)
    timing_contract = build_timing_contract()
    timing_block = {f: {"value": f"v_{f}"} for f in _TIMING_FIELDS}
    base = {
        "approver": "Test Approver",
        "decided_at": "2026-11-08T10:00:00Z",
        "references": ["reports/retraining/execution_timing_contract.md"],
        "timing_contract": timing_block,
        "walk_forward_reconciliation": "R1",
        "walk_forward_note": "r1",
        "experiment_configuration": {
            "candidate": candidate,
            "max_depth": 4,
            "reg_alpha": 0.1,
            "production_freeze": False,
            "note": "experiment only",
        },
        "config_hash": canonical_config_hash(proposal)["hash"],
        "feature_set_version": frozen.feature_version["id"],
        "target_definition_version": frozen.target_version["id"],
        "split_policy_version": frozen.split_version["id"],
        "target": {
            "target_type": "T1",
            "target_hash": target_definition_version_for("T1", int(proposal.job_identity["horizon"]))["hash"],
        },
    }
    # Compute the ratified timing hash exactly the way governance does.
    rat = governance.Ratification(dict(base), root / "x", True, [])
    ratified_contract = governance.apply_timing_ratification(timing_contract, rat)
    base["timing_contract_hash"] = governance.ratified_contract_hash(ratified_contract, rat)["hash"]

    if sign:
        body = {k: v for k, v in base.items() if k != "integrity"}
        sig = hmac.new(key.encode("utf-8"), canonical_json(body).encode("utf-8"), hashlib.sha256).hexdigest()
        base["integrity"] = {"mechanism": "hmac-sha256", "signature": sig}
    return base


def _write_signoff(root: Path, payload: Dict) -> None:
    d = root / "config" / "governance"
    d.mkdir(parents=True, exist_ok=True)
    (d / "prep001_ratification.json").write_text(json.dumps(payload), encoding="utf-8")


@pytest.fixture()
def probes():
    return run_claim_and_lifecycle_probes(), probe_crash_recovery()


@pytest.fixture()
def valid_root(tmp_path: Path, monkeypatch, probes):
    monkeypatch.setenv("NEXORA_GOVERNANCE_KEY", "test-key")
    root = _build_base_root(tmp_path)
    _write_signoff(root, _signed_payload(root, candidate="B", sign=True))
    return root


# ---------------------------------------------------------------------------------
# Pass path
# ---------------------------------------------------------------------------------
def test_full_binding_authorizes(valid_root, probes):
    claim, recovery = probes
    decision = authorize_execution(
        execution_row=_row(),
        project_root=valid_root,
        batch_name="Batch 1",
        requested_execution_ids={"PREP-001"},
        claim_probe_result=claim,
        recovery_probe_result=recovery,
    )
    assert decision.authorized is True, decision.reasons
    assert decision.integrity["status"] == "VERIFIED"
    require_authorized(decision)


# ---------------------------------------------------------------------------------
# Fail-closed paths
# ---------------------------------------------------------------------------------
def test_absent_signoff_blocks(tmp_path, probes):
    claim, recovery = probes
    root = _build_base_root(tmp_path)
    decision = authorize_execution(
        execution_row=_row(),
        project_root=root,
        batch_name="Batch 1",
        requested_execution_ids={"PREP-001"},
        claim_probe_result=claim,
        recovery_probe_result=recovery,
    )
    assert decision.authorized is False
    assert "SIGNOFF_ABSENT" in decision.codes()
    with pytest.raises(AuthorizationError):
        require_authorized(decision)


def test_unsigned_signoff_is_unverified_and_blocks(valid_root, probes):
    """A structurally valid but UNSIGNED sign-off must NOT authorize."""
    claim, recovery = probes
    payload = _signed_payload(valid_root, candidate="B", sign=False)
    _write_signoff(valid_root, payload)
    decision = authorize_execution(
        execution_row=_row(),
        project_root=valid_root,
        batch_name="Batch 1",
        requested_execution_ids={"PREP-001"},
        claim_probe_result=claim,
        recovery_probe_result=recovery,
    )
    assert decision.authorized is False
    assert "SIGNOFF_NOT_RATIFIED" in decision.codes()


def test_wrong_execution_id_blocks(valid_root, probes):
    claim, recovery = probes
    decision = authorize_execution(
        execution_row=_row(execution_id="PREP-002", horizon="4"),
        project_root=valid_root,
        batch_name="Batch 1",
        requested_execution_ids={"PREP-002"},
        claim_probe_result=claim,
        recovery_probe_result=recovery,
    )
    assert decision.authorized is False
    assert "EXECUTION_ID_MISMATCH" in decision.codes()
    assert "JOB_IDENTITY_MISMATCH" in decision.codes()


def test_wrong_batch_blocks(valid_root, probes):
    claim, recovery = probes
    decision = authorize_execution(
        execution_row=_row(batch="Batch 2"),
        project_root=valid_root,
        batch_name="Batch 2",
        requested_execution_ids={"PREP-001"},
        claim_probe_result=claim,
        recovery_probe_result=recovery,
    )
    assert decision.authorized is False
    assert "BATCH_MISMATCH" in decision.codes()


def test_config_hash_mismatch_blocks(valid_root, probes):
    claim, recovery = probes
    payload = _signed_payload(valid_root, candidate="B", sign=False)
    payload["config_hash"] = "0" * 64
    body = {k: v for k, v in payload.items() if k != "integrity"}
    sig = hmac.new(b"test-key", canonical_json(body).encode("utf-8"), hashlib.sha256).hexdigest()
    payload["integrity"] = {"mechanism": "hmac-sha256", "signature": sig}
    _write_signoff(valid_root, payload)
    decision = authorize_execution(
        execution_row=_row(),
        project_root=valid_root,
        batch_name="Batch 1",
        requested_execution_ids={"PREP-001"},
        claim_probe_result=claim,
        recovery_probe_result=recovery,
    )
    assert decision.authorized is False
    assert "CONFIG_HASH_MISMATCH" in decision.codes()


def test_timing_unratified_blocks(valid_root, probes):
    """If timing hash is stripped, timing binding fails even if signed."""
    claim, recovery = probes
    payload = _signed_payload(valid_root, candidate="B", sign=False)
    payload.pop("timing_contract_hash", None)
    body = {k: v for k, v in payload.items() if k != "integrity"}
    sig = hmac.new(b"test-key", canonical_json(body).encode("utf-8"), hashlib.sha256).hexdigest()
    payload["integrity"] = {"mechanism": "hmac-sha256", "signature": sig}
    _write_signoff(valid_root, payload)
    decision = authorize_execution(
        execution_row=_row(),
        project_root=valid_root,
        batch_name="Batch 1",
        requested_execution_ids={"PREP-001"},
        claim_probe_result=claim,
        recovery_probe_result=recovery,
    )
    assert decision.authorized is False
    assert "TIMING_NOT_RATIFIED" in decision.codes()


def test_wrong_candidate_binding_blocks(valid_root, probes):
    """Row requests candidate A but the sign-off authorizes B."""
    claim, recovery = probes
    payload = _signed_payload(valid_root, candidate="B", sign=False)
    body = {k: v for k, v in payload.items() if k != "integrity"}
    sig = hmac.new(b"test-key", canonical_json(body).encode("utf-8"), hashlib.sha256).hexdigest()
    payload["integrity"] = {"mechanism": "hmac-sha256", "signature": sig}
    _write_signoff(valid_root, payload)
    decision = authorize_execution(
        execution_row=_row(experiment_candidate="A"),
        project_root=valid_root,
        batch_name="Batch 1",
        requested_execution_ids={"PREP-001"},
        claim_probe_result=claim,
        recovery_probe_result=recovery,
    )
    assert decision.authorized is False
    assert "CANDIDATE_MISMATCH" in decision.codes()


def test_unscoped_dispatch_blocks(valid_root, probes):
    """No requested_execution_ids (batch-wide) must be refused."""
    claim, recovery = probes
    decision = authorize_execution(
        execution_row=_row(),
        project_root=valid_root,
        batch_name="Batch 1",
        requested_execution_ids=None,
        claim_probe_result=claim,
        recovery_probe_result=recovery,
    )
    assert decision.authorized is False
    assert "MULTI_OR_UNSCOPED_DISPATCH" in decision.codes()


def test_multi_row_dispatch_blocks(valid_root, probes):
    """Requesting more than one id (multi-job) must be refused per single row."""
    claim, recovery = probes
    decision = authorize_execution(
        execution_row=_row(),
        project_root=valid_root,
        batch_name="Batch 1",
        requested_execution_ids={"PREP-001", "PREP-002"},
        claim_probe_result=claim,
        recovery_probe_result=recovery,
    )
    assert decision.authorized is False
    assert "MULTI_OR_UNSCOPED_DISPATCH" in decision.codes()


def test_readiness_blocked_without_probes(valid_root):
    """With no probes, RUNNER/RECOVERY are UNRESOLVED -> readiness blocks."""
    decision = authorize_execution(
        execution_row=_row(),
        project_root=valid_root,
        batch_name="Batch 1",
        requested_execution_ids={"PREP-001"},
    )
    assert decision.authorized is False
    assert "READINESS_BLOCKED" in decision.codes()


def test_integrity_hmac_mismatch_is_invalid(valid_root):
    """A wrong HMAC signature must be INVALID, not VERIFIED."""
    payload = _signed_payload(valid_root, candidate="B", sign=False)
    payload["integrity"] = {"mechanism": "hmac-sha256", "signature": "deadbeef"}
    _write_signoff(valid_root, payload)
    rat = governance.load_ratification(valid_root)
    result = verify_signoff_integrity(rat, valid_root)
    assert result["status"] == "INVALID"


def test_integrity_missing_key_is_unverified(valid_root, monkeypatch):
    monkeypatch.delenv("NEXORA_GOVERNANCE_KEY", raising=False)
    payload = _signed_payload(valid_root, candidate="B", sign=True)
    _write_signoff(valid_root, payload)
    rat = governance.load_ratification(valid_root)
    result = verify_signoff_integrity(rat, valid_root)
    assert result["status"] == "UNVERIFIED"


# ---------------------------------------------------------------------------------
# In-runner gating (never trains; refuses before dispatch)
# ---------------------------------------------------------------------------------
def test_runner_refuses_without_ratification(tmp_path, monkeypatch):
    import batch1_execution_runner as runner

    plan = tmp_path / "plan.csv"
    log = tmp_path / "log.csv"
    _write_plan_and_log(plan, log)

    def _boom(*a, **k):
        raise AssertionError("training must never run when unauthorized")

    monkeypatch.setattr(runner, "run_production_pipeline_to_staging", _boom)

    root = _build_base_root(tmp_path)  # no sign-off
    cfg = runner.RunnerConfig(
        log_path=log, plan_path=plan, batch_name="Batch 1",
        dry_run=False, validate_only=False, execute=True, resume=False, limit=0,
        staging_root=tmp_path / "staging", backup_root=tmp_path / "backup",
        log_lock_timeout_seconds=5.0, log_lock_poll_seconds=0.1,
        execution_ids={"PREP-001"},
        authorization_root=root,
    )
    with pytest.raises(AuthorizationError):
        runner.run_runner(cfg)


def test_runner_refuses_unscoped_execute(tmp_path, monkeypatch):
    import batch1_execution_runner as runner

    plan = tmp_path / "plan.csv"
    log = tmp_path / "log.csv"
    _write_plan_and_log(plan, log)

    def _boom(*a, **k):
        raise AssertionError("training must never run when unscoped")

    monkeypatch.setattr(runner, "run_production_pipeline_to_staging", _boom)

    root = _build_base_root(tmp_path)
    cfg = runner.RunnerConfig(
        log_path=log, plan_path=plan, batch_name="Batch 1",
        dry_run=False, validate_only=False, execute=True, resume=False, limit=0,
        staging_root=tmp_path / "staging", backup_root=tmp_path / "backup",
        log_lock_timeout_seconds=5.0, log_lock_poll_seconds=0.1,
        execution_ids=None,  # unscoped
        authorization_root=root,
    )
    with pytest.raises(AuthorizationError):
        runner.run_runner(cfg)


def _write_plan_and_log(plan: Path, log: Path) -> None:
    import csv

    plan_rows = [
        {"batch": "Batch 1", "order": "1", "scope": "individual", "symbol": "EURUSD", "timeframe": "M30", "horizon": "2"},
    ]
    with plan.open("w", newline="", encoding="utf-8") as h:
        w = csv.DictWriter(h, fieldnames=list(plan_rows[0].keys()))
        w.writeheader()
        w.writerows(plan_rows)

    log_fields = [
        "execution_id", "run_id", "batch", "checkpoint_group", "scope", "symbol", "timeframe",
        "horizon", "planned_action", "run_status", "checkpoint_status",
    ]
    log_rows = [
        {"execution_id": "PREP-001", "run_id": "PREP-001", "batch": "Batch 1", "checkpoint_group": "Batch 1::M30",
         "scope": "individual", "symbol": "EURUSD", "timeframe": "M30", "horizon": "2",
         "planned_action": "TRAIN", "run_status": "PENDING", "checkpoint_status": "QUEUED"},
    ]
    with log.open("w", newline="", encoding="utf-8") as h:
        w = csv.DictWriter(h, fieldnames=log_fields)
        w.writeheader()
        w.writerows(log_rows)
    from batch_checkpoint_manager import ensure_schema
    ensure_schema(log, write_if_changed=True, strict=False)
