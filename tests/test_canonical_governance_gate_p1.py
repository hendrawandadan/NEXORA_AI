"""P1 — Canonical Governance Gate for research_bridge.

Proves that EVERY research path (control loop AND research_bridge, direct and indirect)
passes through ONE canonical governance gate with identical rules, with NO bypass:

  * INFO_ACQUISITION (valid) passes the gate while the price-derived lane is SUSPENDED.
  * PRICE_DERIVED is always blocked while the suspension is active.
  * UNKNOWN lane is blocked.
  * Any governance_status other than ALLOWED is blocked.
  * research_bridge cannot bypass the canonical gate (it delegates to it).
  * Direct and indirect calls are subject to the same rules.
  * No experiment registration escapes the gate.
  * No training / tuning / promotion / live trading / auto-reopen.
  * No production-DB writes.

These are negative/positive assertions on real code paths, not mocks of the gate.
"""

import hashlib
from pathlib import Path

import pytest

from nexora_research.control_loop import (
    run_control_loop, canonical_governance_gate, GovernanceDecision,
    INFO_ACQUISITION_LANE,
)
from nexora_research.external_intelligence import new_information as nii
from nexora_research.external_intelligence import research_bridge as rb
from nexora_research.external_intelligence.new_information import LANE_INFO
from nexora_research.store import ResearchMemoryStore
from nexora_laboratory.governance.lane_suspension import (
    GovernanceViolation, assert_can, is_suspended,
)


# ---------------------------------------------------------------- fixtures
def _event_response():
    return {
        "event_id": 1, "instrument": "EURUSD", "event_ts": "2026-01-15T13:30:00Z",
        "event_type": "CPI", "surprise": 0.3,
        "responses": [
            {"horizon": "15m", "horizon_minutes": 15, "valid": True, "direction": "DOWN"},
            {"horizon": "1h", "horizon_minutes": 60, "valid": True, "direction": "DOWN"},
        ],
    }


def _proposal(instrument="EURUSD"):
    return nii.discover_new_information(
        instrument=instrument, event_responses=[_event_response()])[0]


def _suspended_price_candidate():
    # EURUSD H4 h12 is a suspended price-derived candidate in the registry.
    return dict(lane="PRICE_DERIVED", governance_status="ALLOWED", rule_id="R_HORIZON",
                instrument="EURUSD", timeframe="H4", horizon=12)


@pytest.fixture
def repo(tmp_path):
    from nexora_research.external_intelligence.repository import ExternalKnowledgeRepository
    return ExternalKnowledgeRepository(tmp_path / "ext.db", bootstrap=True)


# ==================================================================== #
# 1. Preconditions: the price-derived lane is SUSPENDED.
# ==================================================================== #
def test_precondition_price_lane_suspended():
    assert is_suspended() is True


# ==================================================================== #
# 2. Canonical gate — direct unit tests of each rule.
# ==================================================================== #
def test_gate_allows_valid_info_acquisition():
    d = canonical_governance_gate(lane=LANE_INFO, governance_status="ALLOWED",
                                  rule_id="R_EXT_EVENT_RESPONSE",
                                  instrument="EURUSD", timeframe="external", horizon=1)
    assert isinstance(d, GovernanceDecision)
    assert d.allowed is True
    assert bool(d) is True
    assert d.status == "ALLOWED"


def test_gate_blocks_price_derived_while_suspended():
    d = canonical_governance_gate(**_suspended_price_candidate())
    assert d.allowed is False
    assert "SUSPENDED" in d.reason.upper()


def test_gate_blocks_unknown_lane():
    d = canonical_governance_gate(lane="UNKNOWN", governance_status="ALLOWED",
                                  rule_id="R_X")
    assert d.allowed is False
    assert "unknown lane" in d.reason.lower()


def test_gate_blocks_none_lane():
    d = canonical_governance_gate(lane=None, governance_status="ALLOWED")
    assert d.allowed is False


@pytest.mark.parametrize("status", ["BLOCKED_GOVERNANCE", "UNKNOWN", "PENDING",
                                    "", None, "invalid"])
def test_gate_blocks_non_allowed_governance_status(status):
    d = canonical_governance_gate(lane=LANE_INFO, governance_status=status,
                                  rule_id="R_EXT_EVENT_RESPONSE")
    assert d.allowed is False


def test_gate_blocks_price_rule_smuggled_under_info_lane():
    # An R_* (non R_EXT_) rule id on the INFO lane is re-checked as price-derived.
    d = canonical_governance_gate(
        lane=LANE_INFO, governance_status="ALLOWED", rule_id="R_HORIZON",
        instrument="EURUSD", timeframe="H4", horizon=12)
    assert d.allowed is False


