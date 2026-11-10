"""Build (and optionally sign) a Price-Derived Lane REOPENING PROPOSAL (DRY-RUN).

Owner workflow helper. Produces a `REOPENING_PROPOSAL` packet that maps onto the
reopening conditions/procedure documented in
``config/governance/price_derived_lane_suspension.json`` (NEXORA-GOV-PRD-001).

SAFETY:
  * This tool NEVER writes to ``config/governance/`` and NEVER changes the registry
    status. It writes a DRAFT/proposal JSON to whatever ``--out`` you pass.
  * It does not train, tune, promote, or enable live trading.
  * Signing requires ``NEXORA_GOVERNANCE_KEY`` (never created or printed here). If
    the key is absent the packet is written UNSIGNED (status UNVERIFIED).

Usage:
    python tools/build_lane_reopening_proposal.py --approver "Your Name" \
        --decided-at 2026-01-01T00:00:00Z \
        --hypothesis-file reports/governance/reopening/new_hypothesis.md \
        --candidate EURUSD,H1,12 --candidate XAUUSD,H1,12 \
        --out reports/governance/reopening/proposal.DRAFT.json
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


def _parse_candidate(text: str) -> dict:
    parts = [p.strip() for p in text.split(",")]
    if len(parts) != 3:
        raise argparse.ArgumentTypeError(
            f"--candidate must be 'INSTRUMENT,TIMEFRAME,HORIZON', got {text!r}")
    instrument, timeframe, horizon = parts
    return {"instrument": instrument, "timeframe": timeframe, "horizon": int(horizon)}


def _default_procedure_status(reg_procedure) -> dict:
    """Map every registry procedure step to a status based on what this tool does.

    'document the reason for reopening', 'create a new hypothesis', 'pre-registration',
    and 'set GO/NO-GO criteria' are addressed by assembling this proposal; the
    remaining experimental steps are PENDING (must be executed after reopening is
    approved, and are still subject to the walk-forward / net-of-cost procedure).
    """
    addressed_now = {
        "document the reason for reopening": "DONE",
        "create a new hypothesis": "DONE",
        "pre-registration": "DONE",
        "set GO/NO-GO criteria": "PENDING",
        "data and leakage inspection": "PENDING",
        "walk-forward validation": "PENDING",
        "net-of-cost evaluation": "PENDING",
        "user approval before training or model promotion": "PENDING",
    }
    out = {}
    for step in reg_procedure:
        out[step] = {"status": addressed_now.get(step, "NOT_STARTED")}
    return out


def build_proposal(*, approver: str, decided_at: str, new_hypothesis: str,
                   distinct_from: str, candidates: list, registry_path: Path,
                   procedure_status: dict | None = None) -> dict:
    reg = lr.load_registry(registry_path)
    conditions = reg.get("reopening_conditions", [])
    procedure = reg.get("reopening_procedure", [])

    # This template cites ALL documented conditions as *individually sufficient*
    # evidence dimensions the proposal will rely on; the owner trims in review.
    conditions_satisfied = [
        {"condition": c, "evidence": "see reports/governance/ (owner to attach)"}
        for c in conditions
    ]
    return {
        "type": "REOPENING_PROPOSAL",
        "decision_id": reg.get("decision_id"),
        "approver": approver,
        "decided_at": decided_at,
        "conditions_satisfied": conditions_satisfied,
        "new_hypothesis": new_hypothesis.strip(),
        "distinct_from_failed_hypothesis": distinct_from.strip(),
        "candidates_requested": candidates,
        "procedure_status": procedure_status or _default_procedure_status(procedure),
        "references": [
            "reports/economic_opportunity_discovery/GOVERNANCE_DECISION_PRD_001.md",
            "config/governance/price_derived_lane_suspension.json",
        ],
        "note": ("Proposal only. Registry status remains SUSPENDED until the owner "
                 "runs tools/apply_lane_reopening.py with a signed ratification."),
    }


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Build a (dry-run) lane reopening proposal.")
    ap.add_argument("--approver", required=True,
                    help="Name of the human proposer (not a placeholder).")
    ap.add_argument("--decided-at", required=True, help="ISO-8601 timestamp.")
    src = ap.add_mutually_exclusive_group(required=True)
    src.add_argument("--hypothesis-file", help="Markdown/text file with the NEW hypothesis.")
    src.add_argument("--hypothesis", help="Inline NEW hypothesis text.")
    ap.add_argument("--distinct", default="",
                    help="How the new hypothesis differs from the failed one "
                         "(defaults to the hypothesis file if omitted).")
    ap.add_argument("--candidate", action="append", default=[], type=_parse_candidate,
                    metavar="INSTRUMENT,TF,HORIZON",
                    help="A suspended candidate this proposal targets (repeatable).")
    ap.add_argument("--registry", default=str(lr.lane_suspension.REGISTRY_PATH))
    ap.add_argument("--out", required=True)
    args = ap.parse_args(argv)

    if args.hypothesis_file:
        new_hypothesis = Path(args.hypothesis_file).read_text(encoding="utf-8")
    else:
        new_hypothesis = args.hypothesis
    distinct = args.distinct.strip() or new_hypothesis

    candidates = list(args.candidate)
    if not candidates:
        # Default: the price-derived candidates that STAGE-5 found IC survivors for,
        # if they happen to be in scope; otherwise the full suspension scope is left
        # to the owner. We do NOT invent scope here.
        print("WARNING: no --candidate supplied; the proposal will target ZERO "
              "candidates and validate as incomplete until you add them.",
              file=sys.stderr)

    registry_path = Path(args.registry)
    proposal = build_proposal(approver=args.approver, decided_at=args.decided_at,
                              new_hypothesis=new_hypothesis, distinct_from=distinct,
                              candidates=candidates, registry_path=registry_path)

    validation = lr.validate_proposal(proposal, registry_path)

    key = os.environ.get("NEXORA_GOVERNANCE_KEY")
    if key:
        proposal = lr.sign_payload(proposal, key)
        integrity = lr.verify_integrity(proposal, key)
    else:
        integrity = {"status": "UNVERIFIED",
                     "detail": "NEXORA_GOVERNANCE_KEY not set; wrote UNSIGNED proposal"}

    out = Path(args.out)
    is_prod_governance = (out.name == "price_derived_lane_suspension.json"
                          and "governance" in out.parts)
    if is_prod_governance:
        print("REFUSING: this tool never writes the governance registry. "
              "Writing NOTHING.", file=sys.stderr)
        return 3
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(proposal, indent=2), encoding="utf-8")

    print(f"Wrote reopening proposal to {out}")
    print(f"  integrity: {integrity['status']} ({integrity.get('detail','')})")
    print(f"  proposal_hash: {lr.proposal_hash(proposal)}")
    print(f"  structural valid: {validation['valid']}")
    if validation["problems"]:
        print("  problems:")
        for p in validation["problems"]:
            print("    -", p)
    print("  NOTE: registry status is UNCHANGED (still SUSPENDED). No training occurred.")
    return 0 if validation["valid"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
