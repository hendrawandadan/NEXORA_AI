"""R2 — POINT-IN-TIME (PIT) safety (external intelligence).

Verifies the P2-B remediation:
  * migration 003 adds PIT columns additively and preserves existing rows,
  * producers record availability/vintage ONLY when the source provides them
    (name: never fabricate) and set pit_verified accordingly,
  * event response uses availability (not period scheduled_ts) as the anti-leakage
    basis when the release is later than the scheduled timestamp,
  * the PIT gate (assess_pit_safety) labels a lead non-confirmatory when data is
    unverified/synthetic, and confirmatory-ready when it is PIT-safe,
  * the bridge surfaces pit_ready and never raises/over-blocks provenance.

Isolated temp DBs only; no production writes.
"""

import shutil
import sqlite3
import tempfile
from pathlib import Path

import pytest

from nexora_research.external_intelligence import event_response as er
from nexora_research.external_intelligence import research_bridge as rb
from nexora_research.external_intelligence.repository import ExternalKnowledgeRepository
from nexora_research.external_intelligence.new_information import ResearchProposal, LANE_INFO
from nexora_research.external_intelligence.config import (
    EXTERNAL_INTEL_MIGRATIONS_DIR,
)
from nexora_state_db.connection import SQLiteConnectionManager
from nexora_state_db.migrations import MigrationManager


@pytest.fixture()
def repo(tmp_path):
    return ExternalKnowledgeRepository(tmp_path / "ext.db", bootstrap=True)


def _event_kwargs(**over):
    base = dict(event_type="CPI", country="US", currency="USD",
                scheduled_ts="2026-01-15T13:30:00Z", source_provider="mock",
                retrieved_at_utc="2026-01-15T13:31:00Z", actual=3.4, forecast=3.2,
                period="2026-01")
    base.update(over)
    return base


# ------------------------------ migration upgrade ------------------------------
def test_migration_003_is_additive_and_preserves_rows(tmp_path):
    db = tmp_path / "v2.db"
    mgr = SQLiteConnectionManager(db_path=db)
    # Apply only {...001,002} then insert a v2-era event, then apply full set (003).
    v2dir = tmp_path / "mig_v2"
    v2dir.mkdir()
    src = Path(EXTERNAL_INTEL_MIGRATIONS_DIR)
    shutil.copy(src / "001__external_intel_schema.sql", v2dir)
    shutil.copy(src / "002__external_lane_guard.sql", v2dir)
    MigrationManager(mgr, v2dir).migrate()
    with mgr.open() as conn:
        conn.execute(
            """INSERT INTO ext_economic_events
               (event_key,event_type,country,currency,scheduled_ts,source_provider,
                retrieved_at_utc,content_sha256)
               VALUES('k','CPI','US','USD','2026-01-15T13:30:00Z','mock',
                      '2026-01-15T13:31:00Z','h')""")
        conn.commit()
    MigrationManager(mgr, src).migrate()  # adds 003
    with mgr.open() as conn:
        cols = [r[1] for r in conn.execute("PRAGMA table_info(ext_economic_events)")]
        row = conn.execute("SELECT event_key, ingested_at_utc, pit_verified "
                           "FROM ext_economic_events WHERE event_key='k'").fetchone()
    for c in ("published_at_utc", "available_at_utc", "ingested_at_utc", "vintage",
              "revision_as_of_utc", "pit_verified"):
        assert c in cols
    # lossless ingestion backfill; unverified by default (no source availability).
    assert row["ingested_at_utc"] == "2026-01-15T13:31:00Z"
    assert row["pit_verified"] == 0


# ------------------------------ producers: never fabricate ------------------------------
def test_event_without_availability_is_unverified(repo):
    r = repo.insert_economic_event(**_event_kwargs())
    row = repo.get_event(r["id"])
    assert row["available_at_utc"] is None
    assert row["pit_verified"] == 0
    assert row["ingested_at_utc"] == "2026-01-15T13:31:00Z"


def test_event_with_source_availability_is_verified(repo):
    r = repo.insert_economic_event(**_event_kwargs(
        available_at_utc="2026-01-15T13:30:05Z",
        published_at_utc="2026-01-15T13:30:00Z", vintage="v1",
        revision_as_of_utc="2026-01-15T13:30:00Z"))
    row = repo.get_event(r["id"])
    assert row["available_at_utc"] == "2026-01-15T13:30:05Z"
    assert row["pit_verified"] == 1
    assert row["vintage"] == "v1"


def test_event_invalid_availability_rejected(repo):
    with pytest.raises(ValueError):
        repo.insert_economic_event(**_event_kwargs(available_at_utc="not-a-date"))


