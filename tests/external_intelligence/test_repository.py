"""Repository + data-validation + isolation tests (requirements §11.B and §11.F)."""

import pytest

from nexora_research.external_intelligence.repository import (
    ExternalKnowledgeRepository, IsolationViolation,
)
from nexora_research.external_intelligence.config import PRODUCTION_DB_PATH, RESEARCH_DB_PATH


# ---------- isolation: refuses protected DBs ----------
def test_refuses_production_db():
    with pytest.raises(IsolationViolation):
        ExternalKnowledgeRepository(PRODUCTION_DB_PATH, bootstrap=False)


def test_refuses_research_db():
    with pytest.raises(IsolationViolation):
        ExternalKnowledgeRepository(RESEARCH_DB_PATH, bootstrap=False)


def test_isolated_path_is_distinct(repo):
    assert repo.db_path != PRODUCTION_DB_PATH
    assert repo.db_path != RESEARCH_DB_PATH


# ---------- schema versioning ----------
def test_schema_version(repo):
    # R1 adds migration 002 (external lane guard), R2 adds 003 (point-in-time) -> v3.
    assert repo.schema_version() == 3


# ---------- valid insert ----------
def test_insert_valid_event(repo, sample_event):
    r = repo.insert_economic_event(**sample_event)
    assert r["inserted"] is True
    assert r["content_sha256"]
    got = repo.get_event(r["id"])
    assert float(got["actual"]) == 3.4


# ---------- missing values respected (no fabrication) ----------
def test_missing_actual_and_forecast_allowed(repo, sample_event):
    sample_event = dict(sample_event)
    sample_event["actual"] = None
    sample_event["forecast"] = None
    r = repo.insert_economic_event(**sample_event)
    got = repo.get_event(r["id"])
    assert got["actual"] is None
    assert got["forecast"] is None
    assert got["has_actual"] == 0
    assert got["has_forecast"] == 0


# ---------- invalid timestamps rejected ----------
def test_invalid_timestamp_rejected(repo, sample_event):
    sample_event = dict(sample_event)
    sample_event["scheduled_ts"] = "not-a-date"
    with pytest.raises(ValueError):
        repo.insert_economic_event(**sample_event)


def test_absurd_future_timestamp_rejected(repo, sample_event):
    sample_event = dict(sample_event)
    sample_event["scheduled_ts"] = "2999-01-01T00:00:00Z"
    with pytest.raises(ValueError):
        repo.insert_economic_event(**sample_event)


# ---------- invalid currency mapping rejected ----------
def test_invalid_currency_rejected(repo, sample_event):
    sample_event = dict(sample_event)
    sample_event["currency"] = "XYZ"
    with pytest.raises(ValueError):
        repo.insert_economic_event(**sample_event)


# ---------- duplicate detection (idempotent) ----------
def test_duplicate_event_not_double_inserted(repo, sample_event):
    r1 = repo.insert_economic_event(**sample_event)
    r2 = repo.insert_economic_event(**sample_event)
    assert r1["inserted"] is True
    assert r2["inserted"] is False
    assert r1["id"] == r2["id"]
    assert repo.count("ext_economic_events") == 1


# ---------- revised value records a NEW row (append-only) ----------
def test_revised_value_is_append_only(repo, sample_event):
    r1 = repo.insert_economic_event(**sample_event)
    revised = dict(sample_event)
    revised["revised_previous"] = 3.0
    r2 = repo.insert_economic_event(supersedes_id=r1["id"], **revised)
    assert r2["inserted"] is True
    assert r2["id"] != r1["id"]
    assert repo.count("ext_economic_events") == 2  # both preserved


# ---------- invalid news currency rejected ----------
def test_news_invalid_currency_rejected(repo):
    with pytest.raises(ValueError):
        repo.insert_news(headline="x", category="ECONOMIC",
                         published_ts="2026-01-15T00:00:00Z", source_provider="mock",
                         retrieved_at_utc="2026-01-15T00:01:00Z", currencies=["ZZZ"])


def test_news_invalid_category_rejected(repo):
    with pytest.raises(ValueError):
        repo.insert_news(headline="x", category="BOGUS",
                         published_ts="2026-01-15T00:00:00Z", source_provider="mock",
                         retrieved_at_utc="2026-01-15T00:01:00Z")


# ---------- central bank doc validation ----------
def test_cb_doc_requires_source_ref(repo):
    with pytest.raises(ValueError):
        repo.insert_central_bank_doc(institution="FED", doc_type="STATEMENT", title="t",
                                     published_ts="2026-01-15T00:00:00Z",
                                     source_provider="mock", source_ref="",
                                     body_text="text", retrieved_at_utc="2026-01-15T00:01:00Z")


def test_cb_doc_tone_confidence_range(repo):
    with pytest.raises(ValueError):
        repo.insert_central_bank_doc(institution="FED", doc_type="STATEMENT", title="t",
                                     published_ts="2026-01-15T00:00:00Z",
                                     source_provider="mock", source_ref="u",
                                     body_text="text", retrieved_at_utc="2026-01-15T00:01:00Z",
                                     tone="HAWKISH", tone_confidence=1.5)


def test_cb_doc_invalid_tone_rejected(repo):
    with pytest.raises(ValueError):
        repo.insert_central_bank_doc(institution="FED", doc_type="STATEMENT", title="t",
                                     published_ts="2026-01-15T00:00:00Z",
                                     source_provider="mock", source_ref="u",
                                     body_text="text", retrieved_at_utc="2026-01-15T00:01:00Z",
                                     tone="ANGRY")


# ---------- audit trail ----------
def test_audit_trail_records_writes(repo, sample_event):
    repo.insert_economic_event(**sample_event)
    log = repo.audit_log()
    assert any(e["table_name"] == "ext_economic_events" for e in log)


# ---------- content hash present on every stored row ----------
def test_content_hash_present(repo, sample_event):
    r = repo.insert_economic_event(**sample_event)
    assert len(r["content_sha256"]) == 64  # sha256 hex
