"""Tool: dump the external-intelligence source registry + connector status.

Usage:
    python tools/external_intel_registry.py [--out reports/.../external_source_registry.json]

Read-only. Produces a JSON catalogue documenting every provider (tier, license, rate
limits, reliability, connector availability, ToS-safety) for human audit. Never performs
network I/O and never touches any database.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from nexora_research.external_intelligence import source_registry as sr
from nexora_research.external_intelligence import connectors as cx
from nexora_research.external_intelligence.config import DEFAULT_CONFIG


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Dump external-intel source registry")
    ap.add_argument("--out", default=str(REPO / "reports" / "external_intelligence" /
                                         "external_source_registry.json"))
    args = ap.parse_args(argv)

    payload = {
        "summary": sr.registry_summary(),
        "connector_status": cx.connector_status(DEFAULT_CONFIG),
        "providers": sr.registry_as_dicts(),
    }
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    print(f"wrote {out}")
    print(json.dumps(payload["summary"], indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
