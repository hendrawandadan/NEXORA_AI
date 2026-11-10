"""End-to-end orchestrator test: full pipeline on synthetic data (offline)."""

import pytest

from nexora_research.external_intelligence import orchestrator
from nexora_research.external_intelligence.config import ExternalIntelConfig
from nexora_research.store import ResearchMemoryStore


def _bars(start_iso, n, step_min=5, base=100.0, drift=0.05):
    from datetime import datetime, timedelta
    t0 = datetime.fromisoformat(start_iso.replace("Z", "+00:00"))
    return [{"ts": (t0 + timedelta(minutes=step_min * i)).isoformat(),
             "close": base + drift * i} for i in range(n)]


def test_orchestrator_end_to_end_dry(repo, tmp_path):
    events = [{
        "event_type": "CPI", "country": "US", "currency": "USD",
        "scheduled_ts": "2026-01-15T13:30:00Z", "actual": 3.4, "forecast": 3.1,
        "previous": 3.2, "source_provider": "mock", "source_ref": "mock://cpi",
        "retrieved_at_utc": "2026-01-15T13:35:00Z", "_synthetic": True,
        "provenance": "SYNTHETIC",
    }]
    cb = [
        {"institution": "FED", "doc_type": "STATEMENT", "title": "Jan",
         "published_ts": "2026-01-10T00:00:00Z", "source_provider": "mock",
         "source_ref": "u1", "body_text": "kept the target range at 4.50% to 4.75%"},
        {"institution": "FED", "doc_type": "STATEMENT", "title": "Mar",
         "published_ts": "2026-03-10T00:00:00Z", "source_provider": "mock",
         "source_ref": "u2", "body_text": "lowered the target range to 4.00% to 4.25%"},
    ]
    news = [{"headline": "US imposes new tariffs in trade war", "published_ts":
             "2026-02-01T00:00:00Z", "source_provider": "mock"}]
    bars = _bars("2026-01-15T12:00:00Z", 120, step_min=5)

    report = orchestrator.run_intelligence(
        instrument="EURUSD", repo=repo, config=ExternalIntelConfig(),
        events=events, central_bank_docs=cb, news=news, price_bars=bars,
        register=False, record_raw_snapshot=False)
    assert report.events_ingested == 1
    assert report.central_bank_docs == 2
    assert report.news_records == 1
    assert report.findings >= 1
    assert report.proposals >= 1  # CPI surprise + response + CB shift
    assert report.dry_run is True
    assert "UNVALIDATED" in report.bottom_line
    # proposals persisted to isolated external repo
    assert repo.count("ext_research_proposals") >= 1


def test_orchestrator_opt_in_registration(repo, tmp_path):
    store = ResearchMemoryStore(tmp_path / "research.db", bootstrap=True)
    events = [{
        "event_type": "CPI", "country": "US", "currency": "USD",
        "scheduled_ts": "2026-01-15T13:30:00Z", "actual": 3.4, "forecast": 3.1,
        "previous": 3.2, "source_provider": "mock", "source_ref": "mock://cpi",
        "retrieved_at_utc": "2026-01-15T13:35:00Z",
    }]
    bars = _bars("2026-01-15T12:00:00Z", 120, step_min=5)
    report = orchestrator.run_intelligence(
        instrument="EURUSD", repo=repo, research_store=store,
        config=ExternalIntelConfig(), events=events, price_bars=bars,
        register=True, record_raw_snapshot=False)
    assert report.proposals_prepared >= 1
    assert len(store.list_hypotheses()) >= 1


def test_orchestrator_rejects_bad_event(repo):
    events = [{"event_type": "CPI", "country": "US", "currency": "XXX",
               "scheduled_ts": "2026-01-15T13:30:00Z", "source_provider": "mock",
               "retrieved_at_utc": "2026-01-15T13:35:00Z"}]
    report = orchestrator.run_intelligence(
        instrument="EURUSD", repo=repo, events=events, record_raw_snapshot=False)
    assert report.events_ingested == 0
    assert any("rejected" in n for n in report.notes)


def test_orchestrator_no_data_still_reports(repo):
    report = orchestrator.run_intelligence(
        instrument="EURUSD", repo=repo, record_raw_snapshot=False)
    assert report.proposals == 0
    assert report.bottom_line
    assert report.providers_known > 0
