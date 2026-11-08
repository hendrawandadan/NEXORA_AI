"""Read-only verification of a PREP-001 sign-off DRAFT (does NOT sign, write, or train).

Owner workflow helper. Given a DRAFT payload and the key used to sign it, this:

  * Recomputes the HMAC over canonical_json(payload without 'integrity') and compares
    it (constant time) to integrity.signature.
  * Runs the REAL ``authorize_execution`` binding checks against the draft's values,
    evaluated on the SAME ``--root`` the draft was built for (so config_hash matches).
    The draft is injected as an in-memory ratification object; nothing is written to
    config/governance/ and no training occurs.
  * The execution row is built exactly like the runner does: target_type, candidate,
    and TARGET-AWARE version ids (feature/target/split) are threaded in.

Usage:
    $env:NEXORA_GOVERNANCE_KEY = "<key used to build the draft>"
    .\\.venv\\Scripts\\python.exe tools\\verify_prep001_draft.py ^
        --draft reports/retraining/prep001_ratification.DRAFT.json ^
        --root "D:\\NEXORA_AI_v2" --execution-id PREP-001 --target-type T3 --candidate A

Exit code 0 = all binding checks pass. Non-zero = a real mismatch.
"""
from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import os
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from nexora_audit import governance
from nexora_audit import authorization as A
from nexora_audit.canonical_config import canonical_json
from nexora_audit.configuration_freeze import (
    feature_set_version,
    split_policy_version_for,
    target_definition_version_for,
)


def _hmac_ok(payload: dict, key: str) -> bool:
    integ = payload.get("integrity") or {}
    declared = str(integ.get("signature") or "").strip()
    if not declared:
        return False
    body = {k: v for k, v in payload.items() if k != "integrity"}
    expected = hmac.new(key.encode("utf-8"), canonical_json(body).encode("utf-8"),
                        hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, declared)


def _ratification_from_payload(root: Path, payload: dict) -> "governance.Ratification":
    """Validate a sign-off payload in-memory WITHOUT writing to config/governance/."""
    return governance.load_ratification(root, payload=payload)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Verify a PREP-001 sign-off draft (read-only).")
    ap.add_argument("--draft", required=True)
    ap.add_argument("--root", required=True)
    ap.add_argument("--execution-id", default="PREP-001")
    ap.add_argument("--target-type", choices=["T1", "T3"], required=True)
    ap.add_argument("--candidate", choices=["A", "B", "C"], default="A")
    args = ap.parse_args(argv)

    key = os.environ.get("NEXORA_GOVERNANCE_KEY")
    if not key:
        print("ERROR: NEXORA_GOVERNANCE_KEY not set (use the SAME key that signed the draft).",
              file=sys.stderr)
        return 2

    payload = json.loads(Path(args.draft).read_text(encoding="utf-8"))

    print("=== HMAC integrity ===")
    ok = _hmac_ok(payload, key)
    print("  signature:", "VERIFIED" if ok else "INVALID/MISMATCH")
    if not ok:
        print("  -> The key does not match the one used to build the draft, OR the payload "
              "was edited. Re-generate the draft with this key.", file=sys.stderr)
        return 4

    # Evaluate against the SAME root the draft was built for (config_hash matches).
    root = Path(args.root).resolve()
    rat = _ratification_from_payload(root, payload)

    print("\n=== Structural validity ===")
    print("  valid:", rat.valid if rat else False, "problems:", rat.problems if rat else "-")

    # Build the row EXACTLY like the runner: target-aware version ids + candidate.
    horizon = int(payload.get("target", {}).get("horizon", 2)) if isinstance(
        payload.get("target"), dict) and payload.get("target", {}).get("horizon") else 2
    tv = target_definition_version_for(args.target_type, horizon)
    sv = split_policy_version_for(args.target_type, horizon)
    row = {
        "execution_id": args.execution_id,
        "batch": "Batch 1",
        "scope": "individual",
        "symbol": "EURUSD",
        "timeframe": "M30",
        "horizon": "2",
        "target_type": args.target_type,
        "experiment_candidate": args.candidate,
        "feature_set_version": feature_set_version()["id"],
        "target_definition_version": tv["id"],
        "split_policy_version": sv["id"],
    }

    decision = A.authorize_execution(
        execution_row=row,
        project_root=root,
        batch_name="Batch 1",
        requested_execution_ids={args.execution_id},
        ratification=rat,
        claim_probe_result={
            "single_active_attempt_enforced": True,
            "lifecycle_synchronized": True,
            "running_job_claim_rejected": True,
        },
        recovery_probe_result={"no_duplicate_active_run": True,
                               "promoted_terminal_preserved": True},
    )
    print("\n=== Binding checks (real root) ===")
    binding_fails = []
    for c in decision.checks:
        status = "PASS" if c.passed else "FAIL"
        print(f"  [{status}] {c.code}: {c.detail[:110]}")
        if not c.passed:
            binding_fails.append(c.code)

    print("\n  split bound:", decision.bindings.get("split_policy_version"))
    print("  versions source:", decision.bindings.get("contract_versions_source"))
    print("  config_hash match:", decision.bindings.get("config_hash_signed")
          == decision.bindings.get("config_hash_live"))
    print("  authorized:", decision.authorized)

    if binding_fails:
        print("\nRESULT: FAILURES ->", binding_fails, file=sys.stderr)
        return 5
    print("\nRESULT: all checks PASS -> authorized=True.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
