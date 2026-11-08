import argparse
import json
from pathlib import Path

import pandas as pd

from nexora_core.config import ROOT, ensure_dirs
from nexora_evaluator.trading import evaluate_signal_file, summarize_consistency


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--signals-dir", default=str(ROOT / "signals"))
    ap.add_argument("--round-trip-cost-bps", type=float, default=0.0)
    ap.add_argument("--out-csv", default=str(ROOT / "reports" / "trading_metrics.csv"))
    ap.add_argument("--out-json", default=str(ROOT / "reports" / "trading_summary.json"))
    args = ap.parse_args()

    ensure_dirs()
    signals_dir = Path(args.signals_dir)
    files = sorted(signals_dir.rglob("*_signals.csv"))
    if not files:
        raise SystemExit(f"No signal files found in: {signals_dir}")

    rows = []
    failures = []
    for path in files:
        try:
            rows.append(evaluate_signal_file(path, round_trip_cost_bps=args.round_trip_cost_bps))
        except Exception as e:
            failures.append({"file": str(path), "error": str(e)})

    frame = pd.DataFrame(rows)
    out_csv = Path(args.out_csv)
    out_json = Path(args.out_json)
    out_csv.parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(out_csv, index=False)

    summary = {
        "signals_dir": str(signals_dir),
        "records": int(len(rows)),
        "failures": failures,
        "consistency": summarize_consistency(rows),
        "group_by_symbol": frame.groupby("symbol")[["expectancy", "win_rate", "profit_factor", "max_drawdown"]].median().to_dict("index") if len(frame) else {},
        "group_by_timeframe": frame.groupby("timeframe")[["expectancy", "win_rate", "profit_factor", "max_drawdown"]].median().to_dict("index") if len(frame) else {},
        "out_csv": str(out_csv),
    }
    out_json.write_text(json.dumps(summary, indent=2), encoding="utf-8")

    print(f"signals={len(files)} evaluated={len(rows)} failures={len(failures)}")
    print(f"metrics_csv={out_csv}")
    print(f"summary_json={out_json}")


if __name__ == "__main__":
    main()

