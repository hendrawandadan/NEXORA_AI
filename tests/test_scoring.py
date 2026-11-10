"""Tests for STAGE 6 — Economic Opportunity Assessment (scoring module)."""

import pytest

from nexora_laboratory.opportunity_discovery.scoring import (
    econ_component, cost_component, signal_component, opportunity_score, verdict,
    assess_candidate, rank_candidates, WEIGHTS,
    SIGNAL_FLOOR_FOR_CANDIDATE, SIGNAL_FLOOR_MIN,
)


# ---------- economics component ----------
def test_econ_component_saturates_at_10x():
    assert econ_component(10.0) == 1.0
    assert econ_component(20.0) == 1.0
    assert econ_component(5.0) == pytest.approx(0.5)
    assert econ_component(None) == 0.0
    assert econ_component(0.0) == 0.0


def test_cost_component_inverse_drag():
    assert cost_component(0.0) == 1.0
    assert cost_component(0.5) == pytest.approx(0.5)
    assert cost_component(1.0) == 0.0
    assert cost_component(2.0) == 0.0  # capped
    assert cost_component(None) == 0.0


# ---------- signal component (strict) ----------
def _row(feature, test_ic, train_ic, sign_consistent):
    return {"feature": feature, "test_ic": test_ic, "train_ic": train_ic,
            "sign_consistent": sign_consistent}


def test_signal_rewards_stable_feature():
    # test IC 0.08, train IC 0.05, same sign -> should score well
    r = signal_component([_row("f", 0.08, 0.05, True)])
    assert r["signal_quality"] > 0.5


def test_signal_penalises_sign_flip():
    stable = signal_component([_row("f", 0.08, 0.05, True)])["signal_quality"]
    flip = signal_component([_row("f", 0.08, -0.05, False)])["signal_quality"]
    assert flip < stable


def test_signal_penalises_train_near_zero():
    # large test IC but train ~0 -> regime artifact -> low score
    r = signal_component([_row("f", 0.12, 0.001, True)])
    assert r["signal_quality"] < 0.10


def test_signal_zero_without_test_ic():
    assert signal_component([_row("f", None, 0.05, True)])["signal_quality"] == 0.0


def test_signal_picks_best_feature():
    rows = [_row("bad", 0.12, 0.0, True), _row("good", 0.06, 0.05, True)]
    r = signal_component(rows)
    # best feature score is the good one (bad is penalised on train~0)
    assert r["signal_quality"] > 0.3


# ---------- weights & score ----------
def test_weights_sum_to_one():
    assert sum(WEIGHTS.values()) == pytest.approx(1.0)


def test_opportunity_score_weighted():
    s = opportunity_score(1.0, 1.0, 1.0, 1.0)
    assert s == 1.0
    s2 = opportunity_score(0.0, 0.0, 0.0, 0.0)
    assert s2 == 0.0


# ---------- verdict gating ----------
def test_verdict_high_score_low_signal_is_economics_only():
    v = verdict(0.80, signal_quality=0.05, economics=0.9)
    assert v == "WATCH_ECONOMICS_ONLY"


def test_verdict_below_min_signal_low_econ_is_reject():
    v = verdict(0.30, signal_quality=0.02, economics=0.1)
    assert v == "REJECT"


def test_verdict_midsignal_caps_at_watch():
    # signal between MIN and FLOOR -> cannot be candidate even if score high
    v = verdict(0.90, signal_quality=0.20, economics=1.0)
    assert v == "WATCH"


def test_verdict_candidate_requires_signal_floor():
    v = verdict(0.80, signal_quality=0.45, economics=1.0)
    assert v == "RESEARCH_CANDIDATE"


def test_verdict_candidate_but_low_score_is_watch():
    v = verdict(0.50, signal_quality=0.40, economics=0.5)
    assert v == "WATCH"


# ---------- assess_candidate ----------
def test_assess_candidate_full():
    rows = [_row("f", 0.07, 0.05, True)]
    c = assess_candidate(instrument="X", timeframe="H4", horizon=12,
                         move_to_cost_ratio=30.0, cost_drag=0.03,
                         data_readiness=0.98, ic_rows=rows)
    assert c["opportunity_score"] > 0.6
    assert c["verdict"] == "RESEARCH_CANDIDATE"
    assert c["components"]["signal_quality"] > 0.3


def test_assess_candidate_unstable_signal_watch():
    rows = [_row("f", 0.10, 0.0, True)]  # train ~0 -> artifact
    c = assess_candidate(instrument="X", timeframe="H1", horizon=24,
                         move_to_cost_ratio=40.0, cost_drag=0.02,
                         data_readiness=0.98, ic_rows=rows)
    assert c["verdict"] in ("WATCH", "WATCH_ECONOMICS_ONLY")


# ---------- ranking ----------
def test_rank_candidates_desc():
    rows_good = [_row("f", 0.08, 0.05, True)]
    rows_bad = [_row("f", 0.12, 0.0, True)]
    c_good = assess_candidate(instrument="A", timeframe="H4", horizon=12,
                              move_to_cost_ratio=20, cost_drag=0.05,
                              data_readiness=0.9, ic_rows=rows_good)
    c_bad = assess_candidate(instrument="B", timeframe="H1", horizon=24,
                             move_to_cost_ratio=20, cost_drag=0.05,
                             data_readiness=0.9, ic_rows=rows_bad)
    ranked = rank_candidates([c_bad, c_good])
    assert ranked[0]["opportunity_score"] >= ranked[1]["opportunity_score"]
