"""Tests for STAGE 2 — Instrument Discovery modules.

Uses small synthetic frames/files (no dependency on the multi-GB real exports):
  * tick_spread.SpreadAccumulator  — spread stats + per-session split
  * tick_spread.analyze_tick_file / analyze_tick_files — streaming CSV & ZIP
  * bar_quality.bar_quality / quality_score — quality metrics & scoring
"""

import zipfile
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from nexora_laboratory.opportunity_discovery.tick_spread import (
    SpreadAccumulator, analyze_tick_file, analyze_tick_files,
)
from nexora_laboratory.opportunity_discovery.bar_quality import (
    bar_quality, quality_score,
)


# ---------- spread accumulator ----------
def _tick_csv(path: Path, n_per_hour=100, hours=24, spread_pips=0.5, pip=0.0001):
    rows = ['"Exness","Symbol","Timestamp","Bid","Ask"']
    base = pd.Timestamp("2023-01-02 00:00:00")
    for h in range(hours):
        for i in range(n_per_hour):
            ts = base + pd.Timedelta(hours=h, seconds=i)
            bid = 1.1000
            ask = bid + spread_pips * pip
            rows.append(f'"exness","X","{ts.strftime("%Y-%m-%d %H:%M:%S.000")}Z",{bid:.5f},{ask:.5f}')
    path.write_text("\n".join(rows), encoding="utf-8")
    return path


def test_accumulator_basic_stats():
    acc = SpreadAccumulator()
    ts = pd.to_datetime(["2023-01-02 00:00", "2023-01-02 09:00", "2023-01-02 14:00"], utc=True)
    bid = np.array([1.1000, 1.1000, 1.1000])
    ask = np.array([1.10005, 1.10010, 1.10020])  # 0.5, 1.0, 2.0 pips
    acc.add_chunk(pd.Series(ts), bid, ask, pip_size=0.0001)
    s = acc.summary()
    assert s["n_ticks"] == 3
    assert s["spread_pips_min"] == pytest.approx(0.5, abs=1e-2)
    assert s["spread_pips_max"] == pytest.approx(2.0, abs=1e-2)
    assert s["spread_pips_mean"] == pytest.approx((0.5 + 1.0 + 2.0) / 3, abs=1e-2)


def test_accumulator_rejects_invalid_ask_below_bid():
    acc = SpreadAccumulator()
    ts = pd.Series(pd.to_datetime(["2023-01-02 00:00", "2023-01-02 00:01"], utc=True))
    bid = np.array([1.1000, 1.1000])
    ask = np.array([1.1001, 1.0999])  # 2nd invalid (ask<bid)
    acc.add_chunk(ts, bid, ask, pip_size=0.0001)
    s = acc.summary()
    assert s["n_ticks"] == 1
    assert s["n_invalid"] == 1


def test_accumulator_session_split():
    acc = SpreadAccumulator()
    # one tick in ASIA(00h), one in LONDON(09h), one in NY(14h), one in LATE(22h)
    ts = pd.Series(pd.to_datetime(
        ["2023-01-02 00:00", "2023-01-02 09:00", "2023-01-02 14:00", "2023-01-02 22:00"],
        utc=True))
    bid = np.array([1.1, 1.1, 1.1, 1.1])
    ask = bid + 0.0001  # 1 pip each
    acc.add_chunk(ts, bid, ask, pip_size=0.0001)
    s = acc.summary()
    for sess in ("ASIA", "LONDON", "NY", "LATE"):
        assert s["by_session"][sess]["n_ticks"] == 1


def test_accumulator_quantile_from_uniform_hist():
    acc = SpreadAccumulator(bin_width_pips=0.1)
    n = 1000
    ts = pd.Series(pd.to_datetime(["2023-01-02 00:00"] * n, utc=True))
    # all 0.5 pip
    bid = np.full(n, 1.1)
    ask = bid + 0.5 * 0.0001
    acc.add_chunk(ts, bid, ask, pip_size=0.0001)
    s = acc.summary()
    assert abs(s["spread_pips_median"] - 0.5) <= 0.1


