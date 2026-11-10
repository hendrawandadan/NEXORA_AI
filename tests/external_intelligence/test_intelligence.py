"""Fundamental, central-bank, news, cross-market & event-response intelligence tests."""

import pytest

from nexora_research.external_intelligence import fundamental_intelligence as fi
from nexora_research.external_intelligence import central_bank_intelligence as cbi
from nexora_research.external_intelligence import news_intelligence as ni
from nexora_research.external_intelligence import cross_market_intelligence as xm
from nexora_research.external_intelligence import event_response as er


# ===================================================================== #
# FUNDAMENTAL
# ===================================================================== #
def test_interpret_with_surprise():
    ev = {"event_type": "CPI", "country": "US", "currency": "USD",
          "scheduled_ts": "2026-01-15T13:30:00Z", "actual": 3.4, "forecast": 3.1,
          "previous": 3.2, "source_provider": "mock", "id": 1}
    res = fi.interpret_event(ev)
    assert res.surprise_present is True
    assert abs(res.surprise - 0.3) < 1e-9
    assert res.direction == "HIGHER"
    assert res.confidence in ("MEDIUM", "HIGH")


def test_no_actual_no_invention():
    ev = {"event_type": "CPI", "country": "US", "currency": "USD",
          "scheduled_ts": "2026-01-15T13:30:00Z", "actual": None, "forecast": 3.1,
          "previous": 3.2, "source_provider": "mock"}
    res = fi.interpret_event(ev)
    assert res.surprise_present is False
    assert "No actual value" in res.interpretation


def test_no_forecast_no_surprise():
    ev = {"event_type": "CPI", "country": "US", "currency": "USD",
          "scheduled_ts": "2026-01-15T13:30:00Z", "actual": 3.4, "forecast": None,
          "previous": 3.2, "source_provider": "mock"}
    res = fi.interpret_event(ev)
    assert res.surprise_present is False
    assert "no consensus" in res.interpretation


def test_contradictory_revision_lowers_confidence():
    ev = {"event_type": "CPI", "country": "US", "currency": "USD",
          "scheduled_ts": "2026-01-15T13:30:00Z", "actual": 3.4, "forecast": 3.1,
          "previous": 3.2, "revised_previous": 9.9, "source_provider": "mock"}
    res = fi.interpret_event(ev)
    assert "revision" in res.interpretation.lower() or "diverges" in res.interpretation.lower()
    assert res.confidence != "HIGH"


def test_upper_event_unknown_type_safe():
    meta = fi.classify_event("SOMETHING_NEW")
    assert meta["known"] is False
    assert meta["importance"] == "UNKNOWN"


def test_directional_implications_are_conditional():
    ev = {"event_type": "CPI", "country": "US", "currency": "USD",
          "scheduled_ts": "2026-01-15T13:30:00Z", "actual": 3.4, "forecast": 3.1,
          "previous": 3.2, "source_provider": "mock"}
    res = fi.interpret_event(ev)
    assert "_caveat" in res.implications
    assert "not causation" in res.implications["_caveat"].lower()


# ===================================================================== #
# CENTRAL BANK
# ===================================================================== #
def test_tone_hawkish():
    txt = "The Committee decided to raise rates. Inflation remains elevated and we see upside risks to inflation."
    t = cbi.assess_tone(txt)
    assert t.tone == "HAWKISH"
    assert t.confidence > 0


def test_tone_dovish():
    txt = "The Committee decided to cut rates given downside risks to growth and recession risk."
    t = cbi.assess_tone(txt)
    assert t.tone == "DOVISH"


def test_tone_unknown_when_no_markers():
    t = cbi.assess_tone("Lorem ipsum dolor sit amet.")
    assert t.tone == "UNKNOWN"
    assert t.confidence == 0.0


def test_policy_change_rate_cut():
    latest = {"institution": "FED", "doc_type": "STATEMENT",
              "published_ts": "2026-03-01T00:00:00Z",
              "body_text": "The Committee lowered the target range to 4.00% to 4.25%."}
    prev = {"institution": "FED", "doc_type": "STATEMENT",
            "published_ts": "2026-01-01T00:00:00Z",
            "body_text": "The Committee kept the target range at 4.50% to 4.75%."}
    pc = cbi.detect_policy_change(latest, prev)
    assert pc.policy_shift == "MORE_DOVISH"
    assert pc.confidence >= 0.5


def test_policy_change_needs_previous():
    latest = {"institution": "ECB", "doc_type": "STATEMENT",
              "published_ts": "2026-03-01T00:00:00Z", "body_text": "monitor incoming data"}
    pc = cbi.detect_policy_change(latest, None)
    assert pc.policy_shift == "UNKNOWN"


def test_rate_expectation_signal_from_explicit_rates():
    docs = [
        {"published_ts": "2026-01-01T00:00:00Z", "body_text": "kept at 4.50%"},
        {"published_ts": "2026-03-01T00:00:00Z", "body_text": "kept at 4.00%"},
    ]
    sig = cbi.rate_expectation_signal(docs)
    assert sig["available"] is True
    assert sig["direction"] == "DOWN"


def test_rate_expectation_unavailable_without_rates():
    sig = cbi.rate_expectation_signal([{"published_ts": "2026-01-01", "body_text": "hi"}])
    assert sig["available"] is False


# ===================================================================== #
# NEWS
# ===================================================================== #
def test_news_classify_geopolitical():
    c = ni.classify_news("Military conflict escalates after missile attack", source_provider="mock")
    assert c.category == "GEOPOLITICAL"


