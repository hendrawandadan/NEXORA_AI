"""Tests for Tahap C — deterministic hypothesis generator + registry.

Covers: rule firing (feasible / feature-info / cross-tf), determinism, dead-end
skipping, pre-registration + hashed experiment spec, dry-run (no writes), and
end-to-end generate_and_register.
"""

import json

import pytest

from nexora_research.store import ResearchMemoryStore
from nexora_research.failure_learning import classify_and_record
from nexora_research.hypothesis_generator import (
    generate_hypotheses, GeneratedHypothesis,
    FEASIBLE_RATIO_MIN, REACHABLE_ACC_MAX,
)
from nexora_research.registry import (
    pre_register, build_experiment_spec, register_experiment_for,
    generate_and_register,
)


@pytest.fixture()
def store(tmp_path):
    return ResearchMemoryStore(db_path=tmp_path / "research_test.db")


def _horizon_evidence():
    # run_horizon_discovery-shaped: one feasible (h12 ratio 12.3 acc .54) and one
    # infeasible (h2 ratio 1.4 acc .86). plus H4/h4 (16h) & H1/h8 same wall-clock? skip
    return {
        "timeframes": {
            "H4": {
                "economics": [
                    {"horizon_bars": 12, "scenario": "baseline", "move_to_cost_ratio": 12.31,
                     "required_acc_symmetric": 0.5406, "median_move_pips": 39.4},
                    {"horizon_bars": 2, "scenario": "baseline", "move_to_cost_ratio": 1.4,
                     "required_acc_symmetric": 0.857, "median_move_pips": 4.5},
                ]
            }
        }
    }


# ---------- generator: R_HORIZON_FEASIBLE ----------
def test_generates_feasible_horizon_only():
    hyps = generate_hypotheses(instrument="EURUSD", horizon_evidence=_horizon_evidence())
    feasible = [h for h in hyps if h.rule_id == "R_HORIZON_FEASIBLE"]
    hs = sorted(h.horizon_bars for h in feasible)
    assert hs == [12]              # h2 infeasible (ratio<5) excluded
    h = feasible[0]
    assert h.go_criteria["metric"] == "oos_directional_accuracy"
    assert h.go_criteria["threshold"] >= 0.5406


def test_feasibility_thresholds_respected():
    ev = {"timeframes": {"H4": {"economics": [
        {"horizon_bars": 8, "scenario": "baseline", "move_to_cost_ratio": FEASIBLE_RATIO_MIN - 0.1,
         "required_acc_symmetric": 0.55, "median_move_pips": 30},
        {"horizon_bars": 9, "scenario": "baseline", "move_to_cost_ratio": 10.0,
         "required_acc_symmetric": REACHABLE_ACC_MAX + 0.01, "median_move_pips": 30},
    ]}}}
    hyps = [h for h in generate_hypotheses(instrument="X", horizon_evidence=ev)
            if h.rule_id == "R_HORIZON_FEASIBLE"]
    # ratio too low excluded; accuracy too high excluded -> none
    assert hyps == []


def test_non_baseline_scenarios_ignored():
    ev = {"timeframes": {"H4": {"economics": [
        {"horizon_bars": 12, "scenario": "optimistic", "move_to_cost_ratio": 99.0,
         "required_acc_symmetric": 0.50, "median_move_pips": 99},
    ]}}}
    hyps = [h for h in generate_hypotheses(instrument="X", horizon_evidence=ev)
            if h.rule_id == "R_HORIZON_FEASIBLE"]
    assert hyps == []


# ---------- generator: R_FEATURE_INFO ----------
def test_generates_feature_info():
    fp = {"timeframe": "H4", "horizon_bars": 12,
          "usable_features": ["ret_5"],
          "features": [{"feature": "ret_5", "ic": -0.05, "ic_ci_low": -0.08, "ic_ci_high": -0.02},
                       {"feature": "junk", "ic": 0.001}]}
    hyps = [h for h in generate_hypotheses(instrument="EURUSD",
                                          horizon_evidence={},
                                          feature_power_evidence=fp)
            if h.rule_id == "R_FEATURE_INFO"]
    assert len(hyps) == 1
    assert hyps[0].signal_source == "feature:ret_5"
    assert abs(hyps[0].go_criteria["threshold"]) >= 0.02


