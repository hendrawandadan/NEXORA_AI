"""Tahap E — Strategy Evolution tests.

Verifies: evidence-grounded proposals, change-basis required, dead-end awareness,
governance gating (price-derived proposals BLOCKED while lane SUSPENDED; new-info
proposals allowed), conversion to a registrable hypothesis, and optional recording.
"""

import json
import tempfile
from pathlib import Path

import pytest

from nexora_research.store import ResearchMemoryStore
from nexora_research.strategy_evolution import (
    evolve_proposals, EvolutionProposal, _governance_status,
)


@pytest.fixture
def store(tmp_path):
    return ResearchMemoryStore(tmp_path / "evo.db", bootstrap=True)


def _seed(store, inst, tf, h, ftype):
    hid = store.register_hypothesis(hypothesis_key=f"{inst}:{tf}:h{h}",
                                    instrument=inst, timeframe=tf, horizon_bars=h,
                                    claim="seed")
    eid = store.create_experiment(experiment_key=f"{inst}:{tf}:h{h}",
                                  hypothesis_id=hid["id"], spec={})
    store.record_failure(experiment_id=eid["id"], failure_type=ftype, recommendation="rec",
                         evidence={"signature": f"{inst}|{tf}|{h}",
                                   "hypothesis_spec": {"instrument": inst,
                                                       "timeframe": tf, "horizon_bars": h}})


# ---------- proposal generation ----------
def test_overfit_generates_horizon_shift(store):
    _seed(store, "XAUUSD", "D1", 2, "OVERFIT")
    props = evolve_proposals(store)
    shifts = [p for p in props if p.rule_id == "R_EVOLVE_HORIZON_SHIFT"]
    assert len(shifts) == 1
    assert shifts[0].horizon_bars == 4  # 2x the failed horizon
    assert shifts[0].signature != "XAUUSD|D1|2"  # different from failed


def test_edge_below_cost_generates_shift(store):
    _seed(store, "EURUSD", "H4", 12, "EDGE_BELOW_COST")
    props = evolve_proposals(store)
    assert any(p.rule_id == "R_EVOLVE_HORIZON_SHIFT" and p.instrument == "EURUSD"
               for p in props)


def test_no_predictive_power_generates_new_info(store):
    _seed(store, "GBPUSDm", "H1", 24, "NO_PREDICTIVE_POWER")
    props = evolve_proposals(store)
    newinfo = [p for p in props if p.rule_id == "R_EVOLVE_NEW_INFO_SOURCE"]
    assert len(newinfo) == 1
    assert newinfo[0].instrument == "GBPUSDm"
    assert newinfo[0].lane == "INFO_ACQUISITION"


# ---------- every proposal has a change basis (governance) ----------
def test_all_proposals_have_change_basis(store):
    _seed(store, "XAUUSD", "D1", 2, "OVERFIT")
    _seed(store, "GBPUSDm", "H1", 24, "NO_PREDICTIVE_POWER")
    for p in evolve_proposals(store):
        assert p.change_basis.strip(), f"{p.rule_id} missing change_basis"


# ---------- governance gating ----------
def test_price_derived_proposals_blocked_while_suspended(store):
    # Lane is SUSPENDED (GOV-PRD-001). Price-derived horizon shifts must be BLOCKED.
    _seed(store, "EURUSD", "H4", 12, "EDGE_BELOW_COST")
    props = [p for p in evolve_proposals(store) if p.rule_id == "R_EVOLVE_HORIZON_SHIFT"]
    assert props, "expected a horizon-shift proposal"
    for p in props:
        assert p.governance_status == "BLOCKED_GOVERNANCE"
        assert p.allowed is False


def test_suspended_candidate_specifically_named(store):
    # XAUUSD D1 h1 fails -> horizon shift proposes h2, which IS a suspended candidate
    # (XAUUSD D1 h2). The governance reason must name the candidate specifically.
    _seed(store, "XAUUSD", "D1", 1, "OVERFIT")
    props = [p for p in evolve_proposals(store) if p.horizon_bars == 2]
    assert props
    assert any("suspended candidate" in p.governance_reason for p in props)


def test_new_info_source_allowed(store):
    _seed(store, "GBPUSDm", "H1", 24, "NO_PREDICTIVE_POWER")
    newinfo = [p for p in evolve_proposals(store) if p.rule_id == "R_EVOLVE_NEW_INFO_SOURCE"]
    assert newinfo[0].governance_status == "ALLOWED"
    assert newinfo[0].allowed is True


# ---------- conversion + registration ----------
def test_allowed_proposal_converts_to_hypothesis(store):
    _seed(store, "GBPUSDm", "H1", 24, "NO_PREDICTIVE_POWER")
    p = [p for p in evolve_proposals(store) if p.allowed][0]
    h = p.to_hypothesis()
    assert h.rule_id == p.rule_id
    assert h.instrument == p.instrument
    assert "change_basis" in h.evidence


def test_blocked_proposal_still_converts_but_is_not_allowed(store):
    _seed(store, "EURUSD", "H4", 12, "EDGE_BELOW_COST")
    p = [p for p in evolve_proposals(store) if not p.allowed][0]
    # conversion is structural; caller must check .allowed before pre-registering.
    assert p.allowed is False
    assert p.to_hypothesis().instrument == p.instrument


# ---------- recording (STRATEGY_LEAD, append-only) ----------
def test_record_proposals_writes_strategy_leads(store):
    _seed(store, "GBPUSDm", "H1", 24, "NO_PREDICTIVE_POWER")
    from nexora_research.knowledge_query import list_knowledge
    before = list_knowledge(store, kind="STRATEGY_LEAD")
    evolve_proposals(store, record_proposals=True)
    after = list_knowledge(store, kind="STRATEGY_LEAD")
    assert len(after) > len(before)


def test_recording_is_append_only_versions(store):
    _seed(store, "GBPUSDm", "H1", 24, "NO_PREDICTIVE_POWER")
    evolve_proposals(store, record_proposals=True)
    evolve_proposals(store, record_proposals=True)  # run again
    # same proposal keys -> versioned entries, not overwritten
    row = store.knowledge_versions("proposal:evo:GBPUSDm:new_info_source")
    assert len(row) >= 2  # two runs -> two versions


# ---------- determinism ----------
def test_deterministic_ordering(store):
    _seed(store, "XAUUSD", "D1", 2, "OVERFIT")
    _seed(store, "GBPUSDm", "H1", 24, "NO_PREDICTIVE_POWER")
    a = [p.proposal_key for p in evolve_proposals(store)]
    b = [p.proposal_key for p in evolve_proposals(store)]
    assert a == b


# ---------- no evidence -> no proposals ----------
def test_empty_store_no_proposals(store):
    assert evolve_proposals(store) == []


# ---------- serialization ----------
def test_proposal_as_dict_complete(store):
    _seed(store, "GBPUSDm", "H1", 24, "NO_PREDICTIVE_POWER")
    p = evolve_proposals(store)[0]
    d = p.as_dict()
    assert {"proposal_key", "rule_id", "instrument", "change_basis",
            "governance_status", "allowed"} <= set(d)