# ==================================================================== #
# 3. research_bridge DELEGATES to the canonical gate (no bypass).
# ==================================================================== #
def test_bridge_gate_is_canonical():
    from nexora_research.control_loop import canonical_governance_gate as canon
    # rb._governance_gate must produce the same verdict as the canonical gate.
    p = _proposal()
    d_bridge = rb._governance_gate(p)
    d_canon = canon(lane=p.lane, governance_status=p.governance_status,
                    rule_id=f"R_EXT_{p.kind}", instrument=p.instrument,
                    timeframe="external", horizon=1)
    assert d_bridge.as_dict() == d_canon.as_dict()


def test_bridge_prepare_hypothesis_raises_when_gate_blocks():
    p = _proposal()
    p.governance_status = "BLOCKED_GOVERNANCE"
    with pytest.raises(GovernanceViolation):
        rb.prepare_hypothesis(p)


def test_bridge_route_blocks_non_allowed_status_and_no_registration(repo, tmp_path):
    store = ResearchMemoryStore(tmp_path / "research.db", bootstrap=True)
    p = _proposal()
    p.governance_status = "UNKNOWN"
    res = rb.route_to_research_memory(repo, p, research_store=store, register=True)
    assert res.hypothesis_prepared is False
    assert store.list_hypotheses() == []            # nothing registered
    assert store.list_failures() == []
    # The blocked attempt IS persisted as provenance (audit trail), never registered.
    assert repo.count("ext_research_proposals") == 1
    assert "canonical governance gate" in res.reason.lower()


def test_bridge_route_blocks_price_lane_proposal(repo, tmp_path):
    # A price-derived proposal forced into the bridge must be blocked by the gate.
    store = ResearchMemoryStore(tmp_path / "research.db", bootstrap=True)
    p = _proposal()
    p.lane = "PRICE_DERIVED"  # attempt to route a price-derived proposal
    res = rb.route_to_research_memory(repo, p, research_store=store, register=True)
    assert res.hypothesis_prepared is False
    assert store.list_hypotheses() == []


def test_bridge_route_registers_valid_info_and_records_audit_trail(repo, tmp_path):
    store = ResearchMemoryStore(tmp_path / "research.db", bootstrap=True)
    p = _proposal()
    res = rb.route_to_research_memory(repo, p, research_store=store, register=True)
    assert res.hypothesis_prepared is True
    hyps = store.list_hypotheses()
    assert len(hyps) == 1
    # Audit trail: the STRATEGY_LEAD knowledge entry records the gate verdict.
    import json
    from nexora_research.knowledge_query import list_knowledge
    leads = list_knowledge(store, kind="STRATEGY_LEAD")
    ext = [l for l in leads if "external_proposal" in l["knowledge_key"]]
    assert ext, "audit-trail knowledge entry must exist"
    detail = json.loads(ext[0]["detail_json"])
    assert detail["gate"]["allowed"] is True
    assert detail["gate"]["lane"] == LANE_INFO


def test_bridge_route_no_registration_when_register_false(repo, tmp_path):
    store = ResearchMemoryStore(tmp_path / "research.db", bootstrap=True)
    res = rb.route_to_research_memory(repo, _proposal(), research_store=store,
                                      register=False)
    assert res.hypothesis_prepared is False
    assert store.list_hypotheses() == []


# ==================================================================== #
# 4. Control loop uses the SAME gate; blocked proposals never register.
# ==================================================================== #
def test_loop_info_acquisition_passes_gate(tmp_path):
    store = ResearchMemoryStore(tmp_path / "research.db", bootstrap=True)
    report = run_control_loop(instrument="EURUSD", horizon_evidence=None, store=store,
                              external_proposals=[_proposal()])
    ext = [o for o in report.outcomes if o.lane == INFO_ACQUISITION_LANE]
    assert ext and ext[0].phase == "READY_FOR_CONFIRMATORY_EXPERIMENT"
    assert ext[0].hypothesis_id is not None       # registered (allowed)
    assert ext[0].experiment_id is not None


def test_loop_blocked_status_never_registers(tmp_path):
    store = ResearchMemoryStore(tmp_path / "research.db", bootstrap=True)
    p = _proposal()
    p.governance_status = "BLOCKED_GOVERNANCE"
    report = run_control_loop(instrument="EURUSD", horizon_evidence=None, store=store,
                              external_proposals=[p])
    ext = [o for o in report.outcomes if o.lane == INFO_ACQUISITION_LANE]
    assert ext and ext[0].phase == "BLOCKED_GOVERNANCE"
    assert ext[0].hypothesis_id is None
    assert ext[0].experiment_id is None
    assert store.list_hypotheses() == []          # nothing escaped the gate


