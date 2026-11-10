"""Integration, governance, and honesty tests (requirements §11.C, §11.D, §11.E, §11.F)."""

import pytest

from nexora_research.external_intelligence import new_information as nii
from nexora_research.external_intelligence import research_bridge as rb
from nexora_research.external_intelligence.new_information import LANE_INFO
from nexora_research.store import ResearchMemoryStore
from nexora_laboratory.governance.lane_suspension import GovernanceViolation


# ---------- fixtures: intelligence inputs ----------
def _event_response():
    return {
        "event_id": 1, "instrument": "EURUSD", "event_ts": "2026-01-15T13:30:00Z",
        "event_type": "CPI", "surprise": 0.3,
        "responses": [
            {"horizon": "15m", "horizon_minutes": 15, "valid": True, "direction": "DOWN"},
            {"horizon": "1h", "horizon_minutes": 60, "valid": True, "direction": "DOWN"},
        ],
    }


# ===================================================================== #
# NEW INFORMATION DISCOVERY (§11.C)
# ===================================================================== #
def test_proposal_from_event_response():
    props = nii.discover_new_information(instrument="EURUSD",
                                         event_responses=[_event_response()])
    assert len(props) == 1
    p = props[0]
    assert p.kind == "EVENT_RESPONSE"
    assert p.lane == LANE_INFO
    assert p.governance_status == "ALLOWED"
    assert p.falsification_criteria
    assert p.data_requirements
    assert p.is_actionable


def test_proposal_requires_surprise():
    er = _event_response(); er["surprise"] = None
    props = nii.discover_new_information(instrument="EURUSD", event_responses=[er])
    assert props == []


def test_proposal_from_cb_shift():
    pc = {"institution": "FED", "policy_shift": "MORE_HAWKISH",
          "latest_published_ts": "2026-03-01T00:00:00Z"}
    props = nii.discover_new_information(instrument="EURUSD", policy_changes=[pc])
    assert any(p.kind == "CB_SHIFT" for p in props)


def test_no_proposal_for_unchanged_policy():
    pc = {"institution": "FED", "policy_shift": "UNCHANGED"}
    props = nii.discover_new_information(instrument="EURUSD", policy_changes=[pc])
    assert props == []


def test_proposal_from_breakdown():
    bd = {"available": True, "breakdown": True, "pair_a": "DXY", "pair_b": "XAUUSD",
          "span": 1.2, "sign_flips": 3}
    props = nii.discover_new_information(instrument="XAUUSD", breakdowns=[bd])
    assert any(p.kind == "XMARKET_BREAKDOWN" for p in props)


def test_no_proposal_for_stable_relationship():
    bd = {"available": True, "breakdown": False, "pair_a": "A", "pair_b": "B"}
    props = nii.discover_new_information(instrument="X", breakdowns=[bd])
    assert props == []


def test_proposals_deterministic_order():
    inputs = dict(event_responses=[_event_response()],
                  policy_changes=[{"institution": "ECB", "policy_shift": "MORE_DOVISH"}],
                  breakdowns=[{"available": True, "breakdown": True, "pair_a": "D", "pair_b": "O"}])
    a = [p.proposal_key for p in nii.discover_new_information(instrument="EURUSD", **{k: v for k, v in inputs.items()})]
    b = [p.proposal_key for p in nii.discover_new_information(instrument="EURUSD", **{k: v for k, v in inputs.items()})]
    assert a == b


def test_all_proposals_target_info_lane_only():
    props = nii.discover_new_information(
        instrument="EURUSD", event_responses=[_event_response()],
        policy_changes=[{"institution": "ECB", "policy_shift": "MORE_DOVISH"}])
    for p in props:
        assert p.lane == LANE_INFO
        assert "SUSPENDED" in p.governance_note


# ===================================================================== #
# RESEARCH MEMORY INTEGRATION (§11.D)
# ===================================================================== #
def test_route_persists_to_external_repo(repo):
    props = nii.discover_new_information(instrument="EURUSD",
                                         event_responses=[_event_response()])
    res = rb.route_to_research_memory(repo, props[0], register=False)
    assert res.persisted is True
    assert repo.count("ext_research_proposals") == 1


