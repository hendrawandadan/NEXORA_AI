"""Tests for configuration freeze v2 (Part A) and timing contract (Part B).

Read-only. Verifies:
* After PREP-001 B1/B2 owner decisions, max_depth=-1, reg_alpha=0.0 and
  decision_time_policy=bar_open are frozen explicitly (current-effective defaults),
  making the config manifest complete and reproducible.
* lightgbm is pinned to 4.7.0 only when the runtime supports it.
* Feature/target/split versions are deterministic content-derived ids.
* The freeze hash is reproducible and complete after the owner decisions.
* The timing contract marks provable fields PROVEN and owner-approved design
  choices OWNER_APPROVED; ratified stays False until a human HMAC sign-off, so
  the timing gate remains UNRESOLVED. Never asserts future information.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from nexora_audit.configuration_freeze import (
    FEATURE_COLUMNS,
    FROZEN,
    REQUIRES_DECISION,
    build_frozen_manifest,
    feature_set_version,
    split_policy_version,
    target_definition_version,
)
from nexora_audit.readiness import check_config_ready_freeze, check_timing_ready
from nexora_audit.timing_contract import (
    NEW_DESIGN,
    PROVEN,
    build_timing_contract,
)

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_engine_and_objective_and_max_iter_are_frozen():
    manifest = build_frozen_manifest(PROJECT_ROOT)
    assert manifest.frozen_value("engine") == "lightgbm"
    assert manifest.frozen_value("objective") == "binary"
    assert manifest.frozen_value("max_iter") == 300
    assert manifest.is_frozen("max_iter")


def test_lightgbm_pinned_to_verified_runtime():
    manifest = build_frozen_manifest(PROJECT_ROOT)
    assert manifest.frozen_value("engine_version") == "4.7.0"
    assert manifest.runtime["lightgbm"] == "4.7.0"


def test_max_depth_and_reg_alpha_now_frozen_explicitly_owner_approved():
    manifest = build_frozen_manifest(PROJECT_ROOT)
    # PREP-001 B1 resolution: owner froze the current-effective defaults explicitly.
    assert manifest.is_frozen("max_depth")
    assert manifest.is_frozen("l1_regularization")
    assert manifest.frozen_value("max_depth") == -1
    assert manifest.frozen_value("l1_regularization") == 0.0
    assert not manifest.requires("max_depth")
    assert not manifest.requires("l1_regularization")


def test_feature_version_is_deterministic_and_matches_contract():
    first = feature_set_version()
    second = feature_set_version()
    assert first["id"] == second["id"]
    assert first["hash"] == second["hash"]
    assert len(first["columns"]) == 29
    assert tuple(first["columns"]) == FEATURE_COLUMNS


def test_target_and_split_versions_deterministic():
    assert target_definition_version(2)["id"] == target_definition_version(2)["id"]
    assert target_definition_version(2)["id"] != target_definition_version(4)["id"]
    assert split_policy_version()["id"] == split_policy_version()["id"]


def test_version_ids_are_frozen_into_manifest():
    manifest = build_frozen_manifest(PROJECT_ROOT)
    assert manifest.is_frozen("feature_set_version")
    assert manifest.is_frozen("target_definition_version")
    assert manifest.is_frozen("split_policy_version")
    assert manifest.frozen_value("feature_set_version") == manifest.feature_version["id"]


def test_freeze_hash_reproducible_and_complete_after_owner_decisions():
    a = build_frozen_manifest(PROJECT_ROOT).config_hash()
    b = build_frozen_manifest(PROJECT_ROOT).config_hash()
    assert a["hash"] == b["hash"]
    # PREP-001 B1/B2 resolved: max_depth, reg_alpha, decision_time_policy frozen.
    assert a["complete"] is True
    assert a["requires_decision"] == []


def test_config_gate_passes_with_complete_freeze_no_human_ratification_needed():
    manifest = build_frozen_manifest(PROJECT_ROOT)
    report = check_config_ready_freeze(manifest)
    # A fully-frozen manifest PASSES config readiness (values evidenced & explicit).
    assert report.status == "PASS"
    assert report.evidence.get("complete") is True


def test_timing_contract_separates_proven_from_owner_approved_design():
    from nexora_audit.timing_contract import OWNER_APPROVED
    contract = build_timing_contract()
    proven = {f.name for f in contract.fields if f.status == PROVEN}
    approved = {f.name for f in contract.fields if f.status == OWNER_APPROVED}
    design = {f.name for f in contract.fields if f.status == NEW_DESIGN}
    # Leakage-avoidance facts are provable.
    assert "candle_close_timestamp" in proven
    assert "feature_availability_timestamp" in proven
    assert "no_future_information_rule" in proven
    # Execution/decision clock and cost model are owner-approved (not NEW_DESIGN, not human-ratified).
    for name in ("decision_timestamp", "earliest_executable_timestamp",
                 "execution_price_model", "spread_usage", "slippage_usage", "cost_usage"):
        assert name in approved
    assert design == set()


def test_timing_contract_owner_approved_but_not_human_ratified_blocks_gate():
    contract = build_timing_contract()
    info = contract.contract_hash()
    # Owner-approved != human-ratified. ratified stays False (no HMAC sign-off).
    assert info["ratified"] is False
    assert info["owner_approved"] is True
    assert info["new_design_fields"] == []
    report = check_timing_ready(contract)
    # Without human ratification the timing gate MUST remain UNRESOLVED.
    assert report.status == "UNRESOLVED"


def test_timing_contract_hash_reproducible():
    a = build_timing_contract().contract_hash()["hash"]
    b = build_timing_contract().contract_hash()["hash"]
    assert a == b


def test_manifest_to_dict_has_all_sections():
    d = build_frozen_manifest(PROJECT_ROOT).to_dict()
    for key in ("config_hash", "frozen_parameters", "requires_decision",
                "feature_set_version", "target_definition_version", "split_policy_version"):
        assert key in d
    for entry in d["frozen_parameters"]:
        assert entry["state"] == FROZEN
    for entry in d["requires_decision"]:
        assert entry["state"] == REQUIRES_DECISION