# ---------- streaming CSV / ZIP ----------
def test_analyze_tick_file_csv(tmp_path):
    p = _tick_csv(tmp_path / "ticks.csv", n_per_hour=10, hours=4, spread_pips=0.8)
    r = analyze_tick_file(p, pip_size=0.0001, chunksize=50)
    assert r["rows_parsed"] == 40
    assert abs(r["spread_pips_median"] - 0.8) <= 0.1
    assert r["time_start"].startswith("2023-01-02")


def test_analyze_tick_file_zip(tmp_path):
    csv = _tick_csv(tmp_path / "inner.csv", n_per_hour=10, hours=4, spread_pips=1.2)
    zpath = tmp_path / "ticks.zip"
    with zipfile.ZipFile(zpath, "w") as zf:
        zf.write(csv, arcname="Exness_X_2023.csv")
    r = analyze_tick_file(zpath, pip_size=0.0001, chunksize=50)
    assert r["rows_parsed"] == 40
    assert abs(r["spread_pips_median"] - 1.2) <= 0.1


def test_analyze_tick_files_combines(tmp_path):
    p1 = _tick_csv(tmp_path / "a.csv", n_per_hour=10, hours=2, spread_pips=0.5)
    p2 = _tick_csv(tmp_path / "b.csv", n_per_hour=10, hours=2, spread_pips=1.5)
    r = analyze_tick_files([p1, p2], pip_size=0.0001, chunksize=50)
    assert r["n_ticks"] == 40  # 20 + 20
    assert len(r["per_file"]) == 2


# ---------- bar quality ----------
def _synthetic_bars(n=500, tf_minutes=60, prefix_daily=10):
    idx = pd.date_range("2020-01-01", periods=n, freq=f"{tf_minutes}min")
    # prepend daily-prefix (24h gaps) to exercise granularity detection
    prefix_idx = pd.date_range("2019-01-01", periods=prefix_daily, freq="1440min")
    all_idx = prefix_idx.append(idx)
    close = np.linspace(1.10, 1.12, len(all_idx))
    df = pd.DataFrame({
        "ts": all_idx,
        "open": close, "high": close + 0.001, "low": close - 0.001, "close": close,
        "volume": 100,
        "spread": np.r_[np.zeros(prefix_daily), np.full(n, 15.0)],  # points
    })
    return df


def test_bar_quality_detects_prefix_and_missing():
    bars = _synthetic_bars(n=500, tf_minutes=60, prefix_daily=10)
    q = bar_quality(bars, expected_minutes=60)
    assert q["granularity"]["has_daily_prefix"] is True
    assert q["n_bars"] == 510
    assert q["intraday_rows"] == 500
    assert q["spread"]["available"] is True
    assert q["spread"]["pct_zero"] == pytest.approx(10 / 510, abs=1e-3)
    assert q["spread"]["reliable"] is True  # only 2% zero overall


def test_bar_quality_missing_frac_low_for_complete():
    bars = _synthetic_bars(n=500, tf_minutes=60, prefix_daily=10)
    q = bar_quality(bars, expected_minutes=60)
    # weekdays-only synthetic spans are dense -> low missing
    assert q["missing_frac_est"] is not None
    assert q["missing_frac_est"] < 0.5


def test_quality_score_grades():
    good = quality_score({"granularity": {"has_daily_prefix": False},
                          "missing_frac_est": 0.0, "n_duplicate_ts": 0,
                          "spread": {"available": True, "reliable": True}})
    assert good["grade"] in ("A", "B")
    bad = quality_score({"granularity": {"has_daily_prefix": True},
                         "missing_frac_est": 0.4, "n_duplicate_ts": 5,
                         "spread": {"available": True, "reliable": False}})
    assert bad["score"] < good["score"]
    assert bad["grade"] in ("C", "D")


def test_quality_score_spread_unreliable_penalised():
    base = {"granularity": {"has_daily_prefix": False}, "missing_frac_est": 0.0,
            "n_duplicate_ts": 0}
    reliable = quality_score({**base, "spread": {"available": True, "reliable": True}})
    unreliable = quality_score({**base, "spread": {"available": True, "reliable": False}})
    assert unreliable["score"] < reliable["score"]