def test_route_does_not_register_by_default(repo, tmp_path):
    store = ResearchMemoryStore(tmp_path / "research.db", bootstrap=True)
    props = nii.discover_new_information(instrument="EURUSD",
                                         event_responses=[_event_response()])
    res = rb.route_to_research_memory(repo, props[0], research_store=store, register=False)
    assert res.hypothesis_prepared is False
    assert store.list_hypotheses() == []


def test_route_opt_in_registers_hypothesis_and_experiment(repo, tmp_path):
    store = ResearchMemoryStore(tmp_path / "research.db", bootstrap=True)
    props = nii.discover_new_information(instrument="EURUSD",
                                         event_responses=[_event_response()])
    res = rb.route_to_research_memory(repo, props[0], research_store=store, register=True)
    assert res.hypothesis_prepared is True
    hyps = store.list_hypotheses()
    assert len(hyps) == 1
    # a knowledge STRATEGY_LEAD entry was created and points at external proposal
    from nexora_research.knowledge_query import list_knowledge
    leads = list_knowledge(store, kind="STRATEGY_LEAD")
    assert any("external_proposal" in l["knowledge_key"] for l in leads)


def test_prepare_hypothesis_rejects_blocked():
    p = nii.discover_new_information(instrument="EURUSD",
                                     event_responses=[_event_response()])[0]
    p.governance_status = "BLOCKED_GOVERNANCE"
    with pytest.raises(GovernanceViolation):
        rb.prepare_hypothesis(p)


def test_record_external_finding_into_research_memory(tmp_path):
    store = ResearchMemoryStore(tmp_path / "research.db", bootstrap=True)
    out = rb.record_external_finding(store, finding_key="cpi_us_2026_01",
                                     summary="CPI surprise linked to USD move",
                                     detail={"surprise": 0.3})
    assert out["id"] > 0


# ===================================================================== #
# GOVERNANCE (§11.E)
# ===================================================================== #
def test_bridge_preflight_respects_suspension():
    ok, reason = rb._governance_preflight()
    assert ok is True
    assert "suspension" in reason.lower()


def test_bridge_never_reopens_price_lane():
    # The bridge prohibits train/promote/live/auto_reopen; verify the guard is armed.
    from nexora_laboratory.governance.lane_suspension import assert_can
    for action in ("train", "promote_model", "enable_live_trading", "auto_reopen"):
        with pytest.raises(GovernanceViolation):
            assert_can(action)


def test_prepare_hypothesis_uses_info_lane():
    p = nii.discover_new_information(instrument="EURUSD",
                                     event_responses=[_event_response()])[0]
    hyp = rb.prepare_hypothesis(p)
    assert hyp.signal_source.startswith("external_info:")
    assert hyp.rule_id.startswith("R_EXT_")


def test_blocked_proposal_not_registered(repo, tmp_path):
    store = ResearchMemoryStore(tmp_path / "research.db", bootstrap=True)
    p = nii.discover_new_information(instrument="EURUSD",
                                     event_responses=[_event_response()])[0]
    p.governance_status = "BLOCKED_GOVERNANCE"
    res = rb.route_to_research_memory(repo, p, research_store=store, register=True)
    assert res.hypothesis_prepared is False
    assert store.list_hypotheses() == []


# ===================================================================== #
# DRY-RUN / ISOLATION (§11.F)
# ===================================================================== #
def test_production_db_untouched():
    from nexora_research.external_intelligence.config import (
        PRODUCTION_DB_PATH, EXTERNAL_INTEL_DB_PATH)
    assert EXTERNAL_INTEL_DB_PATH != PRODUCTION_DB_PATH


def test_default_config_is_dry_run():
    from nexora_research.external_intelligence.config import DEFAULT_CONFIG
    assert DEFAULT_CONFIG.dry_run is True
    assert DEFAULT_CONFIG.production_access is False
    assert DEFAULT_CONFIG.model_training is False
    assert DEFAULT_CONFIG.model_promotion is False
    assert DEFAULT_CONFIG.live_trading is False
    assert DEFAULT_CONFIG.auto_reopen is False


def test_no_secret_leak_in_public_config():
    from nexora_research.external_intelligence.config import DEFAULT_CONFIG
    d = DEFAULT_CONFIG.as_public_dict()
    assert "secret" not in str(d).lower()
