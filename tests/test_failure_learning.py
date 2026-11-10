"""Tests for Tahap B — Failure Learning classifier (nexora_research.failure_learning).

Covers: each failure_type classification, priority ordering, the
'failure must teach' invariant (recommendation always present), and the
classify_and_record integration with the Knowledge Memory store.
"""

import pytest

from nexora_research.failure_learning import (
    classify_failure, classify_and_record, FAILURE_TYPES,
)
from nexora_research.store import ResearchMemoryStore


@pytest.fixture()
def store(tmp_path):
    return ResearchMemoryStore(db_path=tmp_path / "research_test.db")


# ---------------- each cause ----------------
def test_data_quality_from_missing():
    d = classify_failure({"data_quality": {"missing_frac": 0.25}})
    assert d.failure_type == "DATA_QUALITY"


def test_data_quality_from_sparse_spread():
    d = classify_failure({"data_quality": {"spread_pct_zero": 0.9}})
    assert d.failure_type == "DATA_QUALITY"


def test_data_quality_from_granularity_break():
    d = classify_failure({"data_quality": {"granularity_break": True}})
    assert d.failure_type == "DATA_QUALITY"


def test_structural_infeasibility():
    d = classify_failure({"feasibility": {"any_feasible_symmetric": False,
                                          "any_feasible_barrier": False}})
    assert d.failure_type == "STRUCTURAL_INFEASIBILITY"


def test_structural_infeasibility_low_ratio():
    d = classify_failure({"feasibility": {"move_to_cost_ratio": 0.5}})
    assert d.failure_type == "STRUCTURAL_INFEASIBILITY"


def test_no_predictive_power():
    d = classify_failure({"feature_power": {"n_usable": 0,
                                            "verdict": "no_feature_clears_oos_ic_bar",
                                            "top_abs_ic": 0.01}})
    assert d.failure_type == "NO_PREDICTIVE_POWER"


def test_edge_below_cost():
    d = classify_failure({"edge": {"auc_net": 0.56, "edge_pips_per_sd": 0.097,
                                   "cost_pips": 3.2}})
    assert d.failure_type == "EDGE_BELOW_COST"


def test_overfit_from_gap():
    d = classify_failure({"train_test": {"train_auc": 0.80, "test_auc": 0.51}})
    assert d.failure_type == "OVERFIT"


def test_overfit_from_unstable_walkforward():
    d = classify_failure({"train_test": {"walk_forward_stable": False}})
    assert d.failure_type == "OVERFIT"


def test_regime_fragile():
    d = classify_failure({"stability": {"regime_fail_fraction": 0.5}})
    assert d.failure_type == "REGIME_FRAGILE"


def test_unknown_when_no_evidence():
    d = classify_failure(None)
    assert d.failure_type == "UNKNOWN"


# ---------------- priority ordering ----------------
def test_data_quality_wins_over_structural():
    d = classify_failure({
        "data_quality": {"missing_frac": 0.3},
        "feasibility": {"any_feasible_symmetric": False},
    })
    assert d.failure_type == "DATA_QUALITY"


def test_structural_wins_over_no_power():
    d = classify_failure({
        "feasibility": {"move_to_cost_ratio": 0.5},
        "feature_power": {"n_usable": 0},
    })
    assert d.failure_type == "STRUCTURAL_INFEASIBILITY"


def test_no_power_wins_over_edge():
    d = classify_failure({
        "feature_power": {"n_usable": 0},
        "edge": {"auc_net": 0.5, "edge_pips_per_sd": 0.0, "cost_pips": 3.0},
    })
    assert d.failure_type == "NO_PREDICTIVE_POWER"


# ---------------- invariant: always teaches ----------------
@pytest.mark.parametrize("ev", [
    None, {}, {"data_quality": {"missing_frac": 0.5}},
    {"feasibility": {"move_to_cost_ratio": 0.1}},
    {"feature_power": {"n_usable": 0}}, {"edge": {"auc_net": 0.6, "edge_pips_per_sd": 0.1, "cost_pips": 3.0}},
    {"train_test": {"train_auc": 0.9, "test_auc": 0.5}}, {"stability": {"year_fail_fraction": 0.5}},
])
def test_always_has_recommendation_and_valid_type(ev):
    d = classify_failure(ev)
    assert d.recommendation.strip()
    assert d.failure_type in FAILURE_TYPES


# ---------------- integration: classify_and_record ----------------
def test_classify_and_record_persists(store):
    h = store.register_hypothesis(hypothesis_key="H1", instrument="EURUSD",
                                  timeframe="M30", horizon_bars=2, claim="x")
    e = store.create_experiment(experiment_key="E1", hypothesis_id=h["id"], spec={})
    out = classify_and_record(store, experiment_id=e["id"],
                              evidence={"edge": {"auc_net": 0.55, "edge_pips_per_sd": 0.097, "cost_pips": 3.2}})
    assert out["diagnosis"]["failure_type"] == "EDGE_BELOW_COST"
    assert out["failure_row_id"] >= 1
    assert out["knowledge_row_id"] >= 1
    # persisted in DB
    fails = store.list_failures(experiment_id=e["id"])
    assert len(fails) == 1
    assert fails[0]["failure_type"] == "EDGE_BELOW_COST"


def test_classify_and_record_requires_experiment(store):
    with pytest.raises(KeyError):
        classify_and_record(store, experiment_id=999, evidence={})
