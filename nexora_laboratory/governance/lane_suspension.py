"""Research governance — Price-Derived Research Lane suspension (NEXORA-GOV-PRD-001).

This module ENFORCES the governance decision. It is intentionally small and
deterministic: it reads the registry (config/governance/price_derived_lane_suspension.json)
and answers "may I do X?" for the price-derived lane.

Policy: SUSPENDED (Option A — Temporary Suspension).
While SUSPENDED, the lane MUST NOT:
  * train models based on failed candidates
  * tune hyperparameters to force a positive result
  * promote models from this lane
  * enable related strategies for live trading
  * delete/overwrite failure reports or historical experiment results
Reopening is ONLY possible via explicit user authorization + the documented
reopening procedure; NO scheduler / autonomous agent / training runner may reopen
it automatically.

The guard raises GovernanceViolation on prohibited actions so it can be used as a
hard gate in any future runner (fail-closed).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, List, Optional

REGISTRY_PATH = Path("config/governance/price_derived_lane_suspension.json")

# Actions that are always prohibited while the lane is SUSPENDED.
PROHIBITED_ACTIONS = frozenset({
    "train",
    "hyperparameter_tune",
    "promote_model",
    "enable_live_trading",
    "delete_failure_report",
    "overwrite_historical_result",
    # reopening shortcuts that autonomous tooling must never take:
    "auto_reopen",
})

# Actions that are permitted (read-only / knowledge management) regardless.
ALLOWED_ACTIONS = frozenset({
    "read", "audit", "document_suspension", "review_evidence",
    "record_negative_result", "propose_reopening", "request_authorization",
})


class GovernanceViolation(RuntimeError):
    """Raised when a prohibited action is attempted on a suspended lane."""


def load_registry(path: Path = REGISTRY_PATH) -> Dict[str, object]:
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"governance registry not found: {p}")
    with open(p, encoding="utf-8") as f:
        return json.load(f)


def lane_status(path: Path = REGISTRY_PATH) -> str:
    return str(load_registry(path).get("status", "UNKNOWN")).upper()


def is_suspended(path: Path = REGISTRY_PATH) -> bool:
    return lane_status(path) == "SUSPENDED"


def assert_can(action: str, *, path: Path = REGISTRY_PATH,
               authorized: bool = False) -> None:
    """Fail-closed guard. Raises GovernanceViolation if ``action`` is not permitted.

    * Unknown actions are treated as prohibited while suspended (fail-closed).
    * Even a normally-allowed action that belongs to the prohibited set stays blocked,
      unless the lane is not suspended OR the action is a pure read/knowledge action.
    * ``authorized=True`` does NOT bypass the suspension for prohibited actions --
      reopening requires an explicit registry status change, not a flag.
    """
    action = (action or "").strip().lower()
    suspended = is_suspended(path)

    if action in ALLOWED_ACTIONS:
        return  # read/audit/knowledge actions always allowed
    if action in PROHIBITED_ACTIONS:
        if suspended:
            raise GovernanceViolation(
                f"Action '{action}' is PROHIBITED while Price-Derived lane is "
                f"SUSPENDED (NEXORA-GOV-PRD-001). Reopening requires explicit "
                f"user authorization and a registry status change.")
        return
    # Unknown action: fail-closed while suspended.
    if suspended:
        raise GovernanceViolation(
            f"Unknown action '{action}' blocked (fail-closed) while lane SUSPENDED.")
    return


def can(action: str, *, path: Path = REGISTRY_PATH) -> bool:
    try:
        assert_can(action, path=path)
        return True
    except GovernanceViolation:
        return False


def suspended_candidates(path: Path = REGISTRY_PATH) -> List[Dict[str, object]]:
    reg = load_registry(path)
    return list(reg.get("suspended_candidates", []))


def is_candidate_suspended(instrument: str, timeframe: str, horizon: int,
                           path: Path = REGISTRY_PATH) -> bool:
    for c in suspended_candidates(path):
        if (str(c.get("instrument")) == instrument
                and str(c.get("timeframe")) == timeframe
                and int(c.get("horizon")) == int(horizon)):
            return True
    return False


def assert_candidate_not_suspended(instrument: str, timeframe: str, horizon: int,
                                   *, action: str = "train",
                                   path: Path = REGISTRY_PATH) -> None:
    """Guard a specific candidate: block prohibited actions on a suspended candidate."""
    assert_can(action, path=path)
    if is_candidate_suspended(instrument, timeframe, horizon, path=path):
        # already blocked above if suspended; this is an extra explicit message
        raise GovernanceViolation(
            f"Candidate {instrument} {timeframe} h{horizon} is a SUSPENDED price-derived "
            f"candidate; action '{action}' is not allowed without reopening authorization.")
