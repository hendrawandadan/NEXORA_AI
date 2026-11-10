"""Read-only runner: STAGE 2 — Instrument Discovery.

Read-only research. No training, no config/model writes, no data modification.
Writes ONLY under reports/economic_opportunity_discovery/.

Instruments (data on disk):
  EURUSD   bars     2020-2026   spread: <SPREAD column> unreliable (estimate)
  GBPUSDm  tick zip 2020-2025   spread: REAL Bid/Ask  (data/raw/GBPUSD/*.zip)
  USDJPYm  tick zip 2020-2025   spread: REAL Bid/Ask  (data/raw/USDJPY/*.zip)
  XAUUSD   bars     data/raw/XAUUSD_H4.csv  + tick zip (data/raw/XAUUSD/*.zip)
  AUDUSD, USDCAD, USDCHF -> DATA_UNAVAILABLE (no files on disk)

For each instrument we collect: date range, timeframes available, bar count,
missing %, duplicate timestamps, spread distribution (real for tick, estimate for
bar-only), spread by session, volatility, movement-to-cost ratio at a reference
horizon, and a transparent data-quality score.

Heavy: tick pass streams chunks and only keeps aggregates. Use --years / --instruments
to limit a run; default analyses ALL available tick years for chosen instruments.

Usage:
    $env:PYTHONPATH="."
    python tools/run_instrument_discovery.py                      # full
    python tools/run_instrument_discovery.py --instruments GBPUSDm,XAUUSD --years 2023,2024
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Dict, List, Optional

import pandas as pd

from nexora_datahub.loader import load_bars, timeframe_minutes
from nexora_laboratory.opportunity_discovery.granularity import granularity_break
from nexora_laboratory.opportunity_discovery.horizon import (
    Scenario, horizon_economics, pip_size_for,
)
from nexora_laboratory.opportunity_discovery.bar_quality import bar_quality, quality_score
from nexora_laboratory.opportunity_discovery.tick_spread import analyze_tick_files

OUT = Path("reports/economic_opportunity_discovery")

# Reference horizons (in bars) for a rough move-to-cost at each TF.
REF_HORIZONS = {"M30": [24, 48], "H1": [12, 24], "H4": [4, 8, 12], "D1": [1, 2]}

# Bar sources (intraday files for quality/economics). EURUSD/XAUUSD only.
BAR_FILES = {
    "EURUSD": {
        "M30": "data/raw/EURUSD/EURUSD_M30_202001020000_202611062130.csv",
        "H1": "data/raw/EURUSD/EURUSD_H1_202001020000_202611062100.csv",
        "H4": "data/raw/EURUSD/EURUSD_H4_202001020000_202611062000.csv",
    },
    "XAUUSD": {
        "H1": "data/raw/XAUUSD_H1.csv",
        "H4": "data/raw/XAUUSD_H4.csv",
        "D1": "data/raw/XAUUSD_D1.csv",
    },
}

# Tick sources (zip). GBPUSDm/USDJPYm subfolders; XAUUSD from its folder.
TICK_DIRS = {
    "GBPUSDm": ("data/raw/GBPUSD", "GBPUSDm"),
    "USDJPYm": ("data/raw/USDJPY", "USDJPYm"),
    "XAUUSDm": ("data/raw/XAUUSD", "XAUUSDm"),
}

UNAVAILABLE = ["AUDUSD", "USDCAD", "USDCHF"]


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _tick_paths(instrument: str, years: Optional[List[str]]) -> List[Path]:
    d, tag = TICK_DIRS[instrument]
    base = Path(d)
    files = sorted(base.glob(f"Exness_{tag}_*.zip"))
    if years:
        keep = {str(y) for y in years}
        files = [f for f in files if any(f"_{y}.zip" in f.name for y in keep)]
    return files


def analyze_bar_instrument(symbol: str) -> Dict[str, object]:
    """Quality + move economics per available timeframe for a bar instrument."""
    pip = pip_size_for(symbol)
    out: Dict[str, object] = {"symbol": symbol, "source": "bars", "pip_size": pip,
                              "timeframes": {}}
    for tf, path in BAR_FILES[symbol].items():
        p = Path(path)
        if not p.exists():
            out["timeframes"][tf] = {"status": "missing", "file": path}
            continue
        bars_full = load_bars(p)
        expected = timeframe_minutes(tf)
        brk = granularity_break(bars_full, expected)
        seg = bars_full.iloc[brk["intraday_start_index"]:].reset_index(drop=True)
        q = bar_quality(bars_full, expected)
        q["quality"] = quality_score(q)

        # Use bar <SPREAD> as a (possibly unreliable) baseline; otherwise default.
        sp = q.get("spread", {})
        if sp.get("available") and sp.get("median_nonzero"):
            # MT5 spread is in broker POINTS. Convert points->pips.
            # FX 5-digit: 10 points/pip. JPY 3-digit: 10 points/pip. XAU: points->? 
            # To avoid inventing conversions, we report raw and only use a
            # documented default baseline where reliability is poor.
            pass
        # Baseline cost: explicit assumption; for bar-only instruments spread is
        # an ESTIMATE (documented). Conservative per-instrument defaults:
        base_spread_pips = {"EURUSD": 3.0, "GBPUSD": 3.0, "USDJPY": 2.0,
                            "XAUUSD": 25.0}.get(symbol, 3.0)
        scen = [
            Scenario("optimistic", spread_pips=max(0.5, base_spread_pips * 0.5), slippage_pips=0.2),
            Scenario("baseline", spread_pips=base_spread_pips, slippage_pips=0.2),
            Scenario("stress", spread_pips=round(base_spread_pips * 1.6, 2), slippage_pips=0.5),
        ]
        horizons = REF_HORIZONS.get(tf, [4, 8])
        econ = horizon_economics(seg, horizons, scen, pip)
        out["timeframes"][tf] = {
            "file": path,
            "quality": q,
            "cost_baseline_pips": base_spread_pips,
            "cost_note": ("bar-only: spread is an ESTIMATE assumption; "
                          "true tick Bid/Ask not present in this file"),
            "scenarios": {s.name: s.round_trip_pips for s in scen},
            "horizons": horizons,
            "analysis_window": {"start": brk["intraday_first"],
                                "end": brk["intraday_last"],
                                "rows_used": brk["segment_rows"]},
            "economics": econ["economics"],
            "stability_by_year": econ["stability_by_year"],
        }
    return out


def analyze_tick_instrument(instrument: str, years: Optional[List[str]]) -> Dict[str, object]:
    """Real Bid/Ask spread distribution from Exness tick zips."""
    pip = pip_size_for(instrument.replace("m", "") if instrument.endswith("m") else instrument)
    # note: 'm' suffix is broker tag; pip size from base symbol
    if "JPY" in instrument.upper():
        pip = 0.01
    elif "XAU" in instrument.upper():
        pip = 0.10
    else:
        pip = 0.0001
    files = _tick_paths(instrument, years)
    if not files:
        return {"symbol": instrument, "source": "tick", "status": "no_files",
                "years_requested": years}
    summary = analyze_tick_files(files, pip)
    return {
        "symbol": instrument,
        "source": "tick",
        "pip_size": pip,
        "files": [str(f) for f in files],
        "spread": summary,
    }


def _instrument_by_key(results: Dict[str, object], key: str):
    for r in results.values():
        if r.get("symbol") == key:
            return r
    return None


def main(argv=None) -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--instruments", default="",
                    help="comma list e.g. GBPUSDm,XAUUSDm or bar names EURUSD,XAUUSD")
    ap.add_argument("--years", default="",
                    help="comma list of tick years to include e.g. 2023,2024")
    ap.add_argument("--skip-ticks", action="store_true", help="skip heavy tick analysis")
    args = ap.parse_args(argv)

    OUT.mkdir(parents=True, exist_ok=True)
    sel = {s.strip() for s in args.instruments.split(",") if s.strip()}
    years = [y.strip() for y in args.years.split(",")] if args.years else None

    result: Dict[str, object] = {
        "stage": 2,
        "note": ("STAGE 2 Instrument Discovery. Read-only. Tick spread is REAL "
                 "Bid/Ask for GBPUSDm/USDJPYm/XAUUSDm; bar-only instruments use an "
                 "ESTIMATED baseline spread (documented). movement-to-cost is a "
                 "descriptive availability metric, NOT a predictability claim."),
        "data_unavailable": UNAVAILABLE,
        "instruments": {},
        "inputs": {},
    }

    # ---- bar instruments ----
    for sym in ("EURUSD", "XAUUSD"):
        if sel and sym not in sel:
            continue
        result["instruments"][sym] = analyze_bar_instrument(sym)
        for tf, info in BAR_FILES[sym].items():
            p = Path(info)
            if p.exists():
                result["inputs"][f"{sym}_{tf}"] = {"path": info, "sha256": _sha256(p)}

    # ---- tick instruments ----
    if not args.skip_ticks:
        for inst in ("GBPUSDm", "USDJPYm", "XAUUSDm"):
            if sel and inst not in sel:
                continue
            result["instruments"][inst] = analyze_tick_instrument(inst, years)

    # ---- cross-reference + header ----
    out_json = OUT / "instrument_discovery.json"
    out_json.write_text(json.dumps(result, indent=2, default=str), encoding="utf-8")
    manifest = {
        "inputs": result["inputs"],
        "outputs": {"instrument_discovery.json": _sha256(out_json)},
        "instruments_analyzed": list(result["instruments"]),
        "tick_years": years,
        "skip_ticks": bool(args.skip_ticks),
    }
    (OUT / "instrument_discovery_manifest.json").write_text(
        json.dumps(manifest, indent=2), encoding="utf-8")

    # ---- console summary ----
    print("=" * 78)
    print("STAGE 2 — INSTRUMENT DISCOVERY")
    print("=" * 78)
    for name, r in result["instruments"].items():
        if r.get("source") == "bars":
            print(f"\n### {name} (bars)")
            for tf, t in r["timeframes"].items():
                if t.get("status") == "missing":
                    print(f"  {tf}: MISSING {t['file']}")
                    continue
                q = t["quality"]
                print(f"  {tf}: rows={q['n_bars']} intraday={q['intraday_rows']} "
                      f"missing~{q['missing_frac_est']} grade={q['quality']['grade']} "
                      f"({q['quality']['score']})")
                for row in t["economics"]:
                    if row["scenario"] == "baseline":
                        print(f"      h={row['horizon_bars']:>2} med={row['median_move_pips']:>8}pip "
                              f"ratio={row['move_to_cost_ratio']} req_sym={row['required_acc_symmetric']}")
        else:
            print(f"\n### {name} (tick)")
            sp = r.get("spread", {})
            if sp:
                print(f"  ticks={sp.get('n_ticks')} invalid={sp.get('n_invalid')} "
                      f"range={sp.get('time_start')}..{sp.get('time_end')}")
                print(f"  spread pips: median={sp.get('spread_pips_median')} "
                      f"mean={sp.get('spread_pips_mean')} p90={sp.get('spread_pips_p90')} "
                      f"p99={sp.get('spread_pips_p99')}")
                for s, v in (sp.get("by_session") or {}).items():
                    if v.get("n_ticks"):
                        print(f"    {s}: n={v['n_ticks']} median={v['spread_pips_median']} "
                              f"mean={v['spread_pips_mean']}")
    print("\nwrote", out_json)


if __name__ == "__main__":
    main()
