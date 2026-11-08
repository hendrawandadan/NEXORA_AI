"""Promote a VERIFIED PREP-001 sign-off DRAFT into config/governance/ (owner-only).

This does NOT sign anything. It copies an existing, already-signed draft into the
production governance path BYTE-FOR-BYTE (no re-serialization, so the HMAC stays
valid) after re-verifying the signature against the key in the environment. Then it
re-runs the read-only binding check on the REAL root.

Refuses to overwrite an existing prep001_ratification.json unless --overwrite is given.
Requires an explicit owner confirmation flag.

Usage:
    $env:NEXORA_GOVERNANCE_KEY = "<key that signed the draft>"
    .\\.venv\\Scripts\\python.exe tools\\promote_prep001_signoff.py ^
        --draft reports/retraining/prep001_ratification.DRAFT.json ^
        --root "D:\\NEXORA_AI_v2" --execution-id PREP-001 --target-type T3 --candidate A ^
        --i-am-the-owner-and-want-to-write-production
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

from nexora_audit.canonical_config import canonical_json


def _hmac_ok_bytes(raw_text: str, key: str) -> bool:
    payload = json.loads(raw_text)
    integ = payload.get("integrity") or {}
    declared = str(integ.get("signature") or "").strip()
    if not declared:
        return False
    body = {k: v for k, v in payload.items() if k != "integrity"}
    expected = hmac.new(key.encode("utf-8"), canonical_json(body).encode("utf-8"),
                        hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, declared)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Promote a verified sign-off draft to production.")
    ap.add_argument("--draft", required=True)
    ap.add_argument("--root", required=True)
    ap.add_argument("--execution-id", default="PREP-001")
    ap.add_argument("--target-type", choices=["T1", "T3"], required=True)
    ap.add_argument("--candidate", choices=["A", "B", "C"], default="A")
    ap.add_argument("--overwrite", action="store_true")
    ap.add_argument("--i-am-the-owner-and-want-to-write-production", action="store_true",
                    dest="allow_prod")
    args = ap.parse_args(argv)

    if not args.allow_prod:
        print("REFUSING: pass --i-am-the-owner-and-want-to-write-production to proceed.",
              file=sys.stderr)
        return 3

    key = os.environ.get("NEXORA_GOVERNANCE_KEY")
    if not key:
        print("ERROR: NEXORA_GOVERNANCE_KEY not set (use the key that signed the draft).",
              file=sys.stderr)
        return 2

    draft_path = Path(args.draft)
    raw_text = draft_path.read_text(encoding="utf-8")
    if not _hmac_ok_bytes(raw_text, key):
        print("REFUSING: draft signature does NOT verify with this key. Not writing.",
              file=sys.stderr)
        return 4

    root = Path(args.root).resolve()
    dest = root / "config" / "governance" / "prep001_ratification.json"
    if dest.exists() and not args.overwrite:
        print(f"REFUSING: {dest} already exists (use --overwrite to replace).", file=sys.stderr)
        return 5

    dest.parent.mkdir(parents=True, exist_ok=True)
    # Byte-for-byte copy: do NOT re-serialize (would invalidate the HMAC).
    dest.write_bytes(draft_path.read_bytes())
    print(f"WROTE {dest} (byte-for-byte from {draft_path.name})")

    # Re-verify on the REAL root using the production gate (read-only).
    print("\nRe-verifying on the real root...")
    import importlib
    sys.argv = [
        "verify_prep001_draft",
        "--draft", str(dest),
        "--root", str(root),
        "--execution-id", args.execution_id,
        "--target-type", args.target_type,
        "--candidate", args.candidate,
    ]
    verify = importlib.import_module("tools.verify_prep001_draft")
    return verify.main(sys.argv[1:])


if __name__ == "__main__":
    raise SystemExit(main())
