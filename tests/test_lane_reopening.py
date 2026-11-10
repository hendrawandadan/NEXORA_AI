"""Tests for NEXORA-GOV-PRD-002 - Price-Derived Lane REOPENING proposal/ratification flow.

CRITICAL invariant proven here: building or even ratifying a reopening packet does
NOT reopen the lane. The registry stays SUSPENDED and the guard keeps blocking
train/tune/promote/live/auto_reopen until an owner-only tool flips the registry.
"""

import json
from pathlib import Path

import pytest

from nexora_laboratory.governance import lane_reopening as lr
from nexora_laboratory.governance.lane_suspension import (
    GovernanceViolation, assert_can, is_suspended, lane_status, load_registry,
    REGISTRY_PATH,
)

REPO = Path(__file__).resolve().parents[1]


def _proposal(**over):
    base = {
        "type": "REOPENING_PROPOSAL",
        "decision_id": "NEXORA-GOV-PRD-001",
        "approver": "Dadan Hendrawan",
        "decided_at": "2026-11-10T00:00:00Z",
        "conditions_satisfied": [
            {"condition": "new data source providing additional information",
             "evidence": "reports/governance/new_data.md"}],
        "new_hypothesis": "EURUSD H4 h12 range compression predicts direction.",
        "distinct_from_failed_hypothesis":
            "Prior tests used basic range features; this uses a new measurement method.",
        "candidates_requested": [{"instrument": "EURUSD", "timeframe": "H4", "horizon": 12}],
    }
    # Map every registry procedure step so the default proposal validates.
    base["procedure_status"] = {s: {"status": "PENDING"}
                                for s in lr.registry_procedure()}
    base.update(over)
    return base


# ---------------------------------------------------------------- registry read-only
def test_registry_is_still_suspended():
    assert is_suspended() is True
    assert lane_status() == "SUSPENDED"


def test_registry_conditions_match_suspension_file():
    reg = load_registry()
    assert lr.registry_conditions() == reg["reopening_conditions"]
    assert lr.registry_procedure() == reg["reopening_procedure"]


# ---------------------------------------------------------------- proposal validation
def test_valid_proposal_passes():
    v = lr.validate_proposal(_proposal())
    assert v["valid"], v["problems"]


def test_proposal_wrong_decision_id_fails():
    v = lr.validate_proposal(_proposal(decision_id="NEXORA-GOV-WRONG"))
    assert not v["valid"]
    assert any("decision_id" in p for p in v["problems"])


def test_proposal_condition_not_in_registry_fails():
    p = _proposal(conditions_satisfied=[{"condition": "because I want to", "evidence": ""}])
    v = lr.validate_proposal(p)
    assert not v["valid"]
    assert any("not in registry" in x for x in v["problems"])


def test_proposal_missing_hypothesis_fails():
    v = lr.validate_proposal(_proposal(new_hypothesis="", distinct_from_failed_hypothesis=""))
    assert not v["valid"]
    assert any("new_hypothesis" in x for x in v["problems"])


def test_proposal_unmapped_procedure_step_fails():
    p = _proposal()
    p["procedure_status"].pop(lr.registry_procedure()[0])
    v = lr.validate_proposal(p)
    assert not v["valid"]
    assert any("procedure step not addressed" in x for x in v["problems"])


def test_proposal_out_of_scope_candidate_fails():
    v = lr.validate_proposal(_proposal(candidates_requested=[
        {"instrument": "GBPUSD", "timeframe": "H1", "horizon": 12}]))
    assert not v["valid"]
    assert any("not in suspension scope" in x for x in v["problems"])


# ---------------------------------------------------------------- signing
def test_sign_and_verify_roundtrip():
    signed = lr.sign_payload(_proposal(), "secret-key")
    assert lr.verify_integrity(signed, "secret-key")["status"] == "VERIFIED"
    assert lr.verify_integrity(signed, "wrong-key")["status"] == "INVALID"


