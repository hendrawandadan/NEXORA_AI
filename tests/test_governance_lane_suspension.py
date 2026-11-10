"""Tests for NEXORA-GOV-PRD-001 — Price-Derived Research Lane suspension guard."""

import json
from pathlib import Path

import pytest

from nexora_laboratory.governance.lane_suspension import (
    load_registry, lane_status, is_suspended, assert_can, can, GovernanceViolation,
    suspended_candidates, is_candidate_suspended, assert_candidate_not_suspended,
    PROHIBITED_ACTIONS, ALLOWED_ACTIONS,
)

REPO = Path(__file__).resolve().parents[1]
REG = REPO / "config" / "governance" / "price_derived_lane_suspension.json"


# ---------- registry integrity ----------
def test_registry_exists_and_parses():
    reg = load_registry(REG)
    assert reg["decision_id"] == "NEXORA-GOV-PRD-001"


def test_status_is_suspended():
    assert lane_status(REG) == "SUSPENDED"
    assert is_suspended(REG) is True


def test_registry_reopenable_and_authority():
    reg = load_registry(REG)
    assert reg["reopenability"] == "REOPENABLE_WITH_EVIDENCE_AND_AUTHORIZATION"
    assert "explicit user" in reg["authority"].lower()


def test_registry_scope_matches_five_candidates():
    reg = load_registry(REG)
    assert len(reg["suspended_candidates"]) == 5
    keys = {(c["instrument"], c["timeframe"], c["horizon"]) for c in reg["suspended_candidates"]}
    assert keys == {("XAUUSD", "D1", 1), ("XAUUSD", "D1", 2),
                    ("XAUUSD", "H4", 8), ("XAUUSD", "H4", 12),
                    ("EURUSD", "H4", 12)}


# ---------- prohibited actions blocked ----------
@pytest.mark.parametrize("action", sorted(PROHIBITED_ACTIONS))
def test_prohibited_actions_raise(action):
    with pytest.raises(GovernanceViolation):
        assert_can(action, path=REG)


def test_train_blocked():
    with pytest.raises(GovernanceViolation):
        assert_can("train", path=REG)


def test_authorized_flag_does_not_bypass():
    # authorized=True must NOT allow training while suspended (requires status change)
    with pytest.raises(GovernanceViolation):
        assert_can("train", path=REG, authorized=True)


def test_unknown_action_fail_closed():
    with pytest.raises(GovernanceViolation):
        assert_can("something_new", path=REG)


# ---------- allowed (knowledge) actions pass ----------
@pytest.mark.parametrize("action", sorted(ALLOWED_ACTIONS))
def test_allowed_actions_pass(action):
    assert_can(action, path=REG)  # should not raise
    assert can(action, path=REG) is True


def test_can_helper_returns_false_for_prohibited():
    assert can("train", path=REG) is False
    assert can("promote_model", path=REG) is False


# ---------- candidate-level guard ----------
def test_suspended_candidates_listed():
    cands = suspended_candidates(REG)
    assert len(cands) == 5


def test_candidate_suspension_lookup():
    assert is_candidate_suspended("XAUUSD", "D1", 2, path=REG) is True
    assert is_candidate_suspended("EURUSD", "H4", 12, path=REG) is True
    assert is_candidate_suspended("XAUUSD", "H1", 24, path=REG) is False


def test_candidate_guard_blocks_train():
    with pytest.raises(GovernanceViolation):
        assert_candidate_not_suspended("XAUUSD", "D1", 2, action="train", path=REG)


# ---------- evidence references exist ----------
def test_evidence_files_exist():
    reg = load_registry(REG)
    for name, rel in reg["evidence"].items():
        assert (REPO / rel).exists(), f"evidence missing: {name} -> {rel}"


# ---------- decision record file present ----------
def test_decision_record_markdown_exists():
    p = REPO / "reports" / "economic_opportunity_discovery" / "GOVERNANCE_DECISION_PRD_001.md"
    assert p.exists()
    txt = p.read_text(encoding="utf-8")
    assert "NEXORA-GOV-PRD-001" in txt
    assert "SUSPENDED" in txt
