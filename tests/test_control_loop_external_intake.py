"""P0 wiring test: external-intelligence proposals flow through the control loop.

Verifies that external INFO_ACQUISITION proposals enter OBSERVE -> HYPOTHESIZE ->
EXPERIMENT_SPEC -> gates -> DECIDE, that governance stays correct (info lane allowed
while price-derived lane suspended), that dead-ends are skipped, that dry_run persists
nothing, and that price-derived behavior is unchanged.
"""

import pytest

from nexora_research.control_loop import (
    run_control_loop, INFO_ACQUISITION_LANE, LoopReport,
)
from nexora_research.external_intelligence import new_information as nii
from nexora_research.store import ResearchMemoryStore
from nexora_laboratory.governance.lane_suspension import GovernanceViolation


def _event_response():
    return {
        "event_id": 1, "instrument": "EURUSD", "event_ts": "2026-01-15T13:30:00Z",
        "event_type": "CPI", "surprise": 0.3,
        "responses": [
            {"horizon": "15m", "horizon_minutes": 15, "valid": True, "direction": "DOWN"},
            {"horizon": "1h", "horizon_minutes": 60, "valid": True, "direction": "DOWN"},
        ],
    }


def _proposals():
    return nii.discover_new_information(instrument="EURUSD",
                                        event_responses=[_event_response()])


# ---------------------------------------------------------------- #
# Basic intake
# ---------------------------------------------------------------- #
def test_external_proposal_reaches_ready_for_confirmatory(tmp_path):
    store = ResearchMemoryStore(tmp_path / "research.db", bootstrap=True)
    props = _proposals()
    assert props, "fixture should yield >=1 proposal"
    report = run_control_loop(instrument="EURUSD", horizon_evidence=None,
                              store=store, external_proposals=props)
    assert any(o.lane == INFO_ACQUISITION_LANE for o in report.outcomes)
    ext = [o for o in report.outcomes if o.lane == INFO_ACQUISITION_LANE]
    assert ext
    o = ext[0]
    # Feasible + info lane allowed => READY_FOR_CONFIRMATORY_EXPERIMENT (never GO/PROFIT).
    assert o.phase == "READY_FOR_CONFIRMATORY_EXPERIMENT"
    assert o.verdict == "READY_FOR_CONFIRMATORY_EXPERIMENT"
    assert report.max_verdict == "READY_FOR_CONFIRMATORY_EXPERIMENT"


def test_external_proposal_registered_when_not_dry(tmp_path):
    store = ResearchMemoryStore(tmp_path / "research.db", bootstrap=True)
    report = run_control_loop(instrument="EURUSD", horizon_evidence=None,
                              store=store, external_proposals=_proposals())
    ext = [o for o in report.outcomes if o.lane == INFO_ACQUISITION_LANE][0]
    assert ext.hypothesis_id is not None
    assert ext.experiment_id is not None
    # The hypothesis is pre-registered (not evaluated / not trained).
    assert len(store.list_hypotheses(status="PRE_REGISTERED")) >= 1


def test_external_dry_run_persists_nothing(tmp_path):
    store = ResearchMemoryStore(tmp_path / "research.db", bootstrap=True)
    before = len(store.list_hypotheses())
    report = run_control_loop(instrument="EURUSD", horizon_evidence=None,
                              store=store, dry_run=True, external_proposals=_proposals())
    assert len(store.list_hypotheses()) == before  # nothing written
    assert any(o.lane == INFO_ACQUISITION_LANE for o in report.outcomes)


# ---------------------------------------------------------------- #
# Governance
# ---------------------------------------------------------------- #
def test_info_lane_allowed_while_price_lane_suspended():
    # Even though price-derived lane is SUSPENDED, info-acquisition passes the gate.
    from nexora_laboratory.governance.lane_suspension import is_suspended
    assert is_suspended() is True  # precondition
    report = run_control_loop(instrument="EURUSD", horizon_evidence=None, dry_run=True,
                              external_proposals=_proposals())
    ext = [o for o in report.outcomes if o.lane == INFO_ACQUISITION_LANE]
    assert ext and all(o.phase != "BLOCKED_GOVERNANCE" for o in ext)


