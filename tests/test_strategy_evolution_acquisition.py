"""Roadmap item 2.4 — execute R_EVOLVE_NEW_INFO_SOURCE via real acquisition.

Verifies the trigger->acquisition->control-loop wiring:
  * Only R_EVOLVE_NEW_INFO_SOURCE proposals on the INFO_ACQUISITION lane, ALLOWED, run.
  * Other rules / blocked proposals / wrong lanes are refused (fail-closed).
  * The orchestrator is actually invoked; its discovered proposals are routed into the
    research control loop (INFO_ACQUISITION lane outcomes).
  * dry_run persists nothing; never trains/promotes/trades/reopens.
  * Honest result: even executed, no profit/edge claim (max verdict is a research lead).
"""

import pytest

from nexora_research.store import ResearchMemoryStore
from nexora_research import strategy_evolution as se


@pytest.fixture
def store(tmp_path):
    return ResearchMemoryStore(tmp_path / "evo.db", bootstrap=True)


def _seed_no_pred(store, inst="EURUSD", tf="H4", h=12):
    hid = store.register_hypothesis(hypothesis_key=f"{inst}:{tf}:h{h}",
                                    instrument=inst, timeframe=tf, horizon_bars=h,
                                    claim="seed")
    eid = store.create_experiment(experiment_key=f"{inst}:{tf}:h{h}",
                                  hypothesis_id=hid["id"], spec={})
    store.record_failure(experiment_id=eid["id"], failure_type="NO_PREDICTIVE_POWER",
                         recommendation="rec",
                         evidence={"signature": f"{inst}|{tf}|{h}",
                                   "hypothesis_spec": {"instrument": inst,
                                                       "timeframe": tf,
                                                       "horizon_bars": h}})


def _new_info_proposal(store):
    props = [p for p in se.evolve_proposals(store)
             if p.rule_id == "R_EVOLVE_NEW_INFO_SOURCE"]
    assert props, "expected an R_EVOLVE_NEW_INFO_SOURCE proposal"
    return props[0]


def _news():
    return [{"headline": "US imposes new tariffs in escalating trade war",
             "published_ts": "2026-01-15T13:00:00Z", "source_provider": "mock",
             "retrieved_at_utc": "2026-01-15T13:05:00Z"}]


def _events():
    return [{"event_type": "CPI", "country": "US", "currency": "USD",
             "scheduled_ts": "2026-01-15T13:30:00Z", "actual": 3.4, "forecast": 3.1,
             "previous": 3.2, "source_provider": "mock",
             "retrieved_at_utc": "2026-01-15T13:35:00Z"}]


def _bars():
    from datetime import datetime, timedelta, timezone
    t0 = datetime(2026, 1, 15, 13, 20, tzinfo=timezone.utc)
    return [{"ts": (t0 + timedelta(minutes=i)).isoformat(), "close": 100 + 0.1 * i}
            for i in range(120)]


# ---------- happy path: trigger -> acquisition -> loop ----------
def test_executes_allowed_new_info_proposal(store):
    _seed_no_pred(store)
    prop = _new_info_proposal(store)
    res = se.execute_new_info_acquisition(store, prop, news=_news(), dry_run=True)
    assert res.executed is True
    assert res.refused_reason == ""
    assert res.intel_report is not None
    # Orchestrator was actually invoked (it reports provider/connector status).
    assert "connectors" in res.intel_report


def test_acquisition_routes_proposals_and_reports_outcomes(store):
    _seed_no_pred(store)
    prop = _new_info_proposal(store)
    # Events + price_bars deterministically yield an EVENT_RESPONSE proposal, which the
    # acquisition must route into the control loop.
    res = se.execute_new_info_acquisition(store, prop, events=_events(),
                                          price_bars=_bars(), dry_run=False,
                                          external_repo=_tmp_repo(store))
    assert res.executed is True
    assert res.external_proposals > 0, "fixture must yield >=1 external proposal"
    assert res.loop_outcomes, "external proposals must be routed into the loop"
    for o in res.loop_outcomes:
        assert o["lane"] == "INFO_ACQUISITION"
        assert o["phase"] != "BLOCKED_GOVERNANCE"  # info lane allowed while PRD suspended
    # Absolutely never a profit/live verdict.
    assert res.loop_max_verdict not in ("GO", "LIVE", "PROMOTED", "PROFIT")


