"""Read-only runner: FASE 2A upstream signal-quality audit (Audit A + Audit B).

No training, no config/model writes. Uses the SAME split as PREP-001 T3 (from
nexora_learning.pipeline.split_indices on the real feature/target mask) so the OOS
slice is identical to the model's test period.

Outputs:
    reports/fase2a/signal_quality_audit.json   (machine-readable)
    (Markdown summary is written by hand from the JSON; see docs.)

Usage:
    python tools/run_signal_quality_audit.py --data <csv> [--horizon 2]
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd

from nexora_datahub.loader import load_bars
from nexora_vision.features import build_features
from nexora_learning.pipeline import split_indices, purge_bars
from nexora_learning.targets import compute_target, build_target_mask, TARGET_T3
from nexora_laboratory.break_even import (
    CostModel,
    realized_move_sizes,
    feasibility_table,
    any_feasible,
)
from nexora_laboratory.feature_power import feature_power_oos


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", required=True)
    ap.add_argument("--horizon", type=int, default=2)
    ap.add_argument("--out", default="reports/fase2a/signal_quality_audit.json")
    args = ap.parse_args()

    bars = load_bars(args.data)
    X = build_features(bars)
    fwd, y = compute_target(bars, args.horizon, TARGET_T3)
    mask = build_target_mask(X, fwd, TARGET_T3, args.horizon)

    # Same split geometry as PREP-001 (train .6 / valid .2 / test remainder, purged).
    embargo = purge_bars(args.horizon, TARGET_T3, 24)
    tr, va, te = split_indices(mask, args.horizon, 0.6, 0.2, embargo, target_type=TARGET_T3)

    # ---------- Audit A: break-even horizon vs cost ----------
    horizons = [2, 3, 4, 6, 8, 12, 24, 48]
    moves = realized_move_sizes(bars, horizons)

    # Real observed spread (MT5 points -> pips: 10 points = 1 pip on 5-digit EURUSD).
    spread_pts = pd.to_numeric(bars.get("spread"), errors="coerce") if "spread" in bars else None
    spread_pips = None
    if spread_pts is not None:
        nz = spread_pts[spread_pts > 0]
        if len(nz):
            spread_pips = float(nz.median()) / 10.0

    # Observed accuracy at the trained horizon (h=2) from the existing report if present.
    observed = {}
    # NOTE: accuracy is target-specific; here we report the requirement and (if found)
    # the model's OOS accuracy at h=2 only, since that model exists.
    rep = Path("reports/t3/individual/EURUSD/M30/h2/report.json")
    if rep.is_file() and args.horizon == 2:
        r = json.loads(rep.read_text(encoding="utf-8"))
        observed[2] = float(r["test_metrics"]["accuracy"])

    # Cost scenarios: baseline uses the REAL spread; optim/stress bracket it.
    scenarios = {}
    if spread_pips:
        scenarios["baseline_real"] = CostModel(spread_pips=spread_pips, slippage_pips=0.2)
    scenarios["optimistic"] = CostModel(spread_pips=1.0, slippage_pips=0.2)
    scenarios["stress"] = CostModel(spread_pips=5.0, slippage_pips=0.5)  # p90 spread

    audit_a = {"real_spread_pips": spread_pips, "moves": moves.to_dict("records"),
               "observed_accuracy": {str(k): v for k, v in observed.items()},
               "scenarios": {}}
    for name, cost in scenarios.items():
        ft = feasibility_table(moves, cost, observed_accuracy=observed)
        audit_a["scenarios"][name] = {
            "cost": cost.as_dict(),
            "feasibility": ft.to_dict("records"),
            "summary": any_feasible(ft),
        }

    # ---------- Audit B: OOS feature power (test split only) ----------
    X_test = X.iloc[te].reset_index(drop=True)
    fwd_test = fwd[te]
    fp = feature_power_oos(X_test, fwd_test, horizon_bars=args.horizon,
                           iters=400, seed=42, min_ic_to_keep=0.02)
    audit_b = {
        "n_rows": fp["n_rows"], "block_len": fp["block_len"],
        "verdict": fp["verdict"], "n_usable": fp["n_usable"],
        "usable_features": fp["usable_features"],
        "top_features": [r.as_dict() for r in fp["features"][:10]],
        "test_period": {"start": str(bars["ts"].iloc[te[0]]), "end": str(bars["ts"].iloc[te[-1]])},
    }

    out = {
        "horizon": args.horizon,
        "target_type": TARGET_T3,
        "split": {"train": int(len(tr)), "valid": int(len(va)), "test": int(len(te)),
                  "test_start": str(bars["ts"].iloc[te[0]])},
        "audit_a_break_even": audit_a,
        "audit_b_feature_power": audit_b,
    }
    path = Path(args.out)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(out, indent=2, default=str), encoding="utf-8")

    print("AUDIT A (break-even):")
    print("  real spread (pips):", spread_pips)
    for name, sc in audit_a["scenarios"].items():
        print(f"  [{name}] cost={sc['cost']['round_trip_pips']}pips  any_feasible_sym={sc['summary']['any_feasible_symmetric']}")
        for row in sc["feasibility"]:
            obs = row.get("observed_accuracy")
            print(f"     h={row['horizon_bars']:>2} req_sym={row['required_acc_symmetric']:.3f} "
                  f"req_bar={row['required_acc_barrier']:.3f} obs={obs}")
    print("AUDIT B (feature power):", audit_b["verdict"], "| n_usable =", audit_b["n_usable"])
    for f in audit_b["top_features"][:5]:
        print(f"     {f['feature']:<16} IC={f['ic']:+.4f} CI=[{f['ic_ci_low']:+.4f},{f['ic_ci_high']:+.4f}] MI={f['mi_bits']:.5f}")
    print("wrote", path)


if __name__ == "__main__":
    main()
