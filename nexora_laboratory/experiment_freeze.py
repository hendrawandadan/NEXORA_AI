"""FASE 2A — Result freeze manifests (lock a completed experiment as official).

A freeze manifest binds an experiment's *result* to the exact code and artifact
hashes that produced it, plus the frozen configs, split policy and verdict. It is
deterministic and verifiable: ``verify_manifest`` recomputes every hash and fails
if any bound file changed.

This does NOT run any experiment and does NOT write to production data/model/DB.
It only records provenance so a result (e.g. R1) can be cited as official and later
re-checked. Verdict text is copied from the result artifact, never re-derived here.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List

FREEZE_HASH_VERSION = "nexora-experiment-freeze-v1"


def _sha256(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _canonical(payload) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _hash_payload(payload) -> str:
    return hashlib.sha256(_canonical(payload).encode("utf-8")).hexdigest()


def build_freeze_manifest(
    project_root: Path,
    *,
    experiment_id: str,
    result_path: Path,
    code_paths: List[Path],
    frozen_config: Dict,
    protocol: Dict,
    created_at: str | None = None,
) -> Dict:
    """Assemble a deterministic freeze manifest for a completed experiment.

    ``result_path`` is read to copy the verdict (never recomputed). ``code_paths``
    are every source file whose behaviour the result depends on; each is hashed so
    a later change is detectable. ``frozen_config``/``protocol`` are recorded verbatim
    so the reader sees exactly what was locked.
    """
    root = Path(project_root)
    result_path = Path(result_path)
    if not result_path.is_absolute():
        result_path = root / result_path
    result = json.loads(result_path.read_text(encoding="utf-8"))

    code_hashes = {}
    for p in code_paths:
        ap = Path(p)
        ap_abs = ap if ap.is_absolute() else root / ap
        code_hashes[str(Path(p))] = _sha256(ap_abs)

    body = {
        "hash_version": FREEZE_HASH_VERSION,
        "experiment_id": experiment_id,
        "created_at": created_at or datetime.now(timezone.utc).isoformat(),
        "result_file": str(result_path.relative_to(root) if result_path.is_relative_to(root) else result_path),
        "result_sha256": _sha256(result_path),
        "verdict": result.get("verdict"),
        "criteria": result.get("criteria"),
        "reasons": result.get("reasons"),
        "n_folds": result.get("n_folds"),
        "purge_bars": result.get("purge_bars"),
        "code_sha256": code_hashes,
        "frozen_config": frozen_config,
        "protocol": protocol,
    }
    body["manifest_hash"] = _hash_payload({k: v for k, v in body.items() if k != "created_at"})
    return body


def verify_manifest(project_root: Path, manifest: Dict) -> Dict:
    """Recompute and compare every bound hash; return a pass/fail report.

    Fails (ok=False) if the result file or any code file differs from the freeze.
    ``created_at`` is excluded from the manifest_hash so time-of-record does not
    affect verification.
    """
    root = Path(project_root)
    problems: List[str] = []

    # result file
    rf = Path(manifest["result_file"])
    rf_abs = rf if rf.is_absolute() else root / rf
    if not rf_abs.is_file():
        problems.append(f"missing result file: {manifest['result_file']}")
    elif _sha256(rf_abs) != manifest["result_sha256"]:
        problems.append(f"result file changed: {manifest['result_file']}")

    # code files
    for rel, expected in manifest["code_sha256"].items():
        ap = Path(rel)
        ap_abs = ap if ap.is_absolute() else root / ap
        if not ap_abs.is_file():
            problems.append(f"missing code file: {rel}")
        elif _sha256(ap_abs) != expected:
            problems.append(f"code file changed: {rel}")

    # manifest self-hash
    recomputed = _hash_payload({k: v for k, v in manifest.items()
                                if k not in ("created_at", "manifest_hash")})
    if recomputed != manifest["manifest_hash"]:
        problems.append("manifest_hash mismatch (manifest was edited)")

    return {"ok": len(problems) == 0, "problems": problems,
            "manifest_hash": manifest["manifest_hash"]}


def write_manifest(project_root: Path, manifest: Dict, out_path: Path) -> Path:
    root = Path(project_root)
    out = Path(out_path)
    out = out if out.is_absolute() else root / out
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8")
    return out
