"""Apply an APPROVED, signed reopening ratification to the governance registry (OWNER-ONLY).

This is the ONLY code path that changes the Price-Derived lane from ``SUSPENDED``
to an open status. It is deliberately paranoid and fails closed:

  * requires ``--i-am-the-owner-and-want-to-reopen-the-lane`` (explicit intent);
  * requires ``NEXORA_GOVERNANCE_KEY`` and verifies the HMAC on BOTH the proposal
    and the ratification;
  * requires the ratification ``decision`` == APPROVED and its ``proposal_hash`` to
    match the proposal;
  * re-validates the proposal structurally against the registry conditions/procedure;
  * by default is a DRY-RUN; only ``--write`` performs the status change, and it
    writes a *new timestamped backup* of the original registry first (never overwrites
    the evidence);
  * never trains, tunes, promotes, or enables live trading.

What changes on ``--write``:
  * ``status`` -> ``REOPENED_WITH_AUTHORIZATION``;
  * a ``reopening`` block is appended recording the proposal + ratification hashes,
    approver, decided_at, and the backup path (provenance);
  * ``suspended_candidates`` and ``background`` (historical failure evidence) are
    LEFT INTACT - reopening releases candidates from the active suspension but does
    NOT delete the failure history.

Usage (owner action):
    $env:NEXORA_GOVERNANCE_KEY = "<key that signed proposal + ratification>"
    python tools/apply_lane_reopening.py \
        --proposal reports/governance/reopening/proposal.json \
        --ratification reports/governance/reopening/ratification.json \
        --registry config/governance/price_derived_lane_suspension.json \
        --write --i-am-the-owner-and-want-to-reopen-the-lane
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from nexora_laboratory.governance import lane_reopening as lr


def now_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Apply an approved lane reopening (owner-only).")
    ap.add_argument("--proposal", required=True)
    ap.add_argument("--ratification", required=True)
    ap.add_argument("--registry", default=str(lr.lane_suspension.REGISTRY_PATH))
    ap.add_argument("--write", action="store_true",
                    help="Actually modify the registry (default is dry-run).")
    ap.add_argument("--i-am-the-owner-and-want-to-reopen-the-lane",
                    action="store_true", dest="owner_confirm")
    args = ap.parse_args(argv)

    registry_path = Path(args.registry)
    proposal = json.loads(Path(args.proposal).read_text(encoding="utf-8"))
    ratification = json.loads(Path(args.ratification).read_text(encoding="utf-8"))

    # 1. Owner intent.
    if not args.owner_confirm:
        print("REFUSING: pass --i-am-the-owner-and-want-to-reopen-the-lane.",
              file=sys.stderr)
        return 3

    # 2. Key + signatures.
    key = os.environ.get("NEXORA_GOVERNANCE_KEY")
    if not key:
        print("ERROR: NEXORA_GOVERNANCE_KEY not set (use the key that signed both files).",
              file=sys.stderr)
        return 2
    p_int = lr.verify_integrity(proposal, key)
    r_int = lr.verify_integrity(ratification, key)
    print("=== Signature verification ===")
    print("  proposal:    ", p_int["status"], "-", p_int.get("detail", ""))
    print("  ratification:", r_int["status"], "-", r_int.get("detail", ""))
    if p_int["status"] != "VERIFIED" or r_int["status"] != "VERIFIED":
        print("REFUSING: both proposal and ratification must verify with this key.",
              file=sys.stderr)
        return 4

    # 3. Proposal still valid against the registry.
    pv = lr.validate_proposal(proposal, registry_path)
    if not pv["valid"]:
        print("REFUSING: proposal structurally invalid:", file=sys.stderr)
        for p in pv["problems"]:
            print("  -", p, file=sys.stderr)
        return 5

    # 4. Ratification must APPROVE this exact proposal.
    rv = lr.validate_ratification(ratification, proposal, registry_path)
    if not rv["valid"]:
        print("REFUSING: ratification invalid:", file=sys.stderr)
        for p in rv["problems"]:
            print("  -", p, file=sys.stderr)
        return 5
    if str(ratification.get("decision") or "").upper() != "APPROVED":
        print("REFUSING: ratification decision is not APPROVED.", file=sys.stderr)
        return 6

    # 5. Current status.
    reg = lr.load_registry(registry_path)
    current = str(reg.get("status", "")).upper()
    print("\n=== Registry ===")
    print(f"  path: {registry_path}")
    print(f"  current status: {current}")
    if current != "SUSPENDED":
        print(f"NOTICE: status is already {current!r}; nothing to reopen.")
        return 0

    # Compose the updated registry (provenance only; evidence preserved).
    updated = json.loads(json.dumps(reg))  # deep copy
    backup_rel = (registry_path.parent / "backups" /
                  f"{registry_path.name}.{now_stamp()}.bak").as_posix()
    updated["status"] = lr.REGISTRY_OPEN_STATUS
    updated["reopening"] = {
        "decision_id": lr.REOPENING_RATIFICATION_ID,
        "approver": ratification.get("approver"),
        "decided_at": ratification.get("decided_at"),
        "proposal_hash": lr.proposal_hash(proposal),
        "ratification_note": ratification.get("note", ""),
        "applied_at": datetime.now(timezone.utc).replace(microsecond=0)
                             .isoformat().replace("+00:00", "Z"),
        "supersedes_status": current,
        "backup_of_original": backup_rel,
        "note": ("Reopened via explicit owner authorization. Historical failure "
                 "evidence and suspended_candidates are preserved for the record; "
                 "training/promotion remain gated by the PREP-001 authorization "
                 "procedure and walk-forward / net-of-cost evaluation."),
    }

    print("\n=== Proposed changed fields ===")
    print(f"  status: {current} -> {updated['status']}")
    print(f"  reopening.approver: {updated['reopening']['approver']}")
    print(f"  backup_of_original: {backup_rel}")

    if not args.write:
        print("\nDRY-RUN: no files changed. Re-run with --write to apply.")
        return 0

    # 6. Backup original (never overwrite; the backup IS the historical evidence).
    backup_abs = _REPO_ROOT / backup_rel
    backup_abs.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(registry_path, backup_abs)
    print(f"\nBacked up original registry -> {backup_abs}")

    # 7. Atomic write.
    tmp = registry_path.with_suffix(registry_path.suffix + ".incoming")
    tmp.write_text(json.dumps(updated, indent=2), encoding="utf-8")
    os.replace(tmp, registry_path)
    print(f"WROTE {registry_path} (status={updated['status']})")

    # 8. Post-check via the guard itself.
    from nexora_laboratory.governance import lane_suspension
    print(f"\nPost-change lane_status() = {lane_suspension.lane_status(registry_path)}")
    print("NOTE: no training/promotion occurred. Re-run the walk-forward + net-of-cost "
          "procedure before any dispatch.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
