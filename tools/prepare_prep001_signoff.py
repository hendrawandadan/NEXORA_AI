"""PREP-001 sign-off payload builder (DRY-RUN helper; no signing key, no production write).

Purpose: help the human owner assemble a correctly-bound, HMAC-signed sign-off payload
for PREP-001-T3-A (or T1-A) WITHOUT this tool ever: creating a key, writing to
``config/governance/``, running training, or dispatching.

Usage (owner action; reads key from env, writes ONLY to a path you pass with --out):
    setx NEXORA_GOVERNANCE_KEY "..."      # owner sets it; NOT done by this script
    python tools/prepare_prep001_signoff.py --root D:\\NEXORA_AI_v2 --target T3 \
        --candidate A --approver "Your Name" --decided-at 2026-01-01T00:00:00Z \
        --walk-forward R1 --out reports/retraining/prep001_ratification.DRAFT.json

IMPORTANT:
  * The ``config_hash`` (v1) is PATH-SENSITIVE: pass --root exactly as the runner will
    use it (absolute path recommended). A different root yields a different config_hash
    and the authorization gate will REJECT on config_hash_binding.
  * By default this writes a DRAFT to reports/. It will NOT write into config/governance/
    unless you pass --i-am-the-owner-and-want-to-write-production (still your signature).
"""
from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import os
import sys
from pathlib import Path

# Ensure the repository root is importable even when this file is executed
# directly (``python tools/prepare_prep001_signoff.py`` sets sys.path[0] to the
# ``tools`` directory, which would otherwise raise ModuleNotFoundError for
# ``nexora_audit``). Harmless when imported as a module.
_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from nexora_audit import governance
from nexora_audit.canonical_config import (
    build_prep001_proposal,
    canonical_config_hash,
    canonical_json,
)
from nexora_audit.configuration_freeze import (
    build_frozen_manifest,
    split_policy_version_for,
    target_definition_version_for,
)
from nexora_audit.timing_contract import build_timing_contract

TIMING_VALUES = {
    "decision_timestamp": "bar_t+1_open",
    "earliest_executable_timestamp": "bar_t+1_open",
    "execution_price_model": "open_price",
    "spread_usage": "deferred",
    "slippage_usage": "deferred",
    "cost_usage": "deferred",
}


def build_payload(root: Path, target_type: str, candidate: str, approver: str,
                  decided_at: str, walk_forward: str, note: str) -> dict:
    proposal = build_prep001_proposal(root)
    frozen = build_frozen_manifest(root)
    cfg = canonical_config_hash(proposal)
    horizon = int(proposal.job_identity["horizon"])
    # Target-aware versions: for T3 this is split-4d4a794c..., NOT the frozen
    # default split-27dd116e.... Using the default here would make a real T3
    # sign-off mismatch the gate's target-aware binding.
    tver = target_definition_version_for(target_type, horizon)
    sver = split_policy_version_for(target_type, horizon)
    return {
        "approver": approver,
        "decided_at": decided_at,
        "references": [
            "reports/retraining/execution_timing_contract.md",
            "reports/retraining/PREP001_BASELINE_IMPLEMENTATION_FINAL_AUDIT.md",
        ],
        "config_hash": cfg["hash"],
        "config_hash_complete": cfg["complete"],  # informational (v1 may be False)
        "feature_set_version": frozen.feature_version["id"],
        "target_definition_version": tver["id"],
        "split_policy_version": sver["id"],
        "timing_contract_hash": "PLACEHOLDER",
        "target": {"target_type": target_type, "target_hash": tver["hash"]},
        "timing_contract": {k: {"value": v} for k, v in TIMING_VALUES.items()},
        "walk_forward_reconciliation": walk_forward,
        "walk_forward_note": note,
        "experiment_configuration": {
            "candidate": candidate,
            "production_freeze": False,
            "note": "PREP-001-%s-%s first experiment; gross evaluation; costs deferred"
                    % (target_type, candidate),
        },
    }


def fill_ratified_timing_hash(root: Path, payload: dict, tmp_dir: Path) -> None:
    """Two-pass: compute the ratified timing hash from the draft payload."""
    tmp_rat = tmp_dir / "prep001_ratification.json"
    tmp_rat.write_text(json.dumps(payload), encoding="utf-8")
    # Load via governance on a scratch root that mirrors config/research.json
    scratch = tmp_dir / "_scratch"
    (scratch / "config" / "governance").mkdir(parents=True, exist_ok=True)
    (scratch / "config" / "research.json").write_text(
        (root / "config" / "research.json").read_text(encoding="utf-8"), encoding="utf-8")
    (scratch / "config" / "governance" / "prep001_ratification.json").write_text(
        json.dumps(payload), encoding="utf-8")
    rat = governance.load_ratification(scratch)
    ratified = governance.apply_timing_ratification(build_timing_contract(), rat)
    info = governance.ratified_contract_hash(ratified, rat)
    payload["timing_contract_hash"] = info["hash"]


def sign_payload(payload: dict, key: str) -> dict:
    body = {k: v for k, v in payload.items() if k != "integrity"}
    sig = hmac.new(key.encode("utf-8"), canonical_json(body).encode("utf-8"),
                   hashlib.sha256).hexdigest()
    signed = dict(payload)
    signed["integrity"] = {"mechanism": "hmac-sha256", "signature": sig}
    return signed


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Prepare (dry-run) a PREP-001 sign-off payload.")
    ap.add_argument("--root", required=True)
    ap.add_argument("--target", choices=["T1", "T3"], default="T3")
    ap.add_argument("--candidate", choices=["A", "B", "C"], default="A")
    ap.add_argument("--approver", required=True)
    ap.add_argument("--decided-at", required=True)
    ap.add_argument("--walk-forward", choices=["R1", "R2", "R3"], default="R1")
    ap.add_argument("--note", default="")
    ap.add_argument("--out", required=True, help="Where to write the signed payload.")
    ap.add_argument("--i-am-the-owner-and-want-to-write-production", action="store_true",
                    dest="allow_prod",
                    help="Permit writing into config/governance/ (owner only).")
    args = ap.parse_args(argv)

    key = os.environ.get("NEXORA_GOVERNANCE_KEY")
    if not key:
        print("ERROR: NEXORA_GOVERNANCE_KEY is not set. This helper never creates a key; "
              "the owner must set it. Aborting.", file=sys.stderr)
        return 2

    root = Path(args.root)
    payload = build_payload(root, args.target, args.candidate, args.approver,
                            args.decided_at, args.walk_forward, args.note)

    import tempfile
    with tempfile.TemporaryDirectory() as td:
        fill_ratified_timing_hash(root, payload, Path(td))

    signed = sign_payload(payload, key)

    out = Path(args.out)
    # Safety: refuse to write into production governance dir unless explicitly allowed.
    is_prod_governance = (out.name == "prep001_ratification.json"
                          and "governance" in out.parts and out.parts[:1] == ("config",))
    if is_prod_governance and not args.allow_prod:
        print("REFUSING to write into config/governance/ without "
              "--i-am-the-owner-and-want-to-write-production. Writing NOTHING.", file=sys.stderr)
        return 3

    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(signed, indent=2), encoding="utf-8")
    print("Wrote signed payload to", out)
    print("target=%s candidate=%s config_hash=%s timing_hash=%s"
          % (args.target, args.candidate, signed["config_hash"],
             signed["timing_contract_hash"]))
    print("NOTE: this is a file write only. No training/dispatch/promotion occurred.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
