"""R3 — AS-OF RECONSTRUCTION & PIT RE-AUDIT.

Proves that historical NEXORA external data can be reconstructed using ONLY
information genuinely knowable at a decision cutoff, with NO look-ahead leakage.

Covers the Tahap-3 acceptance list:
  * information after the decision cutoff is NOT accessible,
  * published-but-not-yet-available data is NOT usable,
  * a revision made AFTER the cutoff is NOT usable,
  * missing available_at stays UNVERIFIED (excluded from confirmatory view),
  * synthetic data can never be confirmatory,
  * event response uses a valid PIT basis,
  * bridge and evaluator produce a consistent PIT assessment.

Isolated temp DBs only; no production writes, no live acquisition.
"""

import pytest

from nexora_research.external_intelligence import asof
from nexora_research.external_intelligence import event_response as er
from nexora_research.external_intelligence import research_bridge as rb
from nexora_research.external_intelligence.repository import ExternalKnowledgeRepository
from nexora_research.external_intelligence.new_information import ResearchProposal


@pytest.fixture()
def repo(tmp_path):
    return ExternalKnowledgeRepository(tmp_path / "ext.db", bootstrap=True)


def _ev(repo, *, period, scheduled, available=None, published=None, actual=3.4,
        forecast=3.1, revision_as_of=None, vintage=None, synthetic=False,
        quality="UNVERIFIED"):
    return repo.insert_economic_event(
        event_type="CPI", country="US", currency="USD", scheduled_ts=scheduled,
        source_provider="mock", retrieved_at_utc="2026-01-15T13:31:00Z",
        actual=actual, forecast=forecast, period=period,
        data_quality=quality, is_synthetic=synthetic,
        published_at_utc=published, available_at_utc=available,
        revision_as_of_utc=revision_as_of, vintage=vintage)


# =============================================================== Tahap 1: reconstruction
def test_asof_excludes_information_after_cutoff(repo):
    # Available at 10:00 and 14:00; cutoff 12:00 -> only the 10:00 one is usable.
    _ev(repo, period="2026-01", scheduled="2026-01-15T09:55:00Z",
        available="2026-01-15T10:00:00Z")
    _ev(repo, period="2026-02", scheduled="2026-01-15T13:55:00Z",
        available="2026-01-15T14:00:00Z")
    view = asof.reconstruct_events_as_of(repo, cutoff_ts="2026-01-15T12:00:00Z")
    assert len(view.rows) == 1
    assert view.rows[0]["period"] == "2026-01"
    assert asof.verify_no_leakage(view) == []


def test_published_but_not_available_is_unusable(repo):
    # published 13:30 but only knowable 14:00; cutoff 13:45 -> NOT usable.
    _ev(repo, period="2026-01", scheduled="2026-01-15T13:30:00Z",
        published="2026-01-15T13:30:00Z", available="2026-01-15T14:00:00Z")
    view = asof.reconstruct_events_as_of(repo, cutoff_ts="2026-01-15T13:45:00Z")
    assert view.rows == []
    assert view.excluded_future == 1


def test_missing_available_at_stays_unverified(repo):
    _ev(repo, period="2026-01", scheduled="2026-01-15T13:30:00Z")  # no available_at
    view = asof.reconstruct_events_as_of(repo, cutoff_ts="2026-12-31T00:00:00Z")
    assert view.rows == []
    assert view.excluded_unverified == 1
    # scheduled_ts is NEVER used as availability.
    rec = repo.list_events()[0]
    assert rec["available_at_utc"] is None
    assert asof.classify_provenance(rec) == asof.UNVERIFIED


def test_synthetic_never_confirmatory(repo):
    _ev(repo, period="2026-01", scheduled="2026-01-15T13:30:00Z",
        available="2026-01-15T13:30:00Z", synthetic=True)
    view = asof.reconstruct_events_as_of(repo, cutoff_ts="2026-12-31T00:00:00Z")
    assert view.rows == []
    assert view.excluded_synthetic == 1


def test_verified_usable_only_when_all_criteria_met(repo):
    _ev(repo, period="2026-01", scheduled="2026-01-15T13:30:00Z",
        available="2026-01-15T13:30:05Z")
    view = asof.reconstruct_events_as_of(repo, cutoff_ts="2026-01-15T13:31:00Z")
    assert len(view.rows) == 1
    assert asof.classify_provenance(view.rows[0]) == asof.VERIFIED


# =============================================================== Tahap 2: vintage/revision
def test_revision_after_cutoff_is_not_usable(repo):
    # Original (avail 10:00) and a revision made at 16:00; cutoff 12:00 must see original.
    _ev(repo, period="2026-01", scheduled="2026-01-15T09:50:00Z",
        available="2026-01-15T10:00:00Z", actual=3.0, vintage="orig")
    _ev(repo, period="2026-01", scheduled="2026-01-15T09:50:00Z",
        available="2026-01-15T16:00:00Z", actual=3.9, vintage="rev1",
        revision_as_of="2026-01-15T16:00:00Z")
    view = asof.reconstruct_events_as_of(repo, cutoff_ts="2026-01-15T12:00:00Z")
    assert len(view.rows) == 1
    assert view.rows[0]["vintage"] == "orig"
    assert float(view.rows[0]["actual"]) == 3.0


