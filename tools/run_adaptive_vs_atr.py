"""Driver: run the FASE 2A ATR-vs-VolTargeted experiment on the frozen primary model.

Loads an existing trained PRIMARY classifier (never trains/writes it) and uses its
P(up) as the shared signal source for both barrier arms. Delegates all labelling,
cost and the walk-forward/verdict to nexora_laboratory.adaptive_experiment.

Usage:
    python tools/run_adaptive_vs_atr.py --data <csv> --model <joblib> --out <dir>
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import joblib
import numpy as np

from nexora_datahub.loader import load_bars
from nexora_vision.features import build_features
from nexora_laboratory.adaptive_experiment import ExperimentConfig, run_experiment, write_report


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", required=True)
    ap.add_argument("--model", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--side", type=int, default=1, choices=(1, -1))
    ap.add_argument("--folds", type=int, default=3)
    args = ap.parse_args()

    bars = load_bars(args.data)
    X = build_features(bars)

    bundle = joblib.load(args.model)
    model = bundle["model"]
    feats = bundle["features"]
    Xm = X[feats]
    ok = Xm.notna().all(axis=1).to_numpy()
    signal_p = np.full(len(bars), np.nan)
    if ok.any():
        signal_p[ok] = model.predict_proba(Xm[ok])[:, 1]

    cfg = ExperimentConfig(folds=args.folds, side=args.side,
                           horizon_signal=int(bundle.get("horizon", 2)))
    result = run_experiment(bars, Xm, signal_p, cfg)
    path = write_report(result, Path(args.out))

    print(json.dumps({
        "verdict": result.get("verdict"),
        "n_folds": result.get("n_folds"),
        "reasons": result.get("reasons"),
        "scenario_summary": result.get("scenario_summary"),
        "report": str(path),
    }, indent=2, default=str))


if __name__ == "__main__":
    main()
