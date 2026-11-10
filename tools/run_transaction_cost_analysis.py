"""Read-only runner: STAGE 3 — Transaction Cost Analysis.

Reads STAGE 2 instrument_discovery.json (real tick spread + bar economics) and
produces explicit, audited cost scenarios + cost-vs-move analysis. Read-only; writes
ONLY under reports/economic_opportunity_discovery/.

Cost model:
  spread from measured distribution (p50/p90/p99 for optimistic/baseline/stress)
  + explicit slippage assumption (per class) + commission NOT_AVAILABLE (0 band).
  Session costs use measured per-session median spread.

Usage:
    $env:PYTHONPATH="."
    python tools/run_transaction_cost_analysis.py
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Dict, List, Optional

from nexora_laboratory.opportunity_discovery.cost_model import (
    analyze_instrument_costs, MEASURED_SPREAD_PIPS,
)

OUT = Path("reports/economic_opportunity_discovery")
STAGE2_JSON = OUT / "instrument_discovery.json"


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _median_moves_from_stage2(stage2: dict, instrument_key: str) -> Dict[str, float]:
    """Extract baseline median move per horizon from STAGE 2 economics.

    Returns {f"{tf}:h{h}": median_move_pips}. For tick-only instruments (no bar
    economics) returns {}.
    """
    inst = stage2.get("instruments", {}).get(instrument_key)
    if not inst or inst.get("source") != "bars":
        return {}
    out: Dict[str, float] = {}
    for tf, t in inst.get("timeframes", {}).items():
        for row in t.get("economics", []):
            if row.get("scenario") != "baseline":
                continue
            key = f"{tf}:h{row['horizon_bars']}"
            out[key] = float(row["median_move_pips"])
    return out


def _map_tick_to_bar_key(instrument: str) -> Optional[str]:
    """Tick instruments may have a bar sibling with economics (XAUUSDm -> XAUUSD)."""
    m = {"XAUUSDm": "XAUUSD"}
    return m.get(instrument)


def main(argv=None) -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--commission-pips", type=float, default=0.0,
                    help="commission per round trip in pips (default 0 = NOT_AVAILABLE band)")
    args = ap.parse_args(argv)

    OUT.mkdir(parents=True, exist_ok=True)
    if not STAGE2_JSON.exists():
        raise SystemExit(f"missing {STAGE2_JSON}; run STAGE 2 first")
    stage2 = json.loads(STAGE2_JSON.read_text(encoding="utf-8"))

    result: Dict[str, object] = {
        "stage": 3,
        "note": ("STAGE 3 Transaction Cost Analysis. Spread from measured distribution; "
                 "slippage/commission are explicit assumptions (commission NOT_AVAILABLE). "
                 "Descriptive economics; NO profitability claim, NO model result."),
        "commission_pips_primary_band": args.commission_pips,
        "instruments": {},
    }

    for inst in MEASURED_SPREAD_PIPS:
        moves = _median_moves_from_stage2(stage2, inst)
        if not moves:
            bar_key = _map_tick_to_bar_key(inst)
            if bar_key:
                moves = _median_moves_from_stage2(stage2, bar_key)
        result["instruments"][inst] = analyze_instrument_costs(
            inst, horizons_with_median_move=moves or None,
            commission_pips=args.commission_pips,
        )

    out_json = OUT / "transaction_cost_analysis.json"
    out_json.write_text(json.dumps(result, indent=2, default=str), encoding="utf-8")
    manifest = {
        "inputs": {"instrument_discovery.json": _sha256(STAGE2_JSON)},
        "outputs": {"transaction_cost_analysis.json": _sha256(out_json)},
        "commission_pips": args.commission_pips,
    }
    (OUT / "transaction_cost_analysis_manifest.json").write_text(
        json.dumps(manifest, indent=2), encoding="utf-8")

    # ---- console summary ----
    print("=" * 78)
    print("STAGE 3 — TRANSACTION COST ANALYSIS")
    print("=" * 78)
    for inst, r in result["instruments"].items():
        print(f"\n### {inst}  (spread source: {r['spread_source']}, "
              f"commission: {r['commission_status']})")
        for name, sc in r["scenarios"].items():
            print(f"  {name:>10}: spread={sc['spread_pips']:>6} slip={sc['slippage_pips']} "
                  f"+comm={sc['commission_pips']} = RT {sc['round_trip_pips']:>7} pips")
        if r["by_session"]:
            print("  by session (RT pips):")
            for s, v in r["by_session"].items():
                print(f"    {s:>7}: spread={v['spread_pips']:>5} RT={v['round_trip_pips']:>6}")
            print(f"    cheapest={r['cheapest_session']}  most_expensive={r['most_expensive_session']}")
        if r["cost_drag_by_horizon"]:
            print("  cost drag (baseline RT / median move):")
            for h, sc in r["cost_drag_by_horizon"].items():
                b = sc["baseline"]
                print(f"    {h:>10}: RT={b['cost_pips']} move={b['median_move_pips']} "
                      f"drag={b['cost_fraction_of_move']} ratio={b['move_to_cost_ratio']} "
                      f"{'CROSSOVER' if b['crossover'] else ''}")
    print("\nwrote", out_json)


if __name__ == "__main__":
    main()
