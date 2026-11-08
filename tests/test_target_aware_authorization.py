"""Regression tests for target-aware authorization binding (T1/T3 isolation).

These tests guarantee that:
  * The runner threads target_type, experiment_candidate, and target-aware
    version ids (feature/target/split) into the execution row it submits to
    ``authorize_execution``.
  * ``authorize_execution`` binds the split policy to the TARGET-AWARE version
    (T3 -> split-4d4a794c..., T1 -> split-ae9a1a9b...) when the row supplies it,
    so a T3 sign-off cannot pass with a T1 split (and vice versa).
  * When the row does not supply version ids, the gate falls back to the frozen
    defaults (backward compatibility for legacy rows / existing tests).

Read-only with respect to production. Synthetic fixtures live under tmp_path.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import shutil
from pathlib import Path

import pytest

import nexora_audit.governance as governance
from nexora_audit import authorization as A
from nexora_audit.canonical_config import (
    build_prep001_proposal,
    canonical_config_hash,
    canonical_json,
)
from nexora_audit.configuration_freeze import (
    build_frozen_manifest,
    feature_set_version,
    split_policy_version_for,
    target_definition_version_for,
)
from nexora_audit.timing_contract import build_timing_contract

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DATASET = PROJECT_ROOT / "data" / "raw" / "EURUSD" / "EURUSD_M30_202001020000_202611062130.csv"
KEY = "prep001-test-key"


def _build_root(tmp_path: Path) -> Path:
    root = tmp_path / "root"
    (root / "config" / "governance").mkdir(parents=True)
    shutil.copy(PROJECT_ROOT / "config" / "research.json", root / "config" / "research.json")
    (root / "data" / "raw" / "EURUSD").mkdir(parents=True)
    shutil.copy(DATASET, root / "data" / "raw" / "EURUSD" / DATASET.name)
    return root


def _payload(root: Path, target_type: str, candidate: str = "A") -> dict:
    proposal = build_prep001_proposal(root)
    cfg = canonical_config_hash(proposal)
    tv = target_definition_version_for(target_type, 2)
    sv = split_policy_version_for(target_type, 2)
    return {
        "approver": "TEST",
        "decided_at": "2026-01-01T00:00:00Z",
        "references": [],
        "config_hash": cfg["hash"],
        "feature_set_version": feature_set_version()["id"],
        "target_definition_version": tv["id"],
        "split_policy_version": sv["id"],
        "timing_contract_hash": "PLACEHOLDER",
        "target": {"target_type": target_type, "target_hash": tv["hash"]},
        "timing_contract": {
            "decision_timestamp": {"value": "bar_t+1_open"},
            "earliest_executable_timestamp": {"value": "bar_t+1_open"},
            "execution_price_model": {"value": "open_price"},
            "spread_usage": {"value": "deferred"},
            "slippage_usage": {"value": "deferred"},
            "cost_usage": {"value": "deferred"},
        },
        "walk_forward_reconciliation": "R1",
        "walk_forward_note": "test",
        "experiment_configuration": {"candidate": candidate, "production_freeze": False},
    }


def _sign(raw: dict) -> dict:
    body = {k: v for k, v in raw.items() if k != "integrity"}
    sig = hmac.new(KEY.encode(), canonical_json(body).encode(), hashlib.sha256).hexdigest()
    raw["integrity"] = {"mechanism": "hmac-sha256", "signature": sig}
    return raw


def _write_signed(root: Path, target_type: str, candidate: str = "A") -> "governance.Ratification":
    raw = _payload(root, target_type, candidate)
    path = root / "config" / "governance" / "prep001_ratification.json"
    path.write_text(json.dumps(raw), encoding="utf-8")
    rat = governance.load_ratification(root)
    ratified = governance.apply_timing_ratification(build_timing_contract(), rat)
    info = governance.ratified_contract_hash(ratified, rat)
    raw["timing_contract_hash"] = info["hash"]
    raw = _sign(raw)
    path.write_text(json.dumps(raw), encoding="utf-8")
    return governance.load_ratification(root)


def _row(target_type: str, *, with_versions: bool, candidate=None) -> dict:
    row = {
        "execution_id": "PREP-001",
        "batch": "Batch 1",
        "scope": "individual",
        "symbol": "EURUSD",
        "timeframe": "M30",
        "horizon": "2",
        "target_type": target_type,
    }
    if with_versions:
        tv = target_definition_version_for(target_type, 2)
        sv = split_policy_version_for(target_type, 2)
        row["target_definition_version"] = tv["id"]
        row["split_policy_version"] = sv["id"]
        row["feature_set_version"] = feature_set_version()["id"]
    if candidate is not None:
        row["experiment_candidate"] = candidate
    return row


PROBES = dict(
    claim_probe_result={
        "single_active_attempt_enforced": True,
        "lifecycle_synchronized": True,
        "running_job_claim_rejected": True,
    },
    recovery_probe_result={"no_duplicate_active_run": True, "promoted_terminal_preserved": True},
)


@pytest.fixture()
def root(tmp_path, monkeypatch):
    monkeypatch.setenv("NEXORA_GOVERNANCE_KEY", KEY)
    return _build_root(tmp_path)


def _authorize(root, row, rat):
    return A.authorize_execution(
        execution_row=row,
        project_root=root,
        batch_name="Batch 1",
        requested_execution_ids={"PREP-001"},
        ratification=rat,
        **PROBES,
    )


@pytest.mark.parametrize("target_type", ["T1", "T3"])
def test_target_aware_versions_all_pass(root, target_type):
    rat = _write_signed(root, target_type)
    decision = _authorize(root, _row(target_type, with_versions=True, candidate="A"), rat)
    # All version/target/candidate bindings must PASS. Readiness may still block
    # on DATASET_READY in a synthetic tmp root (no dataset audit manifest there);
    # that is an environment artifact, not a binding failure, so we only assert
    # that the failure set is a subset of {READINESS_BLOCKED}.
    failing = {c.code for c in decision.checks if not c.passed}
    assert failing <= {"READINESS_BLOCKED"}, decision.reasons
    assert decision.bindings["contract_versions_source"] == "row"
    assert decision.bindings["split_policy_version"] == split_policy_version_for(target_type, 2)["id"]


def test_t3_split_is_not_default(root):
    """T3 binds split-4d4a794c..., not the frozen default split-27dd116e...."""
    rat = _write_signed(root, "T3")
    decision = _authorize(root, _row("T3", with_versions=True), rat)
    t3_split = split_policy_version_for("T3", 2)["id"]
    default_split = build_frozen_manifest(root).split_version["id"]
    assert t3_split != default_split
    assert decision.bindings["split_policy_version"] == t3_split


def test_t3_signoff_rejected_on_t1_row(root):
    """A T3 sign-off must NOT authorize a row requesting T1 (split/target mismatch)."""
    rat = _write_signed(root, "T3")
    decision = _authorize(root, _row("T1", with_versions=True), rat)
    assert decision.authorized is False
    codes = decision.codes()
    assert "TARGET_TYPE_MISMATCH" in codes
    assert "VERSION_MISMATCH" in codes


def test_fallback_to_frozen_defaults_when_row_omits_versions(root):
    """Rows without explicit version ids bind to the FROZEN DEFAULT ids.

    Backward compatibility: a legacy row that supplies no version ids is bound
    against the frozen-default split/target/feature ids. We construct a sign-off
    that uses exactly those frozen-default ids so the fallback path is exercised
    in isolation from the target-aware path.
    """
    from nexora_audit.configuration_freeze import (
        split_policy_version as _default_split,
        target_definition_version as _default_target,
    )

    frozen = build_frozen_manifest(root)
    raw = _payload(root, "T1")
    # Override with the FROZEN-DEFAULT ids (not target-aware).
    raw["split_policy_version"] = frozen.split_version["id"]
    raw["target_definition_version"] = frozen.target_version["id"]
    path = root / "config" / "governance" / "prep001_ratification.json"
    path.write_text(json.dumps(raw), encoding="utf-8")
    rat0 = governance.load_ratification(root)
    ratified = governance.apply_timing_ratification(build_timing_contract(), rat0)
    info = governance.ratified_contract_hash(ratified, rat0)
    raw["timing_contract_hash"] = info["hash"]
    raw = _sign(raw)
    path.write_text(json.dumps(raw), encoding="utf-8")
    rat = governance.load_ratification(root)

    decision = _authorize(root, _row("T1", with_versions=False, candidate="A"), rat)
    assert decision.bindings["contract_versions_source"] == "frozen_default"
    failing = {c.code for c in decision.checks if not c.passed}
    assert failing <= {"READINESS_BLOCKED"}, decision.reasons


def test_t1_aware_split_differs_from_frozen_default(root):
    """T1-aware split is NOT the frozen default, so the runner MUST inject the
    target-aware ids (a real T1 sign-off would otherwise mismatch the fallback)."""
    from nexora_audit.configuration_freeze import split_policy_version as _default_split

    frozen = build_frozen_manifest(root)
    t1_split = split_policy_version_for("T1", 2)["id"]
    assert t1_split != frozen.split_version["id"]
    assert t1_split != _default_split()["id"]

    # A real T1 sign-off (using the T1-aware split) must NOT bind on a row that
    # omits versions (fallback would use the different frozen default).
    rat = _write_signed(root, "T1")  # sign-off uses T1-aware split-ae9a1a9b...
    decision = _authorize(root, _row("T1", with_versions=False), rat)
    assert "VERSION_MISMATCH" in decision.codes()
    # But with the runner-supplied target-aware row, it binds.
    decision_ok = _authorize(root, _row("T1", with_versions=True), rat)
    assert "VERSION_MISMATCH" not in decision_ok.codes()


def test_runner_threads_target_aware_versions_and_candidate(root, monkeypatch):
    """guard_execution_authorized injects target-aware versions + candidate into the row."""
    monkeypatch.setenv("NEXORA_GOVERNANCE_KEY", KEY)
    rat = _write_signed(root, "T3")
    # Capture the row the runner submits by wrapping authorize_execution.
    captured = {}
    real = A.authorize_execution

    def _capture(*args, **kwargs):
        captured["row"] = kwargs["execution_row"]
        return real(*args, **kwargs)

    monkeypatch.setattr(A, "authorize_execution", _capture)

    import importlib
    import batch1_execution_runner as runner_mod
    importlib.reload(runner_mod)  # rebind the patched authorize_execution
    monkeypatch.setattr(runner_mod, "authorize_execution", _capture, raising=False)

    cfg = runner_mod.RunnerConfig(
        log_path=root / "unused.csv",
        plan_path=root / "unused_plan.csv",
        batch_name="Batch 1",
        dry_run=False,
        validate_only=False,
        execute=True,
        resume=False,
        limit=1,
        staging_root=root,
        backup_root=root,
        log_lock_timeout_seconds=1.0,
        log_lock_poll_seconds=0.05,
        execution_ids={"PREP-001"},
        authorization_root=root,
        target_type="T3",
        experiment_candidate="A",
    )
    # Inject precomputed context to avoid recomputation differences; pass the
    # loaded ratification so signature verification succeeds on this root.
    row = _row("T3", with_versions=False)  # runner must ADD versions itself
    row.pop("target_type")  # ensure runner resolves from target_type=cfg.target_type

    try:
        runner_mod.guard_execution_authorized(row, cfg)
    except A.AuthorizationError:
        pass  # readiness may still be blocked without probes; we only inspect the row

    submitted = captured.get("row") or {}
    assert submitted.get("target_type") == "T3"
    assert submitted.get("split_policy_version") == split_policy_version_for("T3", 2)["id"]
    assert submitted.get("target_definition_version") == target_definition_version_for("T3", 2)["id"]
    assert submitted.get("feature_set_version") == feature_set_version()["id"]
    assert submitted.get("experiment_candidate") == "A"
