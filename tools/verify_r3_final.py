"""R3 Tahap 5 — final verification (read-only).

Checks:
  * production DB hash unchanged,
  * research & external DB integrity + migration versions,
  * PRICE_DERIVED lane still SUSPENDED,
  * ATR baseline frozen artefact unchanged.
"""

import hashlib
import json
import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PROD = ROOT / "database" / "nexora_state.db"
RESEARCH = ROOT / "database" / "nexora_research.db"
EXTERNAL = ROOT / "database" / "nexora_external_intel.db"

EXPECTED_PROD_SHA = "7d945b4d7060b96a13d4c8dc81acba849b3e9984acefe1d12ab140ad06e79f43"


def sha(p):
    return hashlib.sha256(p.read_bytes()).hexdigest() if p.exists() else "MISSING"


def main():
    out = {}
    out["production_sha"] = sha(PROD)
    out["production_unchanged"] = out["production_sha"] == EXPECTED_PROD_SHA

    for label, db in (("research", RESEARCH), ("external", EXTERNAL)):
        if not db.exists():
            out[label] = "MISSING"
            continue
        c = sqlite3.connect(db)
        try:
            integ = c.execute("PRAGMA integrity_check").fetchone()[0]
            vers = [r[0] for r in c.execute("SELECT version FROM schema_migrations ORDER BY version")]
        finally:
            c.close()
        out[f"{label}_integrity"] = integ
        out[f"{label}_schema_versions"] = vers

    # PRICE_DERIVED lane suspension.
    try:
        from nexora_laboratory.governance.lane_suspension import is_suspended, lane_status
        out["price_derived_status"] = lane_status()
        out["price_derived_suspended"] = bool(is_suspended())
    except Exception as exc:  # pragma: no cover
        out["price_derived_suspended"] = f"ERROR: {exc}"

    # ATR baseline frozen artifact (if present): report its hash (must not be regenerated).
    atr_candidates = list((ROOT / "reports").rglob("*atr*baseline*")) + \
                      list((ROOT / "reports").rglob("*baseline*atr*"))
    out["atr_baseline_files"] = [str(p.relative_to(ROOT)) for p in atr_candidates]
    out["atr_baseline_hashes"] = {str(p.relative_to(ROOT)): sha(p) for p in atr_candidates}

    print(json.dumps(out, indent=2))
    return out


if __name__ == "__main__":
    main()
