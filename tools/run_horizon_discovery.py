"""Read-only runner: STAGE 1 — Horizon Discovery (EURUSD M30 / H1 / H4).

No training, no config/model writes, no data modification. Writes ONLY under
reports/economic_opportunity_discovery/.

Steps
-----
1. Load EURUSD M30, H1, H4 bars via nexora_datahub.loader.load_bars.
2. Detect the daily-granularity prefix (granularity.granularity_break) and run
   horizon statistics on the HOMOGENEOUS intraday segment only.
3. Build 3 cost scenarios; baseline spread from the real <SPREAD> median-nonzero
   (points -> pips using the documented EURUSD 10 points/pip factor).
4. Per (timeframe, horizon) compute move distribution, move-to-cost, break-even
   accuracy (symmetric+barrier), net-expectancy map, by-year and by-regime
   stability — via opportunity_discovery.horizon.
5. Emit JSON + multiple-comparison ledger + SHA256 reproducibility manifest.

Usage:
    python tools/run_horizon_discovery.py
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pandas as pd

from nexora_datahub.loader import load_bars, timeframe_minutes
from nexora_laboratory.opportunity_discovery.granularity import granularity_break
from nexora_laboratory.opportunity_discovery.horizon import (
    Scenario, horizon_economics, pip_size_for,
)

OUT = Path("reports/economic_opportunity_discovery")

# Candidate (timeframe, horizons-in-bars) — RESEARCH CANDIDATES, not approved.
CANDIDATES = {
    "M30": [8, 16, 24, 48],
    "H1": [4, 8, 12, 24],
    "H4": [2, 4, 8, 12],
}

FILES = {
    "M30": "data/raw/EURUSD/EURUSD_M30_202001020000_202611062130.csv",
    "H1": "data/raw/EURUSD/EURUSD_H1_202001020000_202611062100.csv",
    "H4": "data/raw/EURUSD/EURUSD_H4_202001020000_202611062000.csv",
}

SYMBOL = "EURUSD"
POINTS_PER_PIP = 10.0  # 5-digit EURUSD: 10 broker points = 1 pip


def _sha256(path: str | Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _spread_summary(bars: pd.DataFrame) -> dict:
    """Honest spread summary. The <SPREAD> column is sparsely populated
    (86-93% zeros per TF), so a per-segment median is unreliable. We report:
      - full-history median-nonzero (matches prior audit: 3.0 pips),
      - the fraction of zero (data-reliability warning),
      - p90 nonzero (stress anchor).
    """
    s = pd.to_numeric(bars.get("spread"), errors="coerce").dropna()
    nz = s[s > 0]
    pips = lambda pts: float(pts) / POINTS_PER_PIP
    return {
        "n": int(len(s)),
        "pct_zero": round(float((s == 0).mean() * 100), 2) if len(s) else None,
        "median_nonzero_pips": pips(nz.median()) if len(nz) else float("nan"),
        "p90_nonzero_pips": pips(nz.quantile(0.90)) if len(nz) else float("nan"),
        "reliability_note": ("sparse <SPREAD> column; median-nonzero is an ESTIMATE "
                             "of spread, not a per-bar truth. True tick spread is "
                             "unavailable for EURUSD in this dataset."),
    }


def _scenarios(full_hist_median_pips: float) -> list:
    """3 scenarios anchored on the full-history median-nonzero spread.
    Baseline = that median (the prior-audit convention). Optimistic halves it;
    stress uses the p90 anchor. Slippage is an explicit ASSUMPTION (not in data).
    """
    base = full_hist_median_pips if (full_hist_median_pips and full_hist_median_pips > 0) else 3.0
    return [
        Scenario("optimistic", spread_pips=max(0.5, round(base * 0.5, 2)), slippage_pips=0.2),
        Scenario("baseline", spread_pips=round(base, 2), slippage_pips=0.2),
        Scenario("stress", spread_pips=round(base * 1.6, 2), slippage_pips=0.5),
    ]


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    pip = pip_size_for(SYMBOL)

    result = {
        "symbol": SYMBOL,
        "pip_size": pip,
        "points_per_pip": POINTS_PER_PIP,
        "note": ("STAGE 1 read-only horizon discovery. Net expectancy is a "
                 "conditional diagnostic vs required-hit, NOT a model result. "
                 "Forward moves are descriptive (realized) sizing statistics."),
        "timeframes": {},
        "multiple_comparison_ledger": [],
    }
    inputs = {}

    # Symbol-level spread baseline: use the FULL-history median-nonzero from the
    # most complete file (M30), applied CONSISTENTLY to all timeframes. Per-segment
    # medians are unreliable due to sparse <SPREAD> population, so we do not let
    # the timeframe change the assumed baseline cost.
    m30_full = load_bars(FILES["M30"])
    symbol_spread = _spread_summary(m30_full)
    base_pips = symbol_spread["median_nonzero_pips"]
    scen = _scenarios(base_pips)
    result["cost_baseline"] = {
        "spread_summary": symbol_spread,
        "applied_baseline_spread_pips": round(base_pips, 4) if base_pips == base_pips else None,
        "scenarios": {s.name: s.round_trip_pips for s in scen},
    }

    for tf, horizons in CANDIDATES.items():
        path = FILES[tf]
        inputs[tf] = {"path": path, "sha256": _sha256(path)}
        bars_full = load_bars(path)
        expected = timeframe_minutes(tf)
        brk = granularity_break(bars_full, expected)
        # Use homogeneous intraday segment only.
        bars = bars_full.iloc[brk["intraday_start_index"]:].reset_index(drop=True)

        econ = horizon_economics(bars, horizons, scen, pip)
        result["timeframes"][tf] = {
            "file": path,
            "granularity": brk,
            "scenarios": {s.name: s.round_trip_pips for s in scen},
            "horizons": horizons,
            "analysis_window": {"start": brk["intraday_first"], "end": brk["intraday_last"],
                                "rows_used": brk["segment_rows"]},
            **econ,
        }
        for item in econ["economics"]:
            result["multiple_comparison_ledger"].append(
                {"timeframe": tf, "horizon_bars": item["horizon_bars"],
                 "scenario": item["scenario"],
                 "move_to_cost_ratio": item["move_to_cost_ratio"]})

    # Reproducibility manifest.
    out_json = OUT / "horizon_discovery.json"
    out_json.write_text(json.dumps(result, indent=2, default=str), encoding="utf-8")
    manifest = {
        "inputs": inputs,
        "outputs": {"horizon_discovery.json": _sha256(out_json)},
        "symbol": SYMBOL,
        "candidates": CANDIDATES,
    }
    (OUT / "horizon_discovery_manifest.json").write_text(
        json.dumps(manifest, indent=2), encoding="utf-8")

    # Console summary.
    for tf in CANDIDATES:
        t = result["timeframes"][tf]
        g = t["granularity"]
        print(f"=== {tf} === (cost scenarios pips {t['scenarios']})")
        print(f"  granularity break: daily_prefix={g['has_daily_prefix']} "
              f"prefix_rows={g['prefix_rows']} intraday_from={g['intraday_first']}")
        for row in t["economics"]:
            if row["scenario"] != "baseline":
                continue
            print(f"  h={row['horizon_bars']:>2} med={row['median_move_pips']:>7} pip  "
                  f"ratio={row['move_to_cost_ratio']}  req_sym={row['required_acc_symmetric']}  "
                  f"req_bar={row['required_acc_barrier']}")
    print("wrote", out_json)


if __name__ == "__main__":
    main()
