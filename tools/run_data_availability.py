"""Read-only runner: STAGE 4 — Data Availability & Quality.

Consolidates STAGE 2 (instrument_discovery.json) and STAGE 3
(transaction_cost_analysis.json) into a per-instrument availability & quality
profile with a transparent readiness score and explicit gaps. Read-only; writes
ONLY under reports/economic_opportunity_discovery/.

Usage:
    $env:PYTHONPATH="."
    python tools/run_data_availability.py
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from nexora_laboratory.opportunity_discovery.availability import build_availability

OUT = Path("reports/economic_opportunity_discovery")
STAGE2_JSON = OUT / "instrument_discovery.json"
STAGE3_JSON = OUT / "transaction_cost_analysis.json"


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    if not STAGE2_JSON.exists():
        raise SystemExit(f"missing {STAGE2_JSON}; run STAGE 2 first")
    stage2 = json.loads(STAGE2_JSON.read_text(encoding="utf-8"))
    stage3 = (json.loads(STAGE3_JSON.read_text(encoding="utf-8"))
              if STAGE3_JSON.exists() else None)

    result = {
        "stage": 4,
        "note": ("STAGE 4 Data Availability & Quality. Consolidates STAGE 2/3 into a "
                 "per-instrument readiness profile + explicit gaps. Readiness is a "
                 "transparent rule-based score, NOT a predictability/profit claim."),
        **build_availability(stage2, stage3),
    }

    out_json = OUT / "data_availability.json"
    out_json.write_text(json.dumps(result, indent=2, default=str), encoding="utf-8")
    manifest = {
        "inputs": {
            "instrument_discovery.json": _sha256(STAGE2_JSON),
            **({"transaction_cost_analysis.json": _sha256(STAGE3_JSON)}
               if STAGE3_JSON.exists() else {}),
        },
        "outputs": {"data_availability.json": _sha256(out_json)},
    }
    (OUT / "data_availability_manifest.json").write_text(
        json.dumps(manifest, indent=2), encoding="utf-8")

    # console summary
    print("=" * 78)
    print("STAGE 4 — DATA AVAILABILITY & QUALITY")
    print("=" * 78)
    for name in result["ranking"]:
        v = result["instruments"][name]
        print(f"\n### {name}  [{v['verdict']}]  readiness={v['readiness_score']}")
        print(f"  source={v['source']}  bars={v['has_bars']} tick={v['has_tick']}  "
              f"grade={v['quality_grade']}  years={v['years_history']}  "
              f"intraday_bars={v['intraday_bars']}")
        print(f"  cost source={v['tick_spread_source']}  commission={v['commission_status']}")
        comps = v["components"]
        print(f"  components: quality={comps['quality']} depth={comps['history_depth']} "
              f"cost={comps['cost_credibility']} coverage={comps['coverage']}")
        if v["gaps"]:
            for g in v["gaps"]:
                print(f"    GAP: {g}")
    print("\nSUMMARY:", result["summary"])
    print("wrote", out_json)


if __name__ == "__main__":
    main()
