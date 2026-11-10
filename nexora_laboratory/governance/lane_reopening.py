"""Price-Derived Research Lane reopening - proposal & ratification helpers (NEXORA-GOV-PRD-002).

This module supports the REOPENING procedure defined by NEXORA-GOV-PRD-001
(``config/governance/price_derived_lane_suspension.json``). It is deliberately
narrow and *proposal-facing*: it can BUILD and VERIFY a reopening packet, but it
**never** mutates the governance registry. Applying a successful ratification is a
separate, explicit, owner-only tool (``tools/apply_lane_reopening.py``).

Lifecycle (all stages are reversed from automatic re-opening):

    1. SUSPENDED            (current registry status)
    2. REOPENING_PROPOSED   (a signed reopening packet exists; training still blocked)
    3. RATIFIED             (a signed ratification record approves the proposal)
    4. REOPENED             (registry status flipped ONLY by the owner-only tool)

Rules enforced here:
  * The suspension guard (:mod:`lane_suspension`) is untouched. While the registry
    says SUSPENDED, ``assert_can("train")`` still raises - even if a proposal or
    ratification record exists. Re-opening requires an actual registry status
    change, never a flag.
  * A proposal is only *well-formed* if it maps onto the reopening conditions and
    procedure documented in the registry; the guard's ``reopening_conditions`` and
    ``reopening_procedure`` are read from the registry (single source of truth).
  * Signing uses HMAC-SHA256 over canonical JSON (same primitive as the PREP-001
    sign-off), with the key supplied via ``NEXORA_GOVERNANCE_KEY`` (never committed).
  * Nothing here trains, tunes, promotes, enables live trading, or auto-reopens.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
from pathlib import Path
from typing import Any, Dict, List, Optional

from . import lane_suspension
from .lane_suspension import GovernanceViolation, PROHIBITED_ACTIONS

# Decision ids used by this reopening flow.
REOPENING_PROPOSAL_ID = "NEXORA-GOV-PRD-002-PROPOSAL"
REOPENING_RATIFICATION_ID = "NEXORA-GOV-PRD-002-RATIFICATION"

# Lifecycle states (registry ``status`` may additionally be SUSPENDED/REOPENED).
STAGE_SUSPENDED = "SUSPENDED"
STAGE_PROPOSED = "REOPENING_PROPOSED"
STAGE_RATIFIED = "RATIFIED"
STAGE_REOPENED = "REOPENED"

# Status the registry may hold after the owner flips it.
REGISTRY_OPEN_STATUS = "REOPENED_WITH_AUTHORIZATION"

INTEGRITY_HMAC_SHA256 = "hmac-sha256"
INTEGRITY_NONE = "none"
_SUPPORTED_INTEGRITY = {INTEGRITY_NONE, INTEGRITY_HMAC_SHA256}


class ReopeningError(RuntimeError):
    """Raised when a reopening packet is malformed or cannot be applied safely."""


# ---------------------------------------------------------------------------
# Canonical JSON + HMAC (matches nexora_audit.canonical_config conventions).
# ---------------------------------------------------------------------------
def canonical_json(payload: Dict[str, Any]) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def sign_payload(payload: Dict[str, Any], key: str) -> Dict[str, Any]:
    """Return a copy of ``payload`` with an HMAC-SHA256 ``integrity`` block."""
    body = {k: v for k, v in payload.items() if k != "integrity"}
    sig = hmac.new(key.encode("utf-8"), canonical_json(body).encode("utf-8"),
                   hashlib.sha256).hexdigest()
    signed = dict(payload)
    signed["integrity"] = {"mechanism": INTEGRITY_HMAC_SHA256, "signature": sig}
    return signed


def verify_integrity(payload: Dict[str, Any], key: Optional[str] = None) -> Dict[str, Any]:
    """Verify the ``integrity`` block. Returns ``{status, mechanism, detail}``.

    ``status`` is one of VERIFIED / INVALID / UNVERIFIED / UNSUPPORTED / ABSENT.
    A structurally valid packet with no signature is UNVERIFIED, never trusted.
    """
    integrity = payload.get("integrity") if isinstance(payload, dict) else None
    if not isinstance(integrity, dict):
        return {"status": "ABSENT", "mechanism": INTEGRITY_NONE,
                "detail": "no integrity block; unsigned"}
    mechanism = str(integrity.get("mechanism") or INTEGRITY_NONE).strip().lower()
    if mechanism not in _SUPPORTED_INTEGRITY:
        return {"status": "UNSUPPORTED", "mechanism": mechanism,
                "detail": f"integrity mechanism {mechanism!r} not supported"}
    if mechanism == INTEGRITY_NONE:
        return {"status": "UNVERIFIED", "mechanism": INTEGRITY_NONE,
                "detail": "integrity block declares 'none'"}
    declared = str(integrity.get("signature") or "").strip()
    if not declared:
        return {"status": "UNVERIFIED", "mechanism": mechanism,
                "detail": "hmac-sha256 declared but signature empty"}
    key = key if key is not None else os.environ.get("NEXORA_GOVERNANCE_KEY")
    if not key:
        return {"status": "UNVERIFIED", "mechanism": mechanism,
                "detail": "NEXORA_GOVERNANCE_KEY not set; cannot verify"}
    body = {k: v for k, v in payload.items() if k != "integrity"}
    expected = hmac.new(key.encode("utf-8"), canonical_json(body).encode("utf-8"),
                        hashlib.sha256).hexdigest()
    ok = hmac.compare_digest(expected, declared)
    return {"status": "VERIFIED" if ok else "INVALID", "mechanism": mechanism,
            "detail": "hmac-sha256 signature verified" if ok else "hmac-sha256 mismatch"}


# ---------------------------------------------------------------------------
# Registry reading (read-only).
# ---------------------------------------------------------------------------
def load_registry(path: Path = lane_suspension.REGISTRY_PATH) -> Dict[str, Any]:
    return lane_suspension.load_registry(path)


def registry_conditions(path: Path = lane_suspension.REGISTRY_PATH) -> List[str]:
    return list(load_registry(path).get("reopening_conditions", []))


def registry_procedure(path: Path = lane_suspension.REGISTRY_PATH) -> List[str]:
    return list(load_registry(path).get("reopening_procedure", []))


def suspended_candidate_keys(path: Path = lane_suspension.REGISTRY_PATH) -> List[Dict[str, Any]]:
    return list(load_registry(path).get("suspended_candidates", []))


# ---------------------------------------------------------------------------
# Proposal validation.
# ---------------------------------------------------------------------------
def validate_proposal(proposal: Dict[str, Any],
                      path: Path = lane_suspension.REGISTRY_PATH) -> Dict[str, Any]:
    """Structurally validate a reopening PROPOSAL against the registry.

    The proposal must:
      * reference the suspended decision (``decision_id`` == NEXORA-GOV-PRD-001);
      * cite at least one registry ``reopening_condition`` it satisfies, using the
        exact documented condition text;
      * state a NEW hypothesis (non-empty) and explain how it is substantively
        different from the failed one;
      * map every registry ``reopening_procedure`` step to a status.

    Returns ``{valid, problems, ...}``. Does NOT check signatures.
    """
    problems: List[str] = []
    reg = load_registry(path)
    conditions = list(reg.get("reopening_conditions", []))
    procedure = list(reg.get("reopening_procedure", []))

    if str(proposal.get("decision_id")) != str(reg.get("decision_id")):
        problems.append(
            f"proposal decision_id must reference {reg.get('decision_id')!r}")
    if str(proposal.get("type", "")).upper() != "REOPENING_PROPOSAL":
        problems.append("proposal.type must be 'REOPENING_PROPOSAL'")

    approver = str(proposal.get("approver") or "").strip()
    if not approver or approver.startswith("<"):
        problems.append("missing/placeholder approver")

    # Conditions satisfied must be drawn from the registry list verbatim.
    satisfied = proposal.get("conditions_satisfied") or []
    if not satisfied:
        problems.append("no reopening condition satisfied")
    for item in satisfied:
        cond = (item.get("condition") if isinstance(item, dict) else str(item)).strip()
        if cond not in conditions:
            problems.append(f"condition not in registry reopening_conditions: {cond!r}")

    # New hypothesis must be present and substantively distinct.
    hyp = proposal.get("new_hypothesis") or ""
    if not str(hyp).strip():
        problems.append("missing new_hypothesis")
    if not str(proposal.get("distinct_from_failed_hypothesis") or "").strip():
        problems.append("missing distinct_from_failed_hypothesis explanation")

    # Every documented procedure step must be mapped.
    mapped = proposal.get("procedure_status") or {}
    for step in procedure:
        entry = mapped.get(step)
        status = ""
        if isinstance(entry, dict):
            status = str(entry.get("status") or "").strip().upper()
        elif entry is not None:
            status = str(entry).strip().upper()
        if not status:
            problems.append(f"procedure step not addressed: {step!r}")
        elif status not in {"DONE", "PENDING", "NOT_STARTED", "N/A"}:
            problems.append(f"procedure step {step!r} has unknown status {status!r}")

    # Candidate scope must be a subset of the suspended candidates.
    suspended = {
        (str(c.get("instrument")), str(c.get("timeframe")), int(c.get("horizon")))
        for c in reg.get("suspended_candidates", [])
    }
    requested = []
    for c in proposal.get("candidates_requested") or []:
        key = (str(c.get("instrument")), str(c.get("timeframe")), int(c.get("horizon")))
        requested.append(key)
        if key not in suspended:
            problems.append(f"candidate not in suspension scope: {key}")

    return {
        "valid": not problems,
        "problems": problems,
        "decision_id": reg.get("decision_id"),
        "conditions": conditions,
        "procedure": procedure,
        "suspended_candidate_keys": sorted(suspended),
        "requested_candidate_keys": requested,
    }


# ---------------------------------------------------------------------------
# Ratification validation.
# ---------------------------------------------------------------------------
REQUIRED_RATIFICATION_FIELDS = (
    "approver",
    "decided_at",
    "proposal_reference",
    "decision",
)


def proposal_hash(proposal: Dict[str, Any]) -> str:
    """Stable sha256 over the proposal body (excluding any integrity block)."""
    body = {k: v for k, v in proposal.items() if k != "integrity"}
    return hashlib.sha256(canonical_json(body).encode("utf-8")).hexdigest()


def validate_ratification(ratification: Dict[str, Any],
                          proposal: Optional[Dict[str, Any]] = None,
                          path: Path = lane_suspension.REGISTRY_PATH) -> Dict[str, Any]:
    """Structurally validate a RATIFICATION record (optionally bound to a proposal).

    If ``proposal`` is supplied, the ratification must reference the same
    ``proposal_hash`` (sha256 of the proposal body) so a ratification cannot be
    swapped onto a different proposal.
    """
    problems: List[str] = []
    for fld in REQUIRED_RATIFICATION_FIELDS:
        val = ratification.get(fld)
        if val is None or (isinstance(val, str) and (not val.strip() or val.startswith("<"))):
            problems.append(f"missing/placeholder {fld}")
    decision = str(ratification.get("decision") or "").strip().upper()
    if decision and decision not in {"APPROVED", "REJECTED"}:
        problems.append("decision must be APPROVED or REJECTED")
    if proposal is not None:
        ph = proposal_hash(proposal)
        if str(ratification.get("proposal_hash") or "") != ph:
            problems.append("ratification.proposal_hash does not match proposal")
    return {"valid": not problems, "problems": problems}


# ---------------------------------------------------------------------------
# Combined lifecycle assessment (read-only; never mutates the registry).
# ---------------------------------------------------------------------------
def assess_lifecycle(*,
                     proposal: Optional[Dict[str, Any]] = None,
                     ratification: Optional[Dict[str, Any]] = None,
                     key: Optional[str] = None,
                     path: Path = lane_suspension.REGISTRY_PATH) -> Dict[str, Any]:
    """Return the current reopening stage and what (if anything) may proceed.

    The registry status is authoritative: while it is SUSPENDED, the stage can at
    most be PROPOSED or RATIFIED, and *training remains blocked*. Only a registry
    status change (performed by the owner-only apply tool) yields REOPENED.
    """
    reg_status = lane_suspension.lane_status(path)
    out: Dict[str, Any] = {
        "registry_status": reg_status,
        "stage": STAGE_SUSPENDED,
        "training_allowed": not lane_suspension.is_suspended(path),
        "proposal": None,
        "ratification": None,
        "reasons": [],
    }

    if proposal is not None:
        pv = validate_proposal(proposal, path)
        pi = verify_integrity(proposal, key)
        out["proposal"] = {"validation": pv, "integrity": pi}
        if pv["valid"] and pi["status"] in {"VERIFIED", "UNVERIFIED", "ABSENT"}:
            out["stage"] = STAGE_PROPOSED
        if not pv["valid"]:
            out["reasons"].extend(pv["problems"])

    if ratification is not None:
        rv = validate_ratification(ratification, proposal, path)
        ri = verify_integrity(ratification, key)
        out["ratification"] = {"validation": rv, "integrity": ri}
        approved = (
            rv["valid"]
            and str(ratification.get("decision") or "").upper() == "APPROVED"
            and ri["status"] == "VERIFIED"
        )
        if approved:
            out["stage"] = STAGE_RATIFIED
            out["reasons"].append(
                "ratification APPROVED and signed; registry still "
                f"{reg_status} until owner applies reopening")
        elif not rv["valid"]:
            out["reasons"].extend(rv["problems"])

    if not lane_suspension.is_suspended(path):
        out["stage"] = STAGE_REOPENED
        out["training_allowed"] = True
        out["reasons"].append("registry status is no longer SUSPENDED")
    return out


# ---------------------------------------------------------------------------
# Guard-armed self-check (defence in depth).
# ---------------------------------------------------------------------------
def assert_suspension_still_enforced(path: Path = lane_suspension.REGISTRY_PATH) -> bool:
    """While SUSPENDED, confirm every prohibited action still raises (guard armed).

    Returns True when the guard is armed. Raises ReopeningError if any prohibited
    action leaks through while the registry still says SUSPENDED.
    """
    if not lane_suspension.is_suspended(path):
        return True
    leaks: List[str] = []
    for action in sorted(PROHIBITED_ACTIONS):
        try:
            lane_suspension.assert_can(action, path=path)
            leaks.append(action)
        except GovernanceViolation:
            pass
    if leaks:
        raise ReopeningError(
            f"governance guard failed to block prohibited actions while SUSPENDED: {leaks}")
    return True


__all__ = [
    "REOPENING_PROPOSAL_ID",
    "REOPENING_RATIFICATION_ID",
    "STAGE_SUSPENDED",
    "STAGE_PROPOSED",
    "STAGE_RATIFIED",
    "STAGE_REOPENED",
    "REGISTRY_OPEN_STATUS",
    "ReopeningError",
    "canonical_json",
    "sign_payload",
    "verify_integrity",
    "load_registry",
    "registry_conditions",
    "registry_procedure",
    "suspended_candidate_keys",
    "validate_proposal",
    "validate_ratification",
    "proposal_hash",
    "assess_lifecycle",
    "assert_suspension_still_enforced",
]
