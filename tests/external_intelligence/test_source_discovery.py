"""Source discovery + registry + connectors tests (requirement §11.A)."""

import pytest

from nexora_research.external_intelligence import source_registry as sr
from nexora_research.external_intelligence import connectors as cx
from nexora_research.external_intelligence.config import ExternalIntelConfig


# ---------- registry integrity ----------
def test_registry_has_all_tiers():
    assert len(sr.providers_by_tier(1)) > 0
    assert len(sr.providers_by_tier(2)) > 0
    assert len(sr.providers_by_tier(3)) > 0


def test_every_provider_documents_required_fields():
    for p in sr.all_providers():
        d = p.as_dict()
        for key in ("tier", "category", "access_method", "auth", "rate_limits",
                    "coverage", "historical_coverage", "update_frequency", "cost",
                    "license", "reliability", "failure_handling", "connector_available"):
            assert key in d, f"{p.provider_id} missing {key}"


def test_valid_source_lookup():
    p = sr.get_provider("fred")
    assert p.tier == 1
    assert p.auth_env_var == "NEXORA_FRED_API_KEY"


def test_invalid_source_raises():
    with pytest.raises(KeyError):
        sr.get_provider("does_not_exist")


def test_no_provider_stores_secret_values():
    # Registry only NAMES env vars; it never stores a secret value.
    for p in sr.all_providers():
        assert not p.as_dict().get("secret_value")


def test_bloomberg_not_scrapeable_and_not_connected():
    p = sr.get_provider("bloomberg")
    assert p.tos_safe_to_scrape is False
    assert p.connector_available is False


def test_unavailable_connector_build_raises():
    # boj has no connector in this build -> NotImplementedError, fail-closed.
    with pytest.raises(NotImplementedError):
        cx.build_connector("boj_press")


# ---------- duplicate source registration ----------
def test_duplicate_source_ids_absent():
    ids = [p.provider_id for p in sr.all_providers()]
    assert len(ids) == len(set(ids)), "duplicate provider_id"


# ---------- provider unavailable / rate limit / timeout ----------
def test_mock_unavailable_resource():
    conn = cx.MockConnector({"calendar": []})
    r = conn.fetch(resource="missing_res")
    assert r.status is cx.FetchStatus.UNAVAILABLE
    assert not r.ok


def test_fred_unavailable_without_key(monkeypatch):
    monkeypatch.delenv("NEXORA_FRED_API_KEY", raising=False)
    conn = cx.FredConnector(ExternalIntelConfig())
    r = conn.fetch(resource="CPIAUCSL")
    assert r.status is cx.FetchStatus.UNAVAILABLE
    assert "not set" in r.message


def test_rate_limiter_blocks():
    lim = cx.RateLimiter(per_min=2)
    assert lim.try_acquire(now=1.0) is True
    assert lim.try_acquire(now=1.0) is True
    assert lim.try_acquire(now=1.0) is False  # exceeded
    # next window resets
    assert lim.try_acquire(now=62.0) is True


def test_connector_rate_limited_status():
    conn = cx.MockConnector({"a": []}, ExternalIntelConfig(rate_limit_per_min=1))
    assert conn.fetch(resource="a").ok
    r2 = conn.fetch(resource="a")
    assert r2.status is cx.FetchStatus.RATE_LIMITED


def test_connector_timeout_is_fail_closed(monkeypatch):
    conn = cx.MockConnector({})
    def boom(**kw):
        raise TimeoutError("simulated")
    monkeypatch.setattr(conn, "_fetch", boom)
    r = conn.fetch(resource="x")
    assert r.status is cx.FetchStatus.TIMEOUT


def test_mock_records_tagged_synthetic():
    conn = cx.MockConnector({"econ": [{"event_type": "CPI"}]})
    r = conn.fetch(resource="econ")
    assert r.ok
    assert r.records[0]["provenance"] == "SYNTHETIC"
    assert r.content_sha256  # hashed


def test_connector_status_honest():
    status = cx.connector_status(ExternalIntelConfig())
    assert status["mock"].startswith("READY")
    # FRED is unconfigured without env
    if "fred" in status:
        assert "UNCONFIGURED" in status["fred"]