def test_news_and_cb_record_availability_and_first_observed(repo):
    n = repo.insert_news(headline="CPI beats", category="ECONOMIC",
                         published_ts="2026-01-15T13:30:00Z", source_provider="mock",
                         retrieved_at_utc="2026-01-15T13:31:00Z",
                         currencies=["USD"], available_at_utc="2026-01-15T13:30:05Z")
    assert n["pit_verified"] == 1
    cn = repo.insert_central_bank_doc(institution="FED", doc_type="STATEMENT", title="t",
                                      published_ts="2026-01-15T18:00:00Z",
                                      source_provider="mock", source_ref="u",
                                      body_text="text", retrieved_at_utc="2026-01-15T18:01:00Z")
    assert cn["pit_verified"] == 0  # no availability supplied -> unverified


# ------------------------------ event-response PIT basis ------------------------------
def _bars():
    # pre at 13:00, then bars at 13:30 and after; a "period" scheduled at 13:30 is fine.
    return [
        {"ts": "2026-01-15T13:00:00Z", "close": 100.0},
        {"ts": "2026-01-15T13:30:00Z", "close": 110.0},
        {"ts": "2026-01-15T13:35:00Z", "close": 121.0},
        {"ts": "2026-01-15T13:40:00Z", "close": 130.0},
    ]


def test_response_uses_event_ts_when_no_availability():
    r = er.measure_event_response(event_id=1, event_ts="2026-01-15T13:30:00Z",
                                  instrument="EURUSD", bars=_bars(),
                                  horizons=(("5m", 5),))
    # pre = last close strictly before 13:30 = 100; post at >=13:35 = 121
    h = r.responses[0]
    assert h.pre_price == 100.0 and h.post_price == 121.0
    assert r.event_available_at is None


def test_response_shifts_basis_to_later_availability():
    # Release only becomes knowable at 13:34 -> pre must be 110 (close before 13:34),
    # NOT 100 -- otherwise a report released at 13:30 would leak the 13:30 close.
    # With basis 13:34, the 5m target is 13:39 -> first bar at/after it is the 13:40 bar.
    r = er.measure_event_response(event_id=1, event_ts="2026-01-15T13:30:00Z",
                                  instrument="EURUSD", bars=_bars(),
                                  horizons=(("5m", 5),),
                                  available_at="2026-01-15T13:34:00Z")
    h = r.responses[0]
    assert r.basis_ts.startswith("2026-01-15T13:34")
    assert h.pre_price == 110.0   # basis-aware pre price (no look-ahead)
    assert h.post_price == 130.0  # 13:40 bar >= 13:39 target


# ------------------------------ PIT gate assessment ------------------------------
def test_assess_pit_safety_unverified_is_not_confirmatory():
    res = rb.assess_pit_safety({"event_response": {"pit_verified": 0,
                                                   "data_quality": "UNVERIFIED"}})
    assert res["pit_safe"] is False
    assert res["confirmatory_ready"] is False
    assert res["reasons"]


def test_assess_pit_safety_synthetic_is_not_confirmatory():
    res = rb.assess_pit_safety({"x": {"pit_verified": 1, "is_synthetic": True}})
    assert res["pit_safe"] is False


def test_assess_pit_safety_clean_is_confirmatory():
    res = rb.assess_pit_safety({"event_response": {"pit_verified": 1,
                                                   "data_quality": "VERIFIED",
                                                   "is_synthetic": False}})
    assert res["pit_safe"] is True
    assert res["confirmatory_ready"] is True


def test_assess_pit_safety_no_metadata_is_fail_closed():
    res = rb.assess_pit_safety({"unrelated": 123})
    assert res["pit_safe"] is False


# ------------------------------ bridge surfaces pit_ready ------------------------------
def _proposal(evidence):
    return ResearchProposal(
        proposal_key="ni:EURUSD:EVENT_RESPONSE:x", instrument="EURUSD",
        kind="EVENT_RESPONSE", claim="c", new_information="n", why_different="w",
        market_relevance="m", data_requirements=["d"], falsification_criteria="f",
        governance_status="ALLOWED", evidence=evidence)


def test_bridge_pit_ready_false_for_unverified(repo):
    p = _proposal({"event_response": {"pit_verified": 0, "data_quality": "UNVERIFIED"}})
    res = rb.route_to_research_memory(repo, p, register=False)
    assert res.pit_ready is False
    assert res.persisted is True  # provenance still recorded; not a governance blocker


def test_bridge_pit_ready_true_for_verified(repo):
    p = _proposal({"event_response": {"pit_verified": 1, "data_quality": "VERIFIED",
                                      "is_synthetic": False}})
    res = rb.route_to_research_memory(repo, p, register=False)
    assert res.pit_ready is True
