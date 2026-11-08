"""Human ratification records for PREP-001 (governance layer).

This module is the ONLY legitimate way a contract/freeze/experiment decision is
marked as ratified. It reads an explicit, human-authored sign-off file
(``config/governance/prep001_ratification.json``) and applies it. If the file is
absent, malformed, incomplete, or unsigned, nothing is ratified and the gates
stay blocked.

The audit tooling never invents a ratification. A human must:
  * name themselves as approver,
  * set a decision time,
  * record each timing NEW_DESIGN field's chosen value,
  * choose the walk-forward reconciliation option (R1/R2/R3),
  * choose the experiment candidate (A/B/C) — as an *experiment* config only.

This file only READS decisions and re-emits derived, hash-addressed state. It does
not touch the production database, dataset, model, or backup.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

GOVERNANCE_DIR = Path("config") / "governance"
RATIFICATION_FILE = GOVERNANCE_DIR / "prep001_ratification.json"

_ALLOWED_WF_OPTIONS = {"R1", "R2", "R3"}
_ALLOWED_CANDIDATES = {"A", "B", "C"}

# Fields the human MUST explicitly decide for the timing contract to be ratified.
# execution_price_model is included because a cost-aware backtest cannot proceed
# without a stated hypothetical execution price.
REQUIRED_TIMING_DECISIONS = (
    "decision_timestamp",
    "earliest_executable_timestamp",
    "execution_price_model",
    "spread_usage",
    "slippage_usage",
    "cost_usage",
)


@dataclass
class Ratification:
    raw: Dict[str, Any]
    path: Path
    valid: bool
    problems: List[str]

    def get(self, key: str, default: Any = None) -> Any:
        return self.raw.get(key, default)


class RatificationError(ValueError):
    pass


def load_ratification(project_root: Path, payload: Optional[Dict[str, Any]] = None) -> Optional[Ratification]:
    """Load and validate the human sign-off file. Returns None if absent.

    ``payload`` (optional) lets a caller validate an in-memory sign-off dict
    instead of reading ``<project_root>/config/governance/...``. This is used by
    read-only verification helpers to check a DRAFT without writing it into the
    production governance directory. The ``path`` on the returned object still
    points at the canonical production path for provenance.
    """
    project_root = Path(project_root)
    path = project_root / RATIFICATION_FILE
    if payload is None:
        if not path.is_file():
            return None
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except Exception as exc:  # malformed json
            return Ratification({}, path, valid=False, problems=[f"unreadable json: {exc}"])
    else:
        raw = payload
    problems: List[str] = []
    if not isinstance(raw, dict):
        return Ratification({}, path, valid=False, problems=["root is not an object"])

    approver = str(raw.get("approver") or "").strip()
    if not approver:
        problems.append("missing approver")
    decided_at = str(raw.get("decided_at") or "").strip()
    if not decided_at:
        problems.append("missing decided_at")

    timing = raw.get("timing_contract")
    if not isinstance(timing, dict):
        problems.append("missing timing_contract object")
        timing = {}
    for field in REQUIRED_TIMING_DECISIONS:
        entry = timing.get(field)
        if not isinstance(entry, dict) or not str(entry.get("value") or "").strip():
            problems.append(f"timing_contract.{field}.value missing")

    wf = raw.get("walk_forward_reconciliation")
    if wf not in _ALLOWED_WF_OPTIONS:
        problems.append(f"walk_forward_reconciliation must be one of {sorted(_ALLOWED_WF_OPTIONS)}")

    exp = raw.get("experiment_configuration")
    if not isinstance(exp, dict):
        problems.append("missing experiment_configuration object")
        exp = {}
    if exp.get("candidate") not in _ALLOWED_CANDIDATES:
        problems.append(f"experiment_configuration.candidate must be one of {sorted(_ALLOWED_CANDIDATES)}")
    if exp.get("production_freeze") not in (False, None):
        # Guard: experiments must not be marked as production freeze.
        if exp.get("production_freeze") is True:
            problems.append("experiment_configuration.production_freeze must not be true (experiments are not production freeze)")

    return Ratification(raw, path, valid=not problems, problems=problems)


def apply_timing_ratification(contract, ratification: Ratification):
    """Return a NEW TimingContract with the human-chosen values applied.

    Provenance: only fields present in the signed file are overridden. The human
    value replaces the proposal value; the field status stays NEW_DESIGN (it is a
    decision, not a data-derived fact) but the contract is marked ratified.
    """
    if not ratification.valid:
        raise RatificationError(f"ratification invalid: {ratification.problems}")
    timing = ratification.raw["timing_contract"]
    # Rebuild with overrides.
    from .timing_contract import TimingContract, TimingField  # local import to avoid cycle

    fields: List[TimingField] = []
    for f in contract.fields:
        value = f.value
        evidence = f.evidence
        if f.name in timing:
            entry = timing[f.name]
            value = entry["value"]
            note = entry.get("note", "")
            evidence = f"{evidence} | RATIFIED by {ratification.get('approver')} at {ratification.get('decided_at')}: {value}"
            if note:
                evidence += f" ({note})"
        fields.append(TimingField(f.name, f.definition, f.status, evidence, value))
    return TimingContract(fields=fields)


def ratified_contract_hash(contract, ratification: Ratification) -> Dict[str, Any]:
    """Hash of the *ratified* contract, including approver/decision time."""
    import hashlib

    from .canonical_config import canonical_json

    body = {
        "hash_version": "nexora-timing-v1-ratified",
        "fields": {f.name: f.value for f in contract.fields},
        "approver": ratification.get("approver"),
        "decided_at": ratification.get("decided_at"),
        "references": ratification.get("references", []),
    }
    digest = hashlib.sha256(canonical_json(body).encode("utf-8")).hexdigest()
    return {
        "hash": digest,
        "hash_version": "nexora-timing-v1-ratified",
        "ratified": True,
        "approver": ratification.get("approver"),
        "decided_at": ratification.get("decided_at"),
    }


def walk_forward_decision(ratification: Ratification) -> Dict[str, Any]:
    return {
        "option": ratification.get("walk_forward_reconciliation"),
        "note": ratification.raw.get("walk_forward_note", ""),
    }


def experiment_decision(ratification: Ratification) -> Dict[str, Any]:
    exp = ratification.raw["experiment_configuration"]
    return {
        "candidate": exp.get("candidate"),
        # A/B/C are EXPERIMENT configs; never the production freeze.
        "as_experiment_only": True,
        "production_freeze": False,
        "note": exp.get("note", ""),
    }


def ratification_summary(project_root: Path) -> Dict[str, Any]:
    """Compact machine-readable summary for readiness output."""
    rat = load_ratification(project_root)
    if rat is None:
        return {
            "present": False,
            "valid": False,
            "problems": ["ratification file absent"],
            "path": str(Path(project_root) / RATIFICATION_FILE),
        }
    summary = {
        "present": True,
        "valid": rat.valid,
        "problems": rat.problems,
        "path": str(rat.path),
        "approver": rat.get("approver"),
        "decided_at": rat.get("decided_at"),
    }
    if rat.valid:
        summary["walk_forward"] = walk_forward_decision(rat)
        summary["experiment"] = experiment_decision(rat)
    return summary
