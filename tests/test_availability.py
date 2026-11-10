"""Tests for STAGE 4 — Data Availability & Quality (availability module)."""

import pytest

from nexora_laboratory.opportunity_discovery.availability import (
    InstrumentAvailability, build_availability, _years_between,
    GRADE_POINTS, MIN_YEARS_FOR_IC,
)


# ---------- helpers ----------
def _bar_inst(symbol, grade_score, grade, start, end, tfs_horizons, intraday=5000):
    return {
        "symbol": symbol, "source": "bars", "pip_size": 0.0001,
        "timeframes": {
            tf: {
                "quality": {"first_ts": start, "last_ts": end,
                            "intraday_rows": intraday,
                            "quality": {"score": grade_score, "grade": grade}},
                "economics": [{"scenario": "baseline", "horizon_bars": h} for h in hs],
            } for tf, hs in tfs_horizons.items()
        },
    }


def _tick_inst(symbol, start, end):
    return {"symbol": symbol, "source": "tick", "pip_size": 0.01,
            "spread": {"time_start": start, "time_end": end, "n_ticks": 100}}


# ---------- years helper ----------
def test_years_between():
    assert _years_between("2020-01-01", "2023-01-01") == pytest.approx(3.0, abs=0.1)
    assert _years_between(None, "2023-01-01") is None
    assert _years_between("2023-01-01", "2020-01-01") == 0.0


# ---------- readiness scoring ----------
def test_ready_instrument_scores_high():
    a = InstrumentAvailability(instrument="X", source="bars", has_bars=True,
                               quality_grade="A", quality_score=1.0,
                               years_history=6.0, intraday_bars=50000,
                               tick_spread_source="tick",
                               horizons_available={"H4": [4, 8, 12], "H1": [12, 24],
                                                   "M30": [24, 48], "D1": [1, 2]})
    r = a.readiness()
    assert r["readiness_score"] >= 0.9
    assert r["verdict"] == "READY"


def test_estimated_spread_lowers_readiness_vs_tick():
    base = dict(instrument="X", source="bars", has_bars=True, quality_grade="A",
                quality_score=1.0, years_history=6.0, intraday_bars=50000,
                horizons_available={"H4": [4, 8, 12]})
    tick = InstrumentAvailability(tick_spread_source="tick", **base).readiness()
    est = InstrumentAvailability(tick_spread_source="estimate", **base).readiness()
    assert est["readiness_score"] < tick["readiness_score"]
    assert est["components"]["cost_credibility"] < tick["components"]["cost_credibility"]


def test_short_history_lowers_depth():
    long = InstrumentAvailability(instrument="X", source="bars", has_bars=True,
                                  quality_score=1.0, years_history=6.0,
                                  intraday_bars=50000, tick_spread_source="tick")
    short = InstrumentAvailability(instrument="Y", source="bars", has_bars=True,
                                   quality_score=1.0, years_history=1.0,
                                   intraday_bars=50000, tick_spread_source="tick")
    assert short.readiness()["components"]["history_depth"] < \
        long.readiness()["components"]["history_depth"]


def test_unavailable_scores_zero():
    a = InstrumentAvailability(instrument="Z", source="none")
    r = a.readiness()
    assert r["readiness_score"] == 0.0
    assert r["verdict"] == "NOT_READY"


def test_weights_sum_to_one():
    a = InstrumentAvailability(instrument="X", source="bars")
    assert sum(a.readiness()["weights"].values()) == pytest.approx(1.0)


# ---------- build_availability integration ----------
def _stage2():
    return {
        "data_unavailable": ["AUDUSD"],
        "instruments": {
            "XAUUSD": _bar_inst("XAUUSD", 1.0, "A", "2020-01-01", "2025-07-20",
                                {"H4": [4, 8, 12], "H1": [12, 24], "D1": [1, 2]}),
            "XAUUSDm": _tick_inst("XAUUSDm", "2020-01-02", "2025-07-20"),
            "GBPUSDm": _tick_inst("GBPUSDm", "2020-01-02", "2025-12-31"),
        },
    }


def test_build_combines_bar_and_tick_sibling():
    res = build_availability(_stage2(), stage3=None)
    xm = res["instruments"]["XAUUSDm"]
    # XAUUSDm should inherit bar quality from XAUUSD sibling
    assert xm["has_bars"] is True and xm["has_tick"] is True
    assert xm["source"] == "bars+tick"
    assert xm["quality_grade"] == "A"


def test_build_flags_tick_only_as_partial():
    res = build_availability(_stage2(), stage3=None)
    gbp = res["instruments"]["GBPUSDm"]
    # tick present, real spread but NO bar OHLC -> cannot compute bars/moves
    assert gbp["has_tick"] is True and gbp["has_bars"] is False
    assert gbp["verdict"] in ("PARTIAL", "NOT_READY")
    assert gbp["components"]["coverage"] == 0.0


def test_build_marks_unavailable():
    res = build_availability(_stage2(), stage3=None)
    aud = res["instruments"]["AUDUSD"]
    assert aud["verdict"] == "NOT_READY"
    assert any("DATA_UNAVAILABLE" in g for g in aud["gaps"])


def test_build_detects_truncated_tick_coverage():
    s2 = {
        "data_unavailable": [],
        "instruments": {
            "XAUUSD": _bar_inst("XAUUSD", 1.0, "A", "2020-01-01", "2026-01-01",
                                {"H4": [4, 8, 12]}),
            "XAUUSDm": _tick_inst("XAUUSDm", "2020-01-02", "2025-07-20"),
        },
    }
    res = build_availability(s2, stage3=None)
    xm = res["instruments"]["XAUUSDm"]
    assert any("tick coverage ends" in g for g in xm["gaps"])


def test_build_uses_stage3_spread_source():
    s3 = {"instruments": {"EURUSD": {"spread_source": "estimate",
                                     "commission_status": "NOT_AVAILABLE"}}}
    s2 = {"data_unavailable": [],
          "instruments": {"EURUSD": _bar_inst("EURUSD", 0.65, "C", "2020-01-01",
                                              "2026-01-01", {"H4": [4, 8, 12]})}}
    res = build_availability(s2, s3)
    eur = res["instruments"]["EURUSD"]
    assert eur["tick_spread_source"] == "estimate"
    assert any("ESTIMATED" in g for g in eur["gaps"])


def test_ranking_sorted_desc():
    res = build_availability(_stage2(), stage3=None)
    scores = [res["instruments"][k]["readiness_score"] for k in res["ranking"]]
    assert scores == sorted(scores, reverse=True)


def test_summary_buckets():
    res = build_availability(_stage2(), stage3=None)
    summ = res["summary"]
    assert "XAUUSD" in summ["ready"]
    assert "AUDUSD" in summ["not_ready"]
