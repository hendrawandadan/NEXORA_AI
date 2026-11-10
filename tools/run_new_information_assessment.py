"""Read-only runner: STAGE 5 — New Information Assessment (IC OOS).

Model-free diagnostic: for each instrument & candidate (timeframe, horizon), test
whether causal price-derived FEATURES carry out-of-sample information about FORWARD
returns, via Spearman IC on a temporal TRAIN/TEST split, with BH-FDR + Bonferroni
multiple-comparison correction.

Instrument priority (from STAGE 4 readiness):
  * XAUUSDm (primary) -> uses XAUUSD bar OHLC for features/labels (bar grade A) and
    tick (XAUUSDm) spread for cost context. NOTE: OHLC comes from spot XAUUSD bars,
    there are no bars derived from XAUUSDm ticks.
  * EURUSD (secondary) -> bar grade C, spread is an ESTIMATE (interpret cautiously).

This does NOT train a model and makes NO profitability claim. Weak/insignificant ICs
(and negative ICs) are reported honestly.

Usage:
    $env:PYTHONPATH="."
    python tools/run_new_information_assessment.py
    python tools/run_new_information_assessment.py --instruments XAUUSD --test-frac 0.3
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Dict, List

import pandas as pd

from nexora_datahub.loader import load_bars, timeframe_minutes
from nexora_laboratory.opportunity_discovery.granularity import granularity_break
from nexora_laboratory.opportunity_discovery.horizon import pip_size_for
from nexora_laboratory.opportunity_discovery.information import assess_information

OUT = Path("reports/economic_opportunity_discovery")

# Candidate (timeframe, horizons) per instrument from STAGE 1-4 economics.
CANDIDATES: Dict[str, Dict[str, object]] = {
    "XAUUSD": {
        "symbol_for_pip": "XAUUSD",
        "timeframes": {
            "H1": {"file": "data/raw/XAUUSD_H1.csv", "horizons": [12, 24]},
            "H4": {"file": "data/raw/XAUUSD_H4.csv", "horizons": [4, 8, 12]},
            "D1": {"file": "data/raw/XAUUSD_D1.csv", "horizons": [1, 2]},
        },
    },
    "EURUSD": {
        "symbol_for_pip": "EURUSD",
        "timeframes": {
            "H1": {"file": "data/raw/EURUSD/EURUSD_H1_202001020000_202611062100.csv",
                   "horizons": [12, 24]},
            "H4": {"file": "data/raw/EURUSD/EURUSD_H4_202001020000_202611062000.csv",
                   "horizons": [4, 8, 12]},
        },
    },
}


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _intraday_segment(bars: pd.DataFrame, tf: str) -> pd.DataFrame:
    """Drop the daily-granularity prefix (EURUSD) -> homogeneous intraday segment."""
    brk = granularity_break(bars, timeframe_minutes(tf))
    return bars.iloc[brk["intraday_start_index"]:].reset_index(drop=True)


def main(argv=None) -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--instruments", default="XAUUSD,EURUSD")
    ap.add_argument("--test-frac", type=float, default=0.30)
    ap.add_argument("--alpha", type=float, default=0.05)
    ap.add_argument("--windows", default="5,20,60")
    args = ap.parse_args(argv)

    windows = tuple(int(x) for x in args.windows.split(","))
    wanted = [s.strip() for s in args.instruments.split(",") if s.strip()]

    OUT.mkdir(parents=True, exist_ok=True)
    result: Dict[str, object] = {
        "stage": 5,
        "note": ("STAGE 5 New Information Assessment. Model-free OOS Spearman IC on a "
                 "temporal train/test split, with BH-FDR + Bonferroni. NOT a model, "
                 "NOT a profitability claim; weak/negative ICs reported honestly. "
                 "XAUUSD OHLC comes from spot XAUUSD bars (no bars from XAUUSDm ticks)."),
        "test_frac": args.test_frac, "alpha": args.alpha, "windows": list(windows),
        "instruments": {},
    }
    inputs: Dict[str, str] = {}

    for inst in wanted:
        if inst not in CANDIDATES:
            continue
        spec = CANDIDATES[inst]
        pip = pip_size_for(spec["symbol_for_pip"])
        inst_res: Dict[str, object] = {"pip_size": pip, "timeframes": {}}
        for tf, cfg in spec["timeframes"].items():
            path = Path(cfg["file"])
            if not path.exists():
                inst_res["timeframes"][tf] = {"status": "missing", "file": str(path)}
                continue
            inputs[f"{inst}_{tf}"] = _sha256(path)
            bars = load_bars(path)
            seg = _intraday_segment(bars, tf)
            if len(seg) < 500:
                inst_res["timeframes"][tf] = {"status": "too_few_bars", "n": len(seg)}
                continue
            horizons: List[int] = cfg["horizons"]
            res = assess_information(seg, horizons=horizons, windows=windows,
                                     test_frac=args.test_frac, alpha=args.alpha)
            res["status"] = "ok"
            res["analysis_window"] = {"start": str(seg["ts"].iloc[0]),
                                     "end": str(seg["ts"].iloc[-1]),
                                     "rows_used": int(len(seg))}
            inst_res["timeframes"][tf] = res
        result["instruments"][inst] = inst_res

    out_json = OUT / "new_information_assessment.json"
    out_json.write_text(json.dumps(result, indent=2, default=str), encoding="utf-8")
    manifest = {"inputs": inputs, "outputs": {"new_information_assessment.json": _sha256(out_json)},
                "test_frac": args.test_frac, "alpha": args.alpha}
    (OUT / "new_information_assessment_manifest.json").write_text(
        json.dumps(manifest, indent=2), encoding="utf-8")

    # ----- console summary -----
    print("=" * 80)
    print("STAGE 5 — NEW INFORMATION ASSESSMENT (OOS Spearman IC)")
    print("=" * 80)
    for inst, r in result["instruments"].items():
        print(f"\n##### {inst} (pip={r['pip_size']})")
        for tf, tr in r["timeframes"].items():
            if tr.get("status") != "ok":
                print(f"  {tf}: {tr.get('status')} {tr.get('file','')}")
                continue
            mc = tr["multiple_comparison"]
            print(f"\n  {tf} [{tr['analysis_window']['start'][:10]}.."
                  f"{tr['analysis_window']['end'][:10]}] tests={tr['n_tests']} | "
                  f"BH survivors={mc['n_survive_bh']} Bonf={mc['n_survive_bonferroni']}")
            print(f"  {'feature':>12} {'h':>3} {'trainIC':>9} {'testIC':>9} "
                  f"{'test_p':>9} {'q_BH':>8} {'con':>4} {'BH*':>4}")
            for row in tr["ic_table"]:
                flag = "*" if row.get("test_reject_bh") else " "
                cons = "Y" if row.get("sign_consistent") else "n"
                tic = f"{row['test_ic']:.4f}" if row["test_ic"] is not None else "  -  "
                tric = f"{row['train_ic']:.4f}" if row["train_ic"] is not None else "  -  "
                tp = f"{row['test_p']:.2e}" if row["test_p"] is not None else "   -   "
                q = f"{row['test_q_bh']:.3f}" if row["test_q_bh"] is not None else "  -  "
                print(f"  {row['feature']:>12} {row['horizon']:>3} {tric:>9} "
                      f"{tic:>9} {tp:>9} {q:>8} {cons:>4} {flag:>4}")
    print("\nwrote", out_json)


if __name__ == "__main__":
    main()
