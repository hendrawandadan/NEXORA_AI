"""Tests for PREP-001 experiment config A/B/C (isolated; no training)."""
from __future__ import annotations

from nexora_audit import experiment_config as ec


def test_three_candidates_defined():
    assert set(ec.BUDGET_CANDIDATES) == {"A", "B", "C"}


def test_values_match_approved_decision():
    assert ec.BUDGET_CANDIDATES["A"].max_depth == -1
    assert ec.BUDGET_CANDIDATES["A"].reg_alpha == 0.0
    assert ec.BUDGET_CANDIDATES["B"].max_depth == 4
    assert ec.BUDGET_CANDIDATES["B"].reg_alpha == 0.1
    assert ec.BUDGET_CANDIDATES["C"].max_depth == 3
    assert ec.BUDGET_CANDIDATES["C"].reg_alpha == 0.5


def test_all_are_experiment_only_not_freeze():
    for cfg in ec.BUDGET_CANDIDATES.values():
        assert cfg.production_freeze is False
    assert ec.EXPERIMENT_ONLY is True


def test_overrides_only_depth_and_alpha():
    assert ec.get_candidate("B").as_overrides() == {"max_depth": 4, "reg_alpha": 0.1}


def test_get_candidate_is_case_insensitive_and_validates():
    assert ec.get_candidate(" b ").name == "B"
    try:
        ec.get_candidate("Z")
    except KeyError:
        pass
    else:
        raise AssertionError("expected KeyError for unknown candidate")


def test_validate_all_passes():
    checks = ec.validate_all()
    assert checks and all(checks.values())
