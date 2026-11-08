"""Tests for the execution-safety & configuration-freeze audit (Parts A-G).

All tests are read-only with respect to production. They use temporary SQLite
databases built from the repo migrations, dummy artifact bytes, and never call
train_one() or model.fit().
"""
from __future__ import annotations

import json
import threading
from pathlib import Path

import pytest

from nexora_audit.canonical_config import (
    CONFIG_HASH_VERSION,
    build_prep001_proposal,
    canonical_config_hash,
    canonical_json,
    load_runtime_versions,
)
from nexora_audit.readiness import (
    GATE_CONFIG,
    GATE_DATASET,
    GATE_RECOVERY,
    GATE_RUNNER,
    GATE_TIMING,
    STATUS_FAIL,
    STATUS_PASS,
    STATUS_UNRESOLVED,
    check_config_ready,
    check_dataset_ready,
    check_recovery_ready,
    check_runner_ready,
    check_timing_ready,
    run_all_gates,
    summarize,
)
from nexora_audit.safety_probe import (
    probe_crash_recovery,
    probe_lifecycle_synchronized,
    probe_running_job_claim_rejected,
    probe_single_active_attempt,
    run_claim_and_lifecycle_probes,
)

PROJECT_ROOT = Path(__file__).resolve().parents[1]


# ---------------------------------------------------------------------------------
# Part A / F: configuration proposal + hash reproducibility
# ---------------------------------------------------------------------------------
def test_proposal_built_from_source_has_identity_and_evidence():
    proposal = build_prep001_proposal(PROJECT_ROOT)
    assert proposal.job_identity["legacy_reference"] == "PREP-001"
    assert proposal.job_identity["symbol"] == "EURUSD"
    assert proposal.job_identity["timeframe"] == "M30"
    assert proposal.job_identity["horizon"] == 2
    # Every parameter must carry an evidence tag from the allowed vocabulary.
    allowed = {"VERIFIED", "INFERRED", "UNRESOLVED", "CONFLICT"}
    for param in proposal.parameters:
        assert param.status in allowed, param.name
        assert param.evidence, param.name


def test_critical_parameters_present():
    proposal = build_prep001_proposal(PROJECT_ROOT)
    names = {p.name for p in proposal.parameters}
    for critical in ("engine", "objective", "max_depth", "feature_set_version",
                     "target_definition_version", "split_policy_version", "decision_time_policy"):
        assert critical in names


def test_config_hash_is_deterministic_and_reproducible():
    first = build_prep001_proposal(PROJECT_ROOT)
    second = build_prep001_proposal(PROJECT_ROOT)
    h1 = canonical_config_hash(first)
    h2 = canonical_config_hash(second)
    assert h1["hash"] == h2["hash"]
    assert h1["hash_version"] == CONFIG_HASH_VERSION
    # Recomputing on identical bytes yields identical canonical JSON.
    assert canonical_json(first.body_for_hash()) == canonical_json(second.body_for_hash())


def test_config_hash_is_incomplete_while_versioned_contracts_missing():
    proposal = build_prep001_proposal(PROJECT_ROOT)
    result = canonical_config_hash(proposal)
    # Feature/target/split versions are resolved only in the FREEZE manifest, not in
    # the raw canonical proposal; so the raw proposal hash stays incomplete on them.
    assert result["complete"] is False
    assert "feature_set_version" in result["blocking_parameters"]
    # decision_time_policy is now owner-approved (VERIFIED) in the proposal itself,
    # so it is no longer a blocking parameter of the raw proposal hash.
    assert "decision_time_policy" not in result["blocking_parameters"]


def test_canonical_json_is_order_independent():
    a = {"b": 2, "a": 1, "c": {"y": 1, "x": 2}}
    b = {"c": {"x": 2, "y": 1}, "a": 1, "b": 2}
    assert canonical_json(a) == canonical_json(b)


def test_runtime_versions_captured():
    versions = load_runtime_versions()
    assert "python" in versions
    assert "lightgbm" in versions  # present or 'not_installed', never missing


# ---------------------------------------------------------------------------------
# Part G / F: readiness gates
# ---------------------------------------------------------------------------------
def test_dataset_ready_passes_for_prep001():
    proposal = build_prep001_proposal(PROJECT_ROOT)
    report = check_dataset_ready(proposal, PROJECT_ROOT)
    assert report.gate == GATE_DATASET
    assert report.passed, report.detail