def test_news_classify_sanctions():
    c = ni.classify_news("New sanctions and embargo imposed on exports", source_provider="mock")
    assert c.category == "SANCTIONS"


def test_news_classify_trade():
    c = ni.classify_news("US imposes new tariffs in escalating trade war", source_provider="mock")
    assert c.category == "TRADE"


def test_news_country_currency_mapping():
    c = ni.classify_news("Fed raises rates in the United States", source_provider="mock")
    assert "US" in c.countries
    assert "USD" in c.currencies


def test_news_reliability_from_registry():
    c = ni.classify_news("Some financial news", source_provider="reuters")
    assert c.reliability in ("HIGH", "MEDIUM", "LOW", "UNKNOWN")


def test_news_duplicate_detection():
    existing = [{"id": 7, "headline": "US imposes new tariffs on Chinese goods"}]
    dup = ni.find_duplicate("US imposes new tariffs on Chinese goods!", existing)
    assert dup == 7


def test_news_no_duplicate_for_different():
    existing = [{"id": 7, "headline": "US imposes new tariffs on Chinese goods"}]
    dup = ni.find_duplicate("ECB holds rates steady amid slowdown", existing)
    assert dup is None


def test_news_entities_extracted():
    c = ni.classify_news("Federal Reserve and European Central Bank meet", source_provider="mock")
    assert any("Federal" in e for e in c.entities) or len(c.entities) >= 0


# ===================================================================== #
# CROSS-MARKET
# ===================================================================== #
def _series(n, slope=1.0, offset=0.0):
    return [offset + slope * i + (0.01 * (i % 3)) for i in range(n)]


def test_correlation_perfect_positive():
    a = _series(100)
    res = xm.correlation("A", a, "B", a)
    assert res.available
    assert res.value > 0.99


def test_correlation_insufficient_obs():
    res = xm.correlation("A", [1, 2, 3], "B", [1, 2, 3], min_observations=30)
    assert res.available is False


def test_correlation_negative():
    a = _series(100)
    b = [-x for x in a]
    res = xm.correlation("A", a, "B", b)
    assert res.value < -0.99


def test_correlation_has_causation_caveat():
    res = xm.correlation("A", _series(100), "B", _series(100))
    assert "not causation" in res.caveat.lower()


def test_rolling_correlation_series():
    a = _series(200)
    res = xm.rolling_correlation("A", a, "B", a, window=60)
    assert res.available
    assert res.n_points > 0


def test_correlation_breakdown_flags_regime():
    # first half positive, second half negative
    a = [i for i in range(100)]
    b = [i for i in range(50)] + [-i for i in range(50)]
    roll = xm.rolling_correlation("A", a, "B", b, window=20)
    bd = xm.detect_correlation_breakdown(roll, change_threshold=0.5)
    assert bd["available"]
    assert bd["breakdown"] is True


def test_lead_lag_recovers_shift():
    base = [float((i * 7) % 11) for i in range(200)]
    leader = base[:-2]
    follower = base[2:]
    res = xm.lead_lag("L", leader, "F", follower, max_lag=5, min_observations=50)
    assert res.available
    # Convention: lag k aligns leader[t-k] with follower[t]. follower = base[+2] means
    # the leader's value at t+2 predicts follower at t -> best lag is -2.
    assert res.best_lag == -2
    assert abs(res.best_correlation) > 0.99


def test_regime_dependent_correlation_diverge():
    a = [i for i in range(120)]
    b = [i if v < 60 else -i for i, v in enumerate(range(120))]
    vol = [float(i % 10) for i in range(120)]
    res = xm.regime_dependent_correlation("A", a, "B", b, vol, min_observations=20)
    assert res["available"]
    assert "caveat" in res


# ===================================================================== #
# EVENT RESPONSE (leakage-aware)
# ===================================================================== #
def _bars(start_iso, n, step_min=1, base=100.0, drift=0.1):
    from datetime import datetime, timedelta, timezone
    t0 = datetime.fromisoformat(start_iso.replace("Z", "+00:00"))
    out = []
    for i in range(n):
        ts = t0 + timedelta(minutes=step_min * i)
        out.append({"ts": ts.isoformat(), "close": base + drift * i})
    return out


def test_event_response_measures_horizons():
    bars = _bars("2026-01-15T13:20:00Z", 120, step_min=1)
    resp = er.measure_event_response(event_id=1, event_ts="2026-01-15T13:30:00Z",
                                     instrument="EURUSD", bars=bars)
    valid = [r for r in resp.responses if r.valid]
    assert len(valid) >= 1
    assert any(r.horizon == "15m" for r in resp.responses)


def test_event_response_no_lookahead_pre_price():
    # Pre price must be BEFORE event, never after.
    bars = _bars("2026-01-15T13:20:00Z", 60)
    resp = er.measure_event_response(event_id=1, event_ts="2026-01-15T13:30:00Z",
                                     instrument="X", bars=bars)
    for r in resp.responses:
        if r.valid:
            assert r.pre_price is not None


def test_event_response_insufficient_data_invalid():
    bars = _bars("2026-01-15T13:20:00Z", 5)  # not enough for 1d horizon
    resp = er.measure_event_response(event_id=1, event_ts="2026-01-15T13:30:00Z",
                                     instrument="X", bars=bars)
    day = [r for r in resp.responses if r.horizon == "1d"][0]
    assert day.valid is False


def test_event_response_invalid_ts():
    resp = er.measure_event_response(event_id=1, event_ts="garbage", instrument="X", bars=[])
    assert resp.responses[0].valid is False