def test_revision_visible_after_its_cutoff(repo):
    _ev(repo, period="2026-01", scheduled="2026-01-15T09:50:00Z",
        available="2026-01-15T10:00:00Z", actual=3.0, vintage="orig")
    _ev(repo, period="2026-01", scheduled="2026-01-15T09:50:00Z",
        available="2026-01-15T16:00:00Z", actual=3.9, vintage="rev1",
        revision_as_of="2026-01-15T16:00:00Z")
    late = asof.reconstruct_events_as_of(repo, cutoff_ts="2026-01-15T17:00:00Z")
    assert len(late.rows) == 1
    assert late.rows[0]["vintage"] == "rev1"
    assert float(late.rows[0]["actual"]) == 3.9


def test_revision_does_not_delete_prior_history(repo):
    r1 = _ev(repo, period="2026-01", scheduled="2026-01-15T09:50:00Z",
             available="2026-01-15T10:00:00Z", actual=3.0, vintage="orig")
    _ev(repo, period="2026-01", scheduled="2026-01-15T09:50:00Z",
        available="2026-01-15T16:00:00Z", actual=3.9, vintage="rev1",
        revision_as_of="2026-01-15T16:00:00Z")
    # Both rows preserved (append-only); earliest cutoff still sees the original.
    assert repo.count("ext_economic_events") == 2
    assert repo.get_event(r1["id"])["actual"] == 3.0


# =============================================================== Tahap 3: validation
def test_news_after_cutoff_excluded(repo):
    repo.insert_news(headline="early", category="ECONOMIC",
                     published_ts="2026-01-15T09:00:00Z", source_provider="mock",
                     retrieved_at_utc="2026-01-15T09:01:00Z",
                     available_at_utc="2026-01-15T09:05:00Z")
    repo.insert_news(headline="late", category="ECONOMIC",
                     published_ts="2026-01-15T15:00:00Z", source_provider="mock",
                     retrieved_at_utc="2026-01-15T15:01:00Z",
                     available_at_utc="2026-01-15T15:05:00Z")
    view = asof.reconstruct_news_as_of(repo, cutoff_ts="2026-01-15T12:00:00Z")
    assert [r["headline"] for r in view.rows] == ["early"]
    assert asof.verify_no_leakage(view) == []


def test_event_response_valid_pit_basis():
    bars = [
        {"ts": "2026-01-15T13:00:00Z", "close": 100.0},
        {"ts": "2026-01-15T13:30:00Z", "close": 110.0},
        {"ts": "2026-01-15T13:35:00Z", "close": 121.0},
    ]
    # Availability later than scheduled -> basis is availability (no look-ahead).
    r = er.measure_event_response(event_id=1, event_ts="2026-01-15T13:30:00Z",
                                  instrument="EURUSD", bars=bars,
                                  horizons=(("5m", 5),),
                                  available_at="2026-01-15T13:34:00Z")
    # target 13:39 -> no bar at/after -> invalid (not leaked from the 13:35 bar).
    assert r.basis_ts.startswith("2026-01-15T13:34")
    assert r.responses[0].valid is False


def test_bridge_and_gate_consistent_for_unverified(repo):
    p = ResearchProposal(
        proposal_key="ni:EURUSD:EVENT_RESPONSE:x", instrument="EURUSD",
        kind="EVENT_RESPONSE", claim="c", new_information="n", why_different="w",
        market_relevance="m", data_requirements=["d"], falsification_criteria="f",
        governance_status="ALLOWED",
        evidence={"event_response": {"pit_verified": 0, "data_quality": "UNVERIFIED"}})
    bridge_res = rb.route_to_research_memory(repo, p, register=False)
    gate = rb.assess_pit_safety(p.evidence)
    assert bridge_res.pit_ready == gate["confirmatory_ready"] == False  # noqa: E712
    assert bridge_res.pit_reasons == gate["reasons"]


def test_bridge_and_gate_consistent_for_verified(repo):
    p = ResearchProposal(
        proposal_key="ni:EURUSD:EVENT_RESPONSE:y", instrument="EURUSD",
        kind="EVENT_RESPONSE", claim="c", new_information="n", why_different="w",
        market_relevance="m", data_requirements=["d"], falsification_criteria="f",
        governance_status="ALLOWED",
        evidence={"event_response": {"pit_verified": 1, "data_quality": "VERIFIED",
                                      "is_synthetic": False}})
    bridge_res = rb.route_to_research_memory(repo, p, register=False)
    gate = rb.assess_pit_safety(p.evidence)
    assert bridge_res.pit_ready == gate["confirmatory_ready"] == True  # noqa: E712


# =============================================================== Tahap 4: integrity matrix
def test_integrity_matrix_classifies_all_three(repo):
    _ev(repo, period="2026-01", scheduled="2026-01-15T09:55:00Z",
        available="2026-01-15T10:00:00Z", quality="VERIFIED")   # VERIFIED
    _ev(repo, period="2026-02", scheduled="2026-01-15T09:55:00Z")  # UNVERIFIED
    _ev(repo, period="2026-03", scheduled="2026-01-15T09:55:00Z",
        available="2026-01-15T10:00:00Z", synthetic=True)          # SYNTHETIC
    m = asof.pit_integrity_matrix(repo)
    assert m["ext_economic_events"][asof.VERIFIED] == 1
    assert m["ext_economic_events"][asof.UNVERIFIED] == 1
    assert m["ext_economic_events"][asof.SYNTHETIC] == 1


def test_valid_cutoff_required(repo):
    _ev(repo, period="2026-01", scheduled="2026-01-15T09:55:00Z",
        available="2026-01-15T10:00:00Z")
    view = asof.reconstruct_events_as_of(repo, cutoff_ts="not-a-date")
    assert view.rows == []
    assert view.notes
