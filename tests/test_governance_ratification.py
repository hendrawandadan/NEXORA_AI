"""Tests for the human-ratification governance layer.

Read-only wrt production. Uses temporary directories; never writes a ratified
file into the real config/. Verifies that:
* absent file         -> not ratified; gates stay BLOCKED;
* template/partial    -> invalid; not ratified;
* properly signed file -> ratified; CONFIG_READY and TIMING_READY can PASS;
* an experiment config is never treated as a production freeze.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from nexora_audit import governance
from nexora_audit.configuration_freeze import build_frozen_manifest
from nexora_audit.readiness import (
    check_config_ready_freeze,
    check_timing_ready,
)
from nexora_audit.timing_contract import build_timing_contract

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _write_ratification(root: Path, payload: dict) -> None:
    d = root / "config" / "governance"
    d.mkdir(parents=True, exist_ok=True)
    (d / "prep001_ratification.json").write_text(json.dumps(payload), encoding="utf-8")


def _valid_payload() -> dict:
    return {
        "approver": "Test Approver",
        "decided_at": "2026-11-08T10:00:00Z",
        "references": ["reports/retraining/execution_timing_contract.md"],
        "timing_contract": {
            "decision_timestamp": {"value": "bar_t_close"},
            "earliest_executable_timestamp": {"value": "bar_t+1_open"},
            "execution_price_model": {"value": "bar_t+1_open"},
            "spread_usage": {"value": "feature_only_no_cost"},
            "slippage_usage": {"value": "none"},
            "cost_usage": {"value": "gross_metrics"},
        },
        "walk_forward_reconciliation": "R1",
        "walk_forward_note": "wire config to code, behaviour unchanged at 0.5",
        "experiment_configuration": {
            "candidate": "B",
            "max_depth": 4,
            "reg_alpha": 0.1,
            "production_freeze": False,
            "note": "experiment only",
        },
    }


def test_absent_file_is_not_ratified(tmp_path):
    rat = governance.load_ratification(tmp_path)
    assert rat is None
    summary = governance.ratification_summary(tmp_path)
    assert summary["present"] is False
    assert summary["valid"] is False


def test_template_like_payload_is_invalid(tmp_path):
    _write_ratification(tmp_path, {"approver": "<FILL_ME>", "timing_contract": {}})
    rat = governance.load_ratification(tmp_path)
    assert rat is not None
    assert rat.valid is False
    assert any("walk_forward_reconciliation" in p for p in rat.problems)


def test_missing_timing_decisions_invalid(tmp_path):
    payload = _valid_payload()
    del payload["timing_contract"]["cost_usage"]
    _write_ratification(tmp_path, payload)
    rat = governance.load_ratification(tmp_path)
    assert rat.valid is False
    assert any("cost_usage" in p for p in rat.problems)


def test_experiment_marked_production_freeze_invalid(tmp_path):
    payload = _valid_payload()
    payload["experiment_configuration"]["production_freeze"] = True
    _write_ratification(tmp_path, payload)
    rat = governance.load_ratification(tmp_path)
    assert rat.valid is False
    assert any("production_freeze" in p for p in rat.problems)


def test_valid_payload_ratifies(tmp_path):
    _write_ratification(tmp_path, _valid_payload())
    rat = governance.load_ratification(tmp_path)
    assert rat.valid is True
    summary = governance.ratification_summary(tmp_path)
    assert summary["valid"] is True
    assert summary["walk_forward"]["option"] == "R1"
    assert summary["experiment"]["candidate"] == "B"
    # Experiment is never production freeze.
    assert summary["experiment"]["production_freeze"] is False


def test_timing_gate_passes_only_with_ratification(tmp_path):
    contract = build_timing_contract()
    # No ratification -> UNRESOLVED.
    assert check_timing_ready(contract).status == "UNRESOLVED"

    _write_ratification(tmp_path, _valid_payload())
    rat = governance.load_ratification(tmp_path)
    ratified = governance.apply_timing_ratification(contract, rat)
    info = governance.ratified_contract_hash(ratified, rat)
    report = check_timing_ready(ratified, ratification_info=info)
    assert report.status == "PASS"
    assert report.evidence["ratification"]["ratified"] is True


def test_apply_timing_ratification_overrides_values(tmp_path):
    _write_ratification(tmp_path, _valid_payload())
    rat = governance.load_ratification(tmp_path)
    contract = build_timing_contract()
    ratified = governance.apply_timing_ratification(contract, rat)
    assert ratified.field("earliest_executable_timestamp").value == "bar_t+1_open"
    assert ratified.field("cost_usage").value == "gross_metrics"


def _incomplete_manifest():
    """A synthetic manifest that still REQUIRES decisions (to exercise the
    ratified-parameters path) without depending on the now-complete live freeze."""
    from nexora_audit.configuration_freeze import FrozenEntry, REQUIRES_DECISION
    m = build_frozen_manifest(PROJECT_ROOT)
    # Drop the three now-frozen params back into requires_decision to simulate
    # an unresolved manifest.
    moved = [e for e in m.frozen if e.name in ("max_depth", "l1_regularization", "decision_time_policy")]
    m.frozen = [e for e in m.frozen if e.name not in ("max_depth", "l1_regularization", "decision_time_policy")]
    for e in moved:
        m.requires_decision.append(FrozenEntry(
            e.name, e.value, REQUIRES_DECISION, e.evidence, "UNRESOLVED"))
    return m


def test_config_gate_passes_with_complete_live_freeze():
    # The live manifest is complete after B1/B2 owner decisions -> PASS without ratification.
    manifest = build_frozen_manifest(PROJECT_ROOT)
    report = check_config_ready_freeze(manifest)
    assert report.status == "PASS"
    assert report.evidence.get("complete") is True


def test_config_gate_passes_with_ratified_parameters_on_incomplete_manifest():
    manifest = _incomplete_manifest()
    ratified_params = {
        "max_depth": 4,
        "l1_regularization": 0.1,
        "decision_time_policy": "bar_t_close",
    }
    report = check_config_ready_freeze(manifest, ratified_parameters=ratified_params)
    assert report.status == "PASS"
    # And still FAIL without them.
    assert check_config_ready_freeze(manifest).status == "FAIL"


def test_config_gate_still_fails_if_one_decision_missing_on_incomplete_manifest():
    manifest = _incomplete_manifest()
    partial = {"max_depth": 4}  # l1 + decision_time_policy missing
    report = check_config_ready_freeze(manifest, ratified_parameters=partial)
    assert report.status == "FAIL"


def test_invalid_ratification_blocks_apply(tmp_path):
    _write_ratification(tmp_path, {"approver": "x"})  # invalid
    rat = governance.load_ratification(tmp_path)
    assert rat.valid is False
    with pytest.raises(governance.RatificationError):
        governance.apply_timing_ratification(build_timing_contract(), rat)