def test_unsigned_proposal_is_unverified():
    assert lr.verify_integrity(_proposal(), "any")["status"] == "ABSENT"


def test_tamper_after_sign_detected():
    signed = lr.sign_payload(_proposal(), "secret-key")
    signed["new_hypothesis"] = "tampered"
    assert lr.verify_integrity(signed, "secret-key")["status"] == "INVALID"


# ---------------------------------------------------------------- ratification
def test_ratification_binds_to_proposal_hash():
    p = _proposal()
    rr = {
        "approver": "Dadan Hendrawan",
        "decided_at": "2026-11-11T00:00:00Z",
        "proposal_reference": "proposal.json",
        "proposal_hash": lr.proposal_hash(p),
        "decision": "APPROVED",
    }
    assert lr.validate_ratification(rr, p)["valid"]

    other = _proposal(new_hypothesis="different")
    v = lr.validate_ratification(rr, other)
    assert not v["valid"]
    assert any("proposal_hash does not match" in x for x in v["problems"])


# ---------------------------------------------------------------- lifecycle: THE invariant
def test_proposal_keeps_lane_suspended():
    before = lane_status()
    result = lr.assess_lifecycle(proposal=_proposal())
    assert before == lane_status() == "SUSPENDED"
    # Stage may advance to PROPOSED, but training stays blocked.
    assert result["stage"] == lr.STAGE_PROPOSED
    assert result["training_allowed"] is False
    with pytest.raises(GovernanceViolation):
        assert_can("train")


def test_signed_ratification_does_not_reopen_registry():
    key = "the-key"
    p = lr.sign_payload(_proposal(), key)
    rr = lr.sign_payload({
        "approver": "Dadan Hendrawan",
        "decided_at": "2026-11-11T00:00:00Z",
        "proposal_reference": "proposal.json",
        "proposal_hash": lr.proposal_hash(p),
        "decision": "APPROVED",
    }, key)
    lifecycle = lr.assess_lifecycle(proposal=p, ratification=rr, key=key)
    assert lifecycle["stage"] == lr.STAGE_RATIFIED
    # Registry is STILL suspended; training still blocked; guard still armed.
    assert lane_status() == "SUSPENDED"
    assert lifecycle["training_allowed"] is False
    assert lr.assert_suspension_still_enforced() is True
    for action in ("train", "hyperparameter_tune", "promote_model",
                   "enable_live_trading", "auto_reopen"):
        with pytest.raises(GovernanceViolation):
            assert_can(action)


def test_ratification_without_valid_signature_is_not_ratified():
    p = lr.sign_payload(_proposal(), "key1")
    rr = lr.sign_payload({
        "approver": "Dadan Hendrawan", "decided_at": "2026-11-11T00:00:00Z",
        "proposal_reference": "proposal.json",
        "proposal_hash": lr.proposal_hash(p), "decision": "APPROVED",
    }, "key2")
    lifecycle = lr.assess_lifecycle(proposal=p, ratification=rr, key="key1")
    assert lifecycle["stage"] != lr.STAGE_RATIFIED


def test_rejected_ratification_stays_proposed():
    key = "k"
    p = lr.sign_payload(_proposal(), key)
    rr = lr.sign_payload({
        "approver": "Dadan Hendrawan", "decided_at": "2026-11-11T00:00:00Z",
        "proposal_reference": "proposal.json",
        "proposal_hash": lr.proposal_hash(p), "decision": "REJECTED",
    }, key)
    lifecycle = lr.assess_lifecycle(proposal=p, ratification=rr, key=key)
    assert lifecycle["stage"] == lr.STAGE_PROPOSED


# ---------------------------------------------------------------- registry file untouched
def test_governance_registry_bytes_unchanged_by_helpers():
    before = REGISTRY_PATH.read_bytes()
    lr.assess_lifecycle(proposal=lr.sign_payload(_proposal(), "k"), key="k")
    lr.assert_suspension_still_enforced()
    after = REGISTRY_PATH.read_bytes()
    assert before == after