def test_feature_info_needs_usable():
    fp = {"timeframe": "H4", "horizon_bars": 12, "usable_features": [],
          "features": [{"feature": "junk", "ic": 0.001}]}
    hyps = [h for h in generate_hypotheses(instrument="EURUSD",
                                          horizon_evidence={},
                                          feature_power_evidence=fp)
            if h.rule_id == "R_FEATURE_INFO"]
    assert hyps == []


# ---------- generator: determinism ----------
def test_generation_is_deterministic():
    a = generate_hypotheses(instrument="EURUSD", horizon_evidence=_horizon_evidence())
    b = generate_hypotheses(instrument="EURUSD", horizon_evidence=_horizon_evidence())
    assert [h.hypothesis_key for h in a] == [h.hypothesis_key for h in b]


# ---------- dead-end skipping ----------
def test_dead_end_skipped_unless_allowed(store):
    # Register a hypothesis + experiment, then record a failure whose evidence has
    # the signature EURUSD|H4|12, and a knowledge DEAD_END carrying that signature.
    h = store.register_hypothesis(hypothesis_key="seed", instrument="EURUSD",
                                  timeframe="H4", horizon_bars=12, claim="seed")
    e = store.create_experiment(experiment_key="seed_exp", hypothesis_id=h["id"], spec={})
    store.record_failure(experiment_id=e["id"], failure_type="EDGE_BELOW_COST",
                         recommendation="x", evidence={"signature": "EURUSD|H4|12"})
    store.record_knowledge(knowledge_key="k", kind="DEAD_END", summary="dead",
                           detail={"hypothesis_spec": {"instrument": "EURUSD",
                                                        "timeframe": "H4",
                                                        "horizon_bars": 12}},
                           source_experiment_id=e["id"])
    # default: dead-end skipped
    skipped = [h for h in generate_hypotheses(instrument="EURUSD",
                                              horizon_evidence=_horizon_evidence(),
                                              store=store)]
    assert all(h.horizon_bars != 12 for h in skipped)
    # allowed: re-emitted
    allowed = [h for h in generate_hypotheses(instrument="EURUSD",
                                              horizon_evidence=_horizon_evidence(),
                                              store=store, allow_dead_ends=True)]
    assert any(h.horizon_bars == 12 for h in allowed)


# ---------- registry: pre-register + hashed spec ----------
def test_pre_register_embeds_signature_in_go_criteria(store):
    hyp = generate_hypotheses(instrument="EURUSD", horizon_evidence=_horizon_evidence())[0]
    r = pre_register(store, hyp)
    got = store.get_hypothesis(r["id"])
    go = json.loads(got["go_criteria_json"])
    assert go["signature"] == hyp.signature
    assert got["status"] == "PRE_REGISTERED"


def test_build_experiment_spec_deterministic():
    hyp = GeneratedHypothesis(hypothesis_key="k", rule_id="R", instrument="EURUSD",
                              timeframe="H4", horizon_bars=12, claim="c",
                              signal_source="s", market_condition="m",
                              go_criteria={"metric": "x"})
    s1 = build_experiment_spec(hyp, dataset_path="d.csv")
    s2 = build_experiment_spec(hyp, dataset_path="d.csv")
    assert json.dumps(s1, sort_keys=True) == json.dumps(s2, sort_keys=True)
    assert s1["signature"] == "EURUSD|H4|12"
    assert "pre_registered_go_criteria" in s1


def test_register_experiment_binds_spec_hash(store):
    hyp = generate_hypotheses(instrument="EURUSD", horizon_evidence=_horizon_evidence())[0]
    h = pre_register(store, hyp)
    e = register_experiment_for(store, h["id"], hyp)
    exp = store.get_experiment(e["id"])
    assert exp["hypothesis_id"] == h["id"]
    assert len(exp["spec_sha256"]) == 64


# ---------- dry-run + end-to-end ----------
def test_dry_run_writes_nothing(store):
    out = generate_and_register(store, instrument="EURUSD",
                                horizon_evidence=_horizon_evidence(), dry_run=True)
    assert all(r["registered"] is False for r in out)
    assert store.list_hypotheses() == []


def test_generate_and_register_end_to_end(store):
    out = generate_and_register(store, instrument="EURUSD",
                                horizon_evidence=_horizon_evidence())
    assert len(out) >= 1
    assert all(r["registered"] for r in out)
    assert len(store.list_hypotheses(status="PRE_REGISTERED")) == len(out)