def test_price_derived_candidate_still_blocked(tmp_path):
    # A price-derived hypothesis on a suspended candidate must still be BLOCKED,
    # even when external proposals are also supplied (lane isolation).
    store = ResearchMemoryStore(tmp_path / "research.db", bootstrap=True)
    horizon_evidence = {
        "timeframe": "H4",
        "economics": [{"scenario": "baseline", "horizon_bars": 12,
                       "move_to_cost_ratio": 8.0, "required_acc_symmetric": 0.55,
                       "median_move_pips": 40.0}],
    }
    # EURUSD H4 h12 is a suspended candidate per governance registry.
    report = run_control_loop(instrument="EURUSD", horizon_evidence=horizon_evidence,
                              timeframe="H4", store=store,
                              external_proposals=_proposals())
    price_outcomes = [o for o in report.outcomes if o.lane != INFO_ACQUISITION_LANE]
    assert any(o.phase == "BLOCKED_GOVERNANCE" for o in price_outcomes), \
        "price-derived suspended candidate must be blocked"
    # External lane still gets through.
    assert any(o.lane == INFO_ACQUISITION_LANE for o in report.outcomes)


def test_blocked_proposal_does_not_register(tmp_path):
    store = ResearchMemoryStore(tmp_path / "research.db", bootstrap=True)
    props = _proposals()
    props[0].governance_status = "BLOCKED_GOVERNANCE"
    before = len(store.list_hypotheses())
    report = run_control_loop(instrument="EURUSD", horizon_evidence=None,
                              store=store, external_proposals=props)
    ext = [o for o in report.outcomes if o.lane == INFO_ACQUISITION_LANE]
    assert ext and ext[0].phase == "BLOCKED_GOVERNANCE"
    assert len(store.list_hypotheses()) == before


# ---------------------------------------------------------------- #
# Dead-end avoidance + input robustness
# ---------------------------------------------------------------- #
def test_dead_end_signature_skipped(tmp_path):
    store = ResearchMemoryStore(tmp_path / "research.db", bootstrap=True)
    props = _proposals()
    # Simulate a recorded dead-end with the same external signature.
    from nexora_research.control_loop import _proposal_to_hypothesis
    hyp = _proposal_to_hypothesis(props[0])
    store.record_knowledge(knowledge_key="de:ext", kind="DEAD_END", summary="prior fail",
                           detail={"signature": hyp.signature})
    report = run_control_loop(instrument="EURUSD", horizon_evidence=None,
                              store=store, external_proposals=[props[0]])
    ext = [o for o in report.outcomes if o.lane == INFO_ACQUISITION_LANE]
    assert ext and ext[0].phase == "FAILURE_LEARNING"  # skipped as dead-end


def test_non_proposal_input_ignored_gracefully(tmp_path):
    store = ResearchMemoryStore(tmp_path / "research.db", bootstrap=True)
    report = run_control_loop(instrument="EURUSD", horizon_evidence=None, store=store,
                              external_proposals=[object(), "junk", 123])
    assert any("ignoring non-proposal" in n for n in report.notes)
    # No external outcomes because nothing valid was supplied.
    assert not [o for o in report.outcomes if o.lane == INFO_ACQUISITION_LANE]


def test_only_external_no_horizon_evidence_ok(tmp_path):
    store = ResearchMemoryStore(tmp_path / "research.db", bootstrap=True)
    report = run_control_loop(instrument="EURUSD", horizon_evidence=None, store=store,
                              external_proposals=_proposals())
    assert any("external proposals only" in n for n in report.notes)
    assert report.outcomes  # still produced outcomes


def test_no_evidence_no_proposals_returns_observing():
    report = run_control_loop(instrument="EURUSD", horizon_evidence=None, dry_run=True)
    assert report.outcomes == []
    assert any("cannot hypothesize" in n for n in report.notes)


# ---------------------------------------------------------------- #
# Price-derived behavior unchanged
# ---------------------------------------------------------------- #
def test_price_derived_loop_unchanged_without_external(tmp_path):
    store = ResearchMemoryStore(tmp_path / "research.db", bootstrap=True)
    horizon_evidence = {
        "timeframe": "M30",
        "economics": [{"scenario": "baseline", "horizon_bars": 8,
                       "move_to_cost_ratio": 8.0, "required_acc_symmetric": 0.55,
                       "median_move_pips": 20.0}],
    }
    report = run_control_loop(instrument="XAUUSD", horizon_evidence=horizon_evidence,
                              timeframe="M30", store=store)
    # No external lane outcomes when none supplied.
    assert not [o for o in report.outcomes if o.lane == INFO_ACQUISITION_LANE]
    assert report.outcomes  # price-derived path still runs
