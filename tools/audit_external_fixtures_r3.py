"""R3 — Fixture provenance audit.

Scans the external-intelligence test fixtures and classifies each data source by the
PIT evidence it provides, WITHOUT running anything or inventing timestamps:

  * REAL_SOURCE_EVIDENCE : carries explicit source-backed available_at/published_at.
  * SIMULATED_HISTORICAL : reconstructed/backtest data with some timestamp provenance
                           but not a direct vendor archive.
  * SYNTHETIC_FIXTURE    : mock/provenance=SYNTHETIC fixtures (never confirmatory).
  * UNVERIFIED           : no availability evidence at all (fail-closed).

This is a STATIC audit (grep-level) so it never mutates data. Output is printed + JSON.

Run:  python tools/audit_external_fixtures_r3.py
"""

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FIXTURE_DIRS = [
    ROOT / "tests" / "external_intelligence",
    ROOT / "tests",
]

# Files that contain external-intelligence fixtures or PIT tests.
TARGETS = [
    "tests/external_intelligence/conftest.py",
    "tests/external_intelligence/test_orchestrator.py",
    "tests/external_intelligence/test_repository.py",
    "tests/external_intelligence/test_intelligence.py",
    "tests/external_intelligence/test_integration_governance.py",
    "tests/test_external_pit_r2.py",
    "tests/test_asof_reconstruction_r3.py",
]


def _classify(text: str) -> dict:
    has_available = "available_at_utc" in text or "available_at=" in text
    has_published = "published_at_utc" in text or "published_ts" in text
    has_revision = "revision_as_of_utc" in text or "vintage" in text
    has_synthetic = ("SYNTHETIC" in text or "_synthetic" in text
                     or "is_synthetic=True" in text or "synthetic=True" in text)
    has_cutoff = "cutoff_ts" in text or "reconstruct_" in text

    if has_available and has_cutoff:
        tier = "REAL_SOURCE_EVIDENCE_OR_PIT_TEST"
    elif has_synthetic and not has_available:
        tier = "SYNTHETIC_FIXTURE"
    elif has_published and not has_available:
        tier = "UNVERIFIED_NO_AVAILABILITY"
    else:
        tier = "MIXED"
    return {
        "tier": tier,
        "has_available_at": has_available,
        "has_published_at": has_published,
        "has_revision_vintage": has_revision,
        "has_synthetic_marker": has_synthetic,
        "has_pit_cutoff_logic": has_cutoff,
    }


def main() -> dict:
    report = {}
    for rel in TARGETS:
        p = ROOT / rel
        if not p.exists():
            report[rel] = {"exists": False}
            continue
        text = p.read_text(encoding="utf-8", errors="ignore")
        report[rel] = {"exists": True, **_classify(text)}

    print(json.dumps(report, indent=2))
    return report


if __name__ == "__main__":
    main()