# ---------- fail-closed refusals ----------
def test_refuses_wrong_rule(store):
    _seed_no_pred(store)
    store.record_failure  # noqa (helper import check)
    # A horizon-shift proposal must be refused.
    _seed_shift(store)
    shifts = [p for p in se.evolve_proposals(store)
              if p.rule_id == "R_EVOLVE_HORIZON_SHIFT"]
    assert shifts
    res = se.execute_new_info_acquisition(store, shifts[0], dry_run=True)
    assert res.executed is False
    assert "R_EVOLVE_NEW_INFO_SOURCE" in res.refused_reason


def _seed_shift(store, inst="XAUUSD", tf="D1", h=2):
    hid = store.register_hypothesis(hypothesis_key=f"{inst}:{tf}:h{h}",
                                    instrument=inst, timeframe=tf, horizon_bars=h,
                                    claim="seed")
    eid = store.create_experiment(experiment_key=f"{inst}:{tf}:h{h}",
                                  hypothesis_id=hid["id"], spec={})
    store.record_failure(experiment_id=eid["id"], failure_type="OVERFIT",
                         recommendation="rec",
                         evidence={"signature": f"{inst}|{tf}|{h}",
                                   "hypothesis_spec": {"instrument": inst,
                                                       "timeframe": tf, "horizon_bars": h}})


def test_refuses_blocked_proposal(store):
    _seed_no_pred(store)
    prop = _new_info_proposal(store)
    # Force a blocked status to simulate governance refusal.
    prop.governance_status = "BLOCKED_GOVERNANCE"
    prop.governance_reason = "simulated"
    res = se.execute_new_info_acquisition(store, prop, dry_run=True)
    assert res.executed is False
    assert "not governance-allowed" in res.refused_reason


def test_refuses_wrong_lane(store):
    _seed_no_pred(store)
    prop = _new_info_proposal(store)
    prop.lane = "PRICE_DERIVED"
    res = se.execute_new_info_acquisition(store, prop, dry_run=True)
    assert res.executed is False
    assert "lane" in res.refused_reason.lower()


# ---------- dry-run persists nothing ----------
def test_dry_run_persists_nothing(store):
    _seed_no_pred(store)
    prop = _new_info_proposal(store)
    before = len(store.list_hypotheses())
    res = se.execute_new_info_acquisition(store, prop, news=_news(), dry_run=True)
    assert res.executed is True
    assert len(store.list_hypotheses()) == before  # nothing written


# ---------- serialization ----------
def test_result_as_dict(store):
    _seed_no_pred(store)
    prop = _new_info_proposal(store)
    res = se.execute_new_info_acquisition(store, prop, dry_run=True)
    d = res.as_dict()
    assert {"proposal_key", "instrument", "executed", "intel_report",
            "external_proposals", "loop_max_verdict", "loop_outcomes"} <= set(d)


# ---------- recording a link (STRATEGY_LEAD) ----------
def test_record_writes_acquisition_knowledge(store):
    from nexora_research.knowledge_query import list_knowledge
    _seed_no_pred(store)
    prop = _new_info_proposal(store)
    before = len(list_knowledge(store, kind="STRATEGY_LEAD"))
    se.execute_new_info_acquisition(store, prop, news=_news(), dry_run=True, record=True)
    after = list_knowledge(store, kind="STRATEGY_LEAD")
    assert len(after) > before


def _tmp_repo(store):
    """Isolated external repo for non-dry tests (temp dir)."""
    import tempfile
    from pathlib import Path
    from nexora_research.external_intelligence.repository import ExternalKnowledgeRepository
    d = Path(tempfile.mkdtemp(prefix="nexora_ext_"))
    return ExternalKnowledgeRepository(d / "ext.db")
