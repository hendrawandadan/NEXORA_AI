"""Build (and sign) a lane REOPENING RATIFICATION record (DRY-RUN; no registry write).

The ratification is the human DECISION on a previously built reopening proposal.
It binds to the proposal by ``proposal_hash`` so it cannot be silently applied to a
different proposal. Signing requires ``NEXORA_GOVERNANCE_KEY``.

SAFETY: this tool writes ONLY to ``--out``. It never touches
``config/governance/`` and never changes the registry status.

Usage:
    python tools/ratify_lane_reopening.py \
        --proposal reports/governance/reopening/proposal.DRAFT.json \
        --approver "Your Name" --decided-at 2026-01-02T00:00:00Z \
        --decision APPROVED \
        --out reports/governance/reopening/ratification.DRAFT.json
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from nexora_laboratory.governance import lane_reopening as lr


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Build a (dry-run) reopening ratification.")
    ap.add_argument("--proposal", required=True)
    ap.add_argument("--approver", required=True)
    ap.add_argument("--decided-at", required=True)
    ap.add_argument("--decision", choices=["APPROVED", "REJECTED"], required=True)
    ap.add_argument("--note", default="")
    ap.add_argument("--out", required=True)
    args = ap.parse_args(argv)

    proposal = json.loads(Path(args.proposal).read_text(encoding="utf-8"))
    validation = lr.validate_proposal(proposal)
    if not validation["valid"]:
        print("REFUSING: proposal is structurally invalid:", file=sys.stderr)
        for p in validation["problems"]:
            print("  -", p, file=sys.stderr)
        return 2

    ratification = {
        "type": "REOPENING_RATIFICATION",
        "proposal_reference": str(Path(args.proposal)),
        "proposal_hash": lr.proposal_hash(proposal),
        "approver": args.approver,
        "decided_at": args.decided_at,
        "decision": args.decision,
        "note": args.note,
    }

    key = os.environ.get("NEXORA_GOVERNANCE_KEY")
    if key:
        ratification = lr.sign_payload(ratification, key)
        integrity = lr.verify_integrity(ratification, key)
    else:
        integrity = {"status": "UNVERIFIED",
                     "detail": "NEXORA_GOVERNANCE_KEY not set; wrote UNSIGNED ratification"}

    out = Path(args.out)
    if out.name == "price_derived_lane_suspension.json" and "governance" in out.parts:
        print("REFUSING: never write the governance registry from this tool.",
              file=sys.stderr)
        return 3
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(ratification, indent=2), encoding="utf-8")

    rv = lr.validate_ratification(ratification, proposal)
    print(f"Wrote ratification to {out}")
    print(f"  decision: {args.decision}")
    print(f"  integrity: {integrity['status']} ({integrity.get('detail','')})")
    print(f"  bound to proposal_hash: {ratification['proposal_hash']}")
    print(f"  structural valid: {rv['valid']}  problems={rv['problems']}")
    print("  NOTE: registry status is UNCHANGED. Apply via tools/apply_lane_reopening.py.")
    return 0 if rv["valid"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
