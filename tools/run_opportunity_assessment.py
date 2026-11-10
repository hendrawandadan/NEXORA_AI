"""Read-only runner: STAGE 6 — Economic Opportunity Assessment (scoring).

Integrates STAGES 1-5 into a transparent opportunity score per
(instrument, timeframe, horizon). Crucially it recomputes movement-to-cost and
cost-drag using the REAL cost band from STAGE 3 (not the stale bar assumption in
STAGE 2), and uses the STRICT IC-stability score from STAGE 5 so regime-artifact
signals cannot masquerade as opportunity.

Read-only; writes ONLY under reports/economic_opportunity_discovery/.

Usage:
    $env:PYTHONPATH="."
    python tools/run_opportunity_assessment.py
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Dict, List, Optional

from nexora_laboratory.opportunity_discovery.scoring import (
    assess_candidate, rank_candidates,
)

OUT = Path("reports/economic_opportunity_discovery")
S1 = OUT / "horizon_discovery.json"
S2 = OUT / "instrument_discovery.json"
S3 = OUT / "transaction_cost_analysis.json"
S4 = OUT / "data_availability.json"
S5 = OUT / "new_information_assessment.json"

# STAGE-5 instrument -> source for median moves (STAGE 1 uses EURUSD; STAGE 2 has XAUUSD).
MOVE_SOURCE = {"XAUUSD": ("STAGE2", "XAUUSD"), "EURUSD": ("STAGE1", "EURUSD")}
# STAGE-5 instrument -> STAGE-3 cost instrument key.
COST_KEY = {"XAUUSD": "XAUUSD", "EURUSD": "EURUSD"}
# STAGE-4 readiness instrument key.
READY_KEY = {"XAUUSD": "XAUUSD", "EURUSD": "EURUSD"}


def _sha256(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for c in iter(lambda: f.read(1 << 20), b""):
            h.update(c)
    return h.hexdigest()


def _median_moves_stage2(stage2: dict, inst: str) -> Dict[str, Dict[int, float]]:
    """{tf: {horizon: median_move_pips}} using baseline scenario."""
    out: Dict[str, Dict[int, float]] = {}
    node = stage2.get("instruments", {}).get(inst, {})
    for tf, t in node.get("timeframes", {}).items():
        d = {}
        for r in t.get("economics", []):
            if r.get("scenario") == "baseline":
                d[int(r["horizon_bars"])] = float(r["median_move_pips"])
        if d:
            out[tf] = d
    return out


def _median_moves_stage1(stage1: dict) -> Dict[str, Dict[int, float]]:
    out: Dict[str, Dict[int, float]] = {}
    for tf, t in stage1.get("timeframes", {}).items():
        d = {}
        for r in t.get("economics", []):
            if r.get("scenario") == "baseline":
                d[int(r["horizon_bars"])] = float(r["median_move_pips"])
        if d:
            out[tf] = d
    return out


def main(argv=None) -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--cost-scenario", default="baseline",
                    choices=["optimistic", "baseline", "stress"])
    args = ap.parse_args(argv)

    OUT.mkdir(parents=True, exist_ok=True)
    for p in (S2, S3, S4, S5):
        if not p.exists():
            raise SystemExit(f"missing {p}; run earlier stages first")

    stage1 = json.loads(S1.read_text(encoding="utf-8")) if S1.exists() else {}
    stage2 = json.loads(S2.read_text(encoding="utf-8"))
    stage3 = json.loads(S3.read_text(encoding="utf-8"))
    stage4 = json.loads(S4.read_text(encoding="utf-8"))
    stage5 = json.loads(S5.read_text(encoding="utf-8"))

    moves2 = _median_moves_stage2(stage2, "XAUUSD")
    moves1 = _median_moves_stage1(stage1) if stage1 else {}

    candidates: List[Dict[str, object]] = []
    for inst, s5 in stage5.get("instruments", {}).items():
        src, src_key = MOVE_SOURCE.get(inst, ("STAGE2", inst))
        moves = moves2 if src == "STAGE2" else moves1
        cost_key = COST_KEY.get(inst, inst)
        real_cost = float(stage3["instruments"][cost_key]["scenarios"]
                          [args.cost_scenario]["round_trip_pips"])
        ready = float(stage4["instruments"][READY_KEY.get(inst, inst)]["readiness_score"])
        for tf, tr in s5.get("timeframes", {}).items():
            if tr.get("status") != "ok":
                continue
            ic_table = tr["ic_table"]
            for horizon in sorted({int(r["horizon"]) for r in ic_table}):
                med_move = moves.get(tf, {}).get(horizon)
                if med_move is None:
                    continue
                mtc = round(med_move / real_cost, 4) if real_cost > 0 else None
                drag = round(real_cost / med_move, 4) if med_move > 0 else None
                ic_rows = [r for r in ic_table if int(r["horizon"]) == horizon]
                cand = assess_candidate(
                    instrument=inst, timeframe=tf, horizon=horizon,
                    move_to_cost_ratio=mtc, cost_drag=drag,
                    data_readiness=ready, ic_rows=ic_rows,
                    extra={"real_cost_pips": real_cost,
                           "median_move_pips": med_move,
                           "cost_scenario": args.cost_scenario},
                )
                candidates.append(cand)

    ranked = rank_candidates(candidates)

    result = {
        "stage": 6,
        "note": ("STAGE 6 Economic Opportunity Assessment (scoring). Transparent "
                 "weighted score; NOT a profitability claim/backtest/signal. Movement-to-"
                 "cost and cost-drag use REAL STAGE-3 cost. Signal quality is STRICT "
                 "(penalises train~0 / sign-flip / regime-artifact), reflecting STAGE-5."),
        "cost_scenario": args.cost_scenario,
        "weights": {"economics": 0.25, "cost_burden": 0.20,
                    "data_readiness": 0.20, "signal_quality": 0.35},
        "n_candidates": len(ranked),
        "ranking": ranked,
        "summary": _summary(ranked),
    }
    out_json = OUT / "opportunity_assessment.json"
    out_json.write_text(json.dumps(result, indent=2, default=str), encoding="utf-8")

    manifest = {
        "inputs": {p.name: _sha256(p) for p in (S1, S2, S3, S4, S5) if p.exists()},
        "outputs": {"opportunity_assessment.json": _sha256(out_json)},
        "cost_scenario": args.cost_scenario,
    }
    (OUT / "opportunity_assessment_manifest.json").write_text(
        json.dumps(manifest, indent=2), encoding="utf-8")

    # console
    print("=" * 92)
    print(f"STAGE 6 — ECONOMIC OPPORTUNITY ASSESSMENT (cost={args.cost_scenario})")
    print("=" * 92)
    print(f"{'rank':>4} {'instrument':>9} {'tf':>4} {'h':>3} {'econ':>6} {'cost':>6} "
          f"{'data':>6} {'sig':>6} {'SCORE':>7} {'verdict':>20}")
    for i, c in enumerate(ranked, 1):
        comp = c["components"]
        print(f"{i:>4} {c['instrument']:>9} {c['timeframe']:>4} {c['horizon']:>3} "
              f"{comp['economics']:>6.3f} {comp['cost_burden']:>6.3f} "
              f"{comp['data_readiness']:>6.3f} {comp['signal_quality']:>6.3f} "
              f"{c['opportunity_score']:>7.4f} {c['verdict']:>20}")
    print("\nSUMMARY:", result["summary"])
    print("wrote", out_json)


def _summary(ranked: List[Dict[str, object]]) -> Dict[str, object]:
    buckets: Dict[str, List[str]] = {}
    for c in ranked:
        buckets.setdefault(c["verdict"], []).append(
            f"{c['instrument']} {c['timeframe']} h{c['horizon']}")
    return {k: {"count": len(v), "items": v} for k, v in buckets.items()}


if __name__ == "__main__":
    main()