def test_config_ready_fails_on_critical_unresolved():
    proposal = build_prep001_proposal(PROJECT_ROOT)
    report = check_config_ready(proposal)
    assert report.gate == GATE_CONFIG
    assert report.status == STATUS_FAIL
    assert "feature_set_version" in report.evidence["blocking"]


def test_timing_ready_is_unresolved():
    report = check_timing_ready()
    assert report.gate == GATE_TIMING
    assert report.status == STATUS_UNRESOLVED


def test_runner_ready_requires_probe_results():
    unresolved = check_runner_ready(None)
    assert unresolved.status == STATUS_UNRESOLVED
    passing = check_runner_ready({
        "single_active_attempt_enforced": True,
        "lifecycle_synchronized": True,
        "running_job_claim_rejected": True,
    })
    assert passing.status == STATUS_PASS
    failing = check_runner_ready({
        "single_active_attempt_enforced": False,
        "lifecycle_synchronized": True,
        "running_job_claim_rejected": True,
    })
    assert failing.status == STATUS_FAIL


def test_recovery_ready_requires_probe_results():
    assert check_recovery_ready(None).status == STATUS_UNRESOLVED
    passing = check_recovery_ready({
        "no_duplicate_active_run": True,
        "promoted_terminal_preserved": True,
    })
    assert passing.status == STATUS_PASS


def test_full_gate_aggregation_blocks_prep001():
    proposal = build_prep001_proposal(PROJECT_ROOT)
    claim = run_claim_and_lifecycle_probes()
    recovery = probe_crash_recovery()
    reports = run_all_gates(proposal, PROJECT_ROOT, claim, recovery)
    decision = summarize(reports)
    # Must not claim readiness while config/timing unresolved.
    assert decision["ready_for_training"] is False
    assert decision["decision"] == "BLOCKED"
    assert GATE_CONFIG in decision["blocking_gates"]
    assert GATE_TIMING in decision["blocking_gates"]
    # Dataset/runner/recovery gates pass on the current code.
    assert decision["gates"][GATE_DATASET] == STATUS_PASS
    assert decision["gates"][GATE_RUNNER] == STATUS_PASS
    assert decision["gates"][GATE_RECOVERY] == STATUS_PASS


# ---------------------------------------------------------------------------------
# Part C/D: atomic claim & lifecycle probes
# ---------------------------------------------------------------------------------
def test_probe_single_active_attempt_enforced():
    outcome = probe_single_active_attempt()
    assert outcome.passed, outcome.detail


def test_probe_running_job_claim_rejected():
    outcome = probe_running_job_claim_rejected()
    assert outcome.passed, outcome.detail


def test_probe_lifecycle_synchronized():
    outcome = probe_lifecycle_synchronized()
    assert outcome.passed, outcome.detail


def test_claim_lifecycle_probes_all_pass():
    aggregate = run_claim_and_lifecycle_probes()
    assert aggregate["all_passed"]
    assert aggregate["single_active_attempt_enforced"]
    assert aggregate["running_job_claim_rejected"]
    assert aggregate["lifecycle_synchronized"]


# ---------------------------------------------------------------------------------
# Part E/F: crash recovery
# ---------------------------------------------------------------------------------
def test_probe_crash_recovery_idempotent():
    result = probe_crash_recovery()
    assert result["all_passed"], json.dumps(result, indent=2)
    assert result["no_duplicate_active_run"]
    assert result["no_duplicate_artifact"]
    assert result["promoted_terminal_preserved"]
    assert result["idempotent"]


# ---------------------------------------------------------------------------------
# Part B/F: look-ahead / leakage guard on features
# ---------------------------------------------------------------------------------
def test_features_have_no_future_dependency():
    import numpy as np
    import pandas as pd

    from nexora_vision.features import build_features

    n = 400
    rng = np.random.default_rng(7)
    close = 1.1 + np.cumsum(rng.normal(0, 0.0001, n))
    df = pd.DataFrame({
        "ts": pd.date_range("2021-01-01", periods=n, freq="30min"),
        "open": close, "high": close + 0.0002, "low": close - 0.0002,
        "close": close, "volume": rng.integers(1, 100, n),
    })
    base = build_features(df)
    # Perturb only the tail; earlier feature rows must not change (no future leakage).
    df2 = df.copy()
    df2.loc[n - 10:, "close"] += 0.5
    df2.loc[n - 10:, "high"] += 0.5
    perturbed = build_features(df2)
    head = n - 65  # beyond the longest rolling window
    pd.testing.assert_frame_equal(base.iloc[:head], perturbed.iloc[:head])
