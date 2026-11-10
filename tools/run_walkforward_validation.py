"""Read-only runner: Walk-forward multi-split validation of STAGE-6 candidates.

Re-tests the IC *stability* of the features that STAGE 5/6 flagged, using EXPANDING-
window walk-forward with multiple out-of-sample folds (with purging at fold boundaries).
A feature is "stable" only if its IC is sign-consistent, individually significant in a
majority of folds, non-dominated by one fold, and of non-trivial magnitude.

This does NOT train a model and makes NO profitability claim. If the walk-forward is
not stable, the honest conclusion is to CLOSE the line.

Targets (from STAGE 6 RESEARCH_CANDIDATE + the driving features):
  XAUUSD D1 h2   -> driving features ret_5, zclose_5 (STAGE-6 evidence)
  XAUUSD D1 h1   -> ret_5, zclose_5
  EURUSD H4 h12  -> zclose_60, ret_60
plus control features at the same horizons (rng_20, rng_60, vol_60) so a failure is
visible rather than cherry-picked.

Usage:
    $env:PYTHONPATH="."
    python tools/run_walkforward_validation.py
    python tools/run_walkforward_validation.py --folds 6
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
from nexora_laboratory.opportunity_discovery.walkforward import assess_walkforward

OUT = Path("reports/economic_opportunity_discovery")

# (instrument, timeframe, file, [horizons], [features]) — candidates + controls.
JOBS = [
    ("XAUUSD", "D1", "data/raw/XAUUSD_D1.csv", [1, 2],
     ["ret_5", "zclose_5", "rng_20", "rng_60"]),
    ("XAUUSD", "H4", "data/raw/XAUUSD_H4.csv", [8, 12],
     ["rng_20", "rng_60", "vol_60", "ret_60"]),
    ("EURUSD", "H4", "data/raw/EURUSD/EURUSD_H4_202001020000_202611062000.csv", [12],
     ["zclose_60", "ret_60", "vol_60", "rng_60"]),
]


def _sha256(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for c in iter(lambda: f.read(1 << 20), b""):
            h.update(c)
    return h.hexdigest()


def _seg(bars: pd.DataFrame, tf: str) -> pd.DataFrame:
    brk = granularity_break(bars, timeframe_minutes(tf))
    return bars.iloc[brk["intraday_start_index"]:].reset_index(drop=True)


def main(argv=None) -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--folds", type=int, default=6)
    ap.add_argument("--alpha", type=float, default=0.05)
    ap.add_argument("--windows", default="5,20,60")
    args = ap.parse_args(argv)
    windows = tuple(int(x) for x in args.windows.split(","))

    OUT.mkdir(parents=True, exist_ok=True)
    result: Dict[str, object] = {
        "study": "Walk-forward multi-split validation (STAGE 6 candidates)",
        "note": ("Read-only. Multi-fold expanding-window OOS IC with purging. Stability "
                 "requires sign-consistency, majority significance, non-dominance and "
                 "non-trivial magnitude. NOT a model, NOT a profit claim."),
        "n_folds": args.folds, "alpha": args.alpha, "windows": list(windows),
        "jobs": {},
    }
    inputs: Dict[str, str] = {}

    for inst, tf, path, horizons, feats in JOBS:
        p = Path(path)
        if not p.exists():
            result["jobs"][f"{inst}_{tf}"] = {"status": "missing", "file": path}
            continue
        inputs[f"{inst}_{tf}"] = _sha256(p)
        bars = _seg(load_bars(p), tf)
        res = assess_walkforward(bars, features_to_test=feats, horizons=horizons,
                                 windows=windows, n_folds=args.folds, alpha=args.alpha)
        res["status"] = "ok"
        res["window"] = {"start": str(bars["ts"].iloc[0]), "end": str(bars["ts"].iloc[-1]),
                        "rows": int(len(bars))}
        result["jobs"][f"{inst}_{tf}"] = res

    out_json = OUT / "walkforward_validation.json"
    out_json.write_text(json.dumps(result, indent=2, default=str), encoding="utf-8")
    manifest = {"inputs": inputs,
                "outputs": {"walkforward_validation.json": _sha256(out_json)},
                "n_folds": args.folds, "alpha": args.alpha}
    (OUT / "walkforward_validation_manifest.json").write_text(
        json.dumps(manifest, indent=2), encoding="utf-8")

    # console
    print("=" * 88)
    print(f"WALK-FORWARD MULTI-SPLIT VALIDATION (folds={args.folds}, alpha={args.alpha})")
    print("=" * 88)
    total = stable = 0
    for key, r in result["jobs"].items():
        if r.get("status") != "ok":
            print(f"{key}: {r.get('status')}")
            continue
        print(f"\n### {key} [{r['window']['start'][:10]}..{r['window']['end'][:10]}] rows={r['window']['rows']}")
        print(f"    stable {r['n_stable']}/{r['n_tests']}")
        for row in r["results"]:
            s = "STABLE" if row["stable"] else "unstable"
            ics = ",".join("na" if v is None else f"{v:+.3f}" for v in row["fold_ics"])
            print(f"    {row['feature']:>10} h{row['horizon']:>2}: {s:>8} | "
                  f"sign {row['sign_match']}/{row['n_folds_valid']} "
                  f"sig {row['frac_folds_significant']:.2f} dom {row['max_fold_dominance']:.2f} "
                  f"med {row['median_ic']:+.4f} | folds[{ics}]")
            total += 1
            stable += 1 if row["stable"] else 0
    result["summary"] = {"total_tests": total, "stable": stable,
                        "unstable": total - stable}
    out_json.write_text(json.dumps(result, indent=2, default=str), encoding="utf-8")
    print(f"\nSUMMARY: stable {stable}/{total} feature×horizon tests survived walk-forward.")
    print("wrote", out_json)


if __name__ == "__main__":
    main()