def test_loop_unknown_lane_proposal_blocked_no_registration(tmp_path):
    store = ResearchMemoryStore(tmp_path / "research.db", bootstrap=True)
    p = _proposal()
    p.lane = "UNKNOWN"
    report = run_control_loop(instrument="EURUSD", horizon_evidence=None, store=store,
                              external_proposals=[p])
    blocked = [o for o in report.outcomes if o.phase == "BLOCKED_GOVERNANCE"]
    assert blocked, "unknown lane must be BLOCKED"
    assert store.list_hypotheses() == []


def test_loop_price_derived_candidate_still_blocked_while_suspended(tmp_path):
    store = ResearchMemoryStore(tmp_path / "research.db", bootstrap=True)
    horizon_evidence = {
        "timeframe": "H4",
        "economics": [{"scenario": "baseline", "horizon_bars": 12,
                       "move_to_cost_ratio": 8.0, "required_acc_symmetric": 0.55,
                       "median_move_pips": 40.0}],
    }
    report = run_control_loop(instrument="EURUSD", horizon_evidence=horizon_evidence,
                              timeframe="H4", store=store)
    price = [o for o in report.outcomes if o.lane != INFO_ACQUISITION_LANE]
    assert any(o.phase == "BLOCKED_GOVERNANCE" for o in price)


# ==================================================================== #
# 5. Direct AND indirect paths share identical rules.
# ==================================================================== #
def test_direct_and_indirect_paths_agree(tmp_path):
    """A blocked proposal is blocked both via the bridge AND the control loop."""
    live_store = ResearchMemoryStore(tmp_path / "loop.db", bootstrap=True)
    bridge_store = ResearchMemoryStore(tmp_path / "bridge.db", bootstrap=True)

    p1 = _proposal(); p1.governance_status = "UNKNOWN"
    report = run_control_loop(instrument="EURUSD", horizon_evidence=None,
                              store=live_store, external_proposals=[p1])
    loop_blocked = any(o.phase == "BLOCKED_GOVERNANCE" for o in report.outcomes)

    from nexora_research.external_intelligence.repository import ExternalKnowledgeRepository
    repo = ExternalKnowledgeRepository(tmp_path / "ext.db", bootstrap=True)
    p2 = _proposal(); p2.governance_status = "UNKNOWN"
    res = rb.route_to_research_memory(repo, p2, research_store=bridge_store,
                                      register=True)
    bridge_blocked = (res.hypothesis_prepared is False)

    assert loop_blocked is True
    assert bridge_blocked is True
    assert live_store.list_hypotheses() == []
    assert bridge_store.list_hypotheses() == []


# ==================================================================== #
# 6. No prohibited actions; no automatic suspension change.
# ==================================================================== #
@pytest.mark.parametrize("action", ["train", "hyperparameter_tune", "promote_model",
                                    "enable_live_trading", "auto_reopen"])
def test_prohibited_actions_still_blocked(action):
    with pytest.raises(GovernanceViolation):
        assert_can(action)


def test_suspension_status_unchanged_by_gate_and_runs():
    from nexora_laboratory.governance.lane_suspension import load_registry
    before = load_registry()
    # Exercise gate + a dry loop; suspension must not change.
    canonical_governance_gate(lane=LANE_INFO, governance_status="ALLOWED",
                              rule_id="R_EXT_X")
    run_control_loop(instrument="EURUSD", horizon_evidence=None, dry_run=True,
                     external_proposals=[_proposal()])
    after = load_registry()
    assert before["status"] == after["status"] == "SUSPENDED"
    assert before["suspended_candidates"] == after["suspended_candidates"]


# ==================================================================== #
# 7. Production DB is never touched.
# ==================================================================== #
def test_production_db_untouched_by_bridge_and_loop(tmp_path):
    from nexora_research.external_intelligence.config import PRODUCTION_DB_PATH
    if not Path(PRODUCTION_DB_PATH).exists():
        pytest.skip("production DB not present in this checkout")
    before = hashlib.sha256(Path(PRODUCTION_DB_PATH).read_bytes()).hexdigest()

    store = ResearchMemoryStore(tmp_path / "research.db", bootstrap=True)
    run_control_loop(instrument="EURUSD", horizon_evidence=None, store=store,
                     external_proposals=[_proposal()])

    after = hashlib.sha256(Path(PRODUCTION_DB_PATH).read_bytes()).hexdigest()
    assert before == after
