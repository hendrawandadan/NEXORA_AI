"""Tahap D — Autonomous Research Control Loop tests.

Verifies: state machine transitions, feasibility + governance gates, dry-run does not
persist, governance blocks suspended candidates end-to-end, and the max verdict never
exceeds READY_FOR_CONFIRMATORY_EXPERIMENT (no live/train side-effects).
"""

import json
from pathlib import Path

import pytest

from nexora_research.control_loop import (
    run_control_loop, assert_loop_is_allowed, Phase, LoopReport, HypothesisOutcome,
)
from nexora_research.store import ResearchMemoryStore

REPO = Path(__file__).resolve().parents[1]
HORIZON = json.load(open(REPO / "reports/economic_opportunity_discovery/horizon_discovery.json",
                         encoding="utf-8"))
INSTR = json.load(open(REPO / "reports/economic_opportunity_discovery/instrument_discovery.json",
                       encoding="utf-8"))


# ---------- preflight governance ----------
def test_loop_preflight_blocks_prohibited():
    # All prohibited actions must be blocked while lane SUSPENDED.
    assert assert_loop_is_allowed() is True


# ---------- state machine: EURUSD (mixed) ----------
def test_eurusd_dry_run_visits_phases():
    rep = run_control_loop(instrument="EURUSD", horizon_evidence=HORIZON, dry_run=True)
    assert Phase.OBSERVE.value in rep.phases_visited
    assert Phase.HYPOTHESIZE.value in rep.phases_visited
    assert Phase.EXPERIMENT_SPEC.value in rep.phases_visited
    assert len(rep.outcomes) > 0


def test_eurusd_blocks_suspended_h4_h12_only():
    rep = run_control_loop(instrument="EURUSD", horizon_evidence=HORIZON, dry_run=True)
    blocked = [o for o in rep.outcomes if o.phase == Phase.BLOCKED_GOVERNANCE.value]
    # Exactly the EURUSD H4 h12 candidate is suspended.
    assert len(blocked) == 1
    assert blocked[0].horizon == 12
    # Others proceed to a research decision (not blocked).
    ready = [o for o in rep.outcomes if o.phase == Phase.READY_FOR_CONFIRMATORY_EXPERIMENT.value]
    assert len(ready) >= 5


# ---------- governance blocks XAUUSD D1/H4 entirely ----------
def test_xauusd_all_suspended_candidates_blocked():
    xau = INSTR["instruments"]["XAUUSD"]
    rep = run_control_loop(instrument="XAUUSD", horizon_evidence=xau, dry_run=True)
    assert rep.max_verdict == "BLOCKED_GOVERNANCE"
    for o in rep.outcomes:
        # XAUUSD generator emits D1 h2 and H4 h12, both suspended.
        assert o.phase == Phase.BLOCKED_GOVERNANCE.value


# ---------- max verdict ceiling ----------
def test_max_verdict_never_exceeds_ready():
    rep = run_control_loop(instrument="EURUSD", horizon_evidence=HORIZON, dry_run=True)
    assert rep.max_verdict in (
        "READY_FOR_CONFIRMATORY_EXPERIMENT", "BLOCKED_GOVERNANCE",
        "FAILURE_LEARNING", "SKIPPED_INFEASIBLE", "NO_OUTCOME")
    # absolutely never a live/profit verdict
    assert rep.max_verdict not in ("GO", "LIVE", "PROMOTED", "PROFIT")


def test_ready_verdict_carries_no_profit_claim():
    rep = run_control_loop(instrument="EURUSD", horizon_evidence=HORIZON, dry_run=True)
    for o in rep.outcomes:
        if o.phase == Phase.READY_FOR_CONFIRMATORY_EXPERIMENT.value:
            assert "profit claim" in o.reason.lower() or "no evaluation" in o.reason.lower()


# ---------- dry-run does not persist to disk ----------
def test_dry_run_does_not_touch_research_db():
    # Point the real research DB path; a dry run must not create rows there.
    from nexora_research.config import RESEARCH_DATABASE_PATH
    db = Path(RESEARCH_DATABASE_PATH)
    before = db.stat().st_size if db.exists() else None
    run_control_loop(instrument="EURUSD", horizon_evidence=HORIZON, dry_run=True)
    after = db.stat().st_size if db.exists() else None
    assert before == after  # size unchanged (nothing persisted by dry-run)


# ---------- empty evidence handled ----------
def test_empty_evidence_no_hypotheses():
    rep = run_control_loop(instrument="EURUSD", horizon_evidence={}, dry_run=True)
    assert rep.outcomes == []
    assert rep.max_verdict == "NO_OUTCOME"
    assert any("no horizon evidence" in n.lower() for n in rep.notes)


# ---------- report serialization ----------
def test_report_as_dict_structure():
    rep = run_control_loop(instrument="EURUSD", horizon_evidence=HORIZON, dry_run=True)
    d = rep.as_dict()
    assert set(d) == {"instrument", "phases_visited", "max_verdict", "outcomes", "notes"}
    for o in d["outcomes"]:
        assert {"rule_id", "phase", "reason", "horizon"} <= set(o)


def test_outcome_as_dict_keys():
    o = HypothesisOutcome(hypothesis_id=1, instrument="EURUSD", horizon=12,
                          rule_id="R_HORIZON_FEASIBLE", phase="X", reason="r")
    d = o.as_dict()
    assert d["hypothesis_id"] == 1 and d["rule_id"] == "R_HORIZON_FEASIBLE"


# ---------- non-dry-run persistence (temp store) ----------
def test_non_dry_run_persists_to_store(tmp_path):
    store = ResearchMemoryStore(tmp_path / "t.db", bootstrap=True)
    rep = run_control_loop(instrument="EURUSD", horizon_evidence=HORIZON,
                           store=store, dry_run=False)
    assert Phase.KNOWLEDGE_MEMORY.value in rep.phases_visited
    # at least some hypotheses were registered/persisted
    hyps = store.list_hypotheses()
    assert len(hyps) >= 1


# ---------- governance candidate guard called with real timeframe ----------
def test_governance_gate_uses_hypothesis_timeframe():
    # XAUUSD hypotheses carry timeframe D1/H4; both suspended -> all blocked.
    xau = INSTR["instruments"]["XAUUSD"]
    rep = run_control_loop(instrument="XAUUSD", horizon_evidence=xau, dry_run=True)
    reasons = " ".join(o.reason for o in rep.outcomes)
    assert "SUSPENDED" in reasons
