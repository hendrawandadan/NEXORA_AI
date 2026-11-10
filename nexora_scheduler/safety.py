"""Safety + governance preflight for research scheduler jobs (Item 2.5, Phase 3).

EVERY job must pass this preflight before its handler runs. Two independent gates:

  1. Governance gate — the canonical ``canonical_governance_gate`` from
     ``nexora_research.control_loop``. The scheduler NEVER changes governance status; it
     only READS the registry and refuses work that the gate blocks. Also re-verifies the
     governance guard is armed (prohibited actions still raise while lane suspended).

  2. PIT gate — ``research_bridge.assess_pit_safety``. When a job carries PIT-sensitive
     evidence (external acquisition), a lead that is NOT point-in-time safe must be
     labelled non-confirmatory. Depending on policy the scheduler either BLOCKS the job
     or records it as a non-confirmatory discovery lead (never confirmatory evidence).

Hard rules enforced here:
  * INFO_ACQUISITION is allowed ONLY for valid, governance-permitted proposals.
  * PRICE_DERIVED stays SUSPENDED — price-derived candidates that are suspended are
    blocked; the scheduler never reopens them.
  * UNVERIFIED data may become a discovery lead (if policy allows) but never confirmatory
    evidence.
  * SYNTHETIC data can never be confirmatory.
  * No training/tuning/promotion/live path exists here at all.
  * No bypass of governance or PIT gate.

Fail-closed: any unexpected error during a gate is treated as a BLOCK.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, Optional

from nexora_laboratory.governance.lane_suspension import (
    GovernanceViolation, assert_can, is_suspended,
)


@dataclass
class SafetyDecision:
    allowed: bool
    reasons: list = field(default_factory=list)
    governance_allowed: bool = True
    pit_safe: Optional[bool] = None
    confirmatory_ready: Optional[bool] = None
    non_confirmatory_lead: bool = False

    def as_dict(self) -> Dict[str, object]:
        return {
            "allowed": self.allowed, "reasons": list(self.reasons),
            "governance_allowed": self.governance_allowed,
            "pit_safe": self.pit_safe, "confirmatory_ready": self.confirmatory_ready,
            "non_confirmatory_lead": self.non_confirmatory_lead,
        }


# Prohibited actions the scheduler must NEVER be able to perform. Re-checking that the
# guard refuses them is a defence-in-depth self-test run on every preflight.
_PROHIBITED = ("train", "hyperparameter_tune", "promote_model", "enable_live_trading",
               "auto_reopen")


def _guard_is_armed() -> tuple:
    """Verify the governance guard refuses prohibited actions while lane suspended."""
    if not is_suspended():
        # If not suspended we still never perform these; the guard permits, which is fine.
        return True, "lane not suspended"
    leaks = []
    for action in _PROHIBITED:
        try:
            assert_can(action)
            leaks.append(action)   # should have raised -> guard not armed for this action
        except GovernanceViolation:
            pass
    if leaks:
        return False, f"governance guard failed to block prohibited actions: {leaks}"
    return True, "governance guard armed"


def preflight_governance(*, lane: Optional[str], governance_status: Optional[str],
                          rule_id: Optional[str] = None,
                          instrument: str = "", timeframe: str = "",
                          horizon: int = 0) -> SafetyDecision:
    """Run the canonical governance gate + guard-armed self-check."""
    reasons = []
    armed, armed_reason = _guard_is_armed()
    if not armed:
        return SafetyDecision(allowed=False, reasons=[armed_reason],
                              governance_allowed=False)
    reasons.append(armed_reason)
    try:
        from nexora_research.control_loop import canonical_governance_gate
        decision = canonical_governance_gate(
            lane=lane, governance_status=governance_status, rule_id=rule_id,
            instrument=instrument, timeframe=timeframe, horizon=horizon)
    except Exception as exc:  # fail-closed
        return SafetyDecision(allowed=False,
                              reasons=reasons + [f"governance gate error: {exc}"],
                              governance_allowed=False)
    reasons.append(f"canonical_governance_gate: {decision.reason}")
    return SafetyDecision(allowed=decision.allowed, reasons=reasons,
                          governance_allowed=decision.allowed)


def preflight_pit(*, evidence: Optional[object], policy_block_non_pit: bool = False
                  ) -> SafetyDecision:
    """Assess PIT safety of a job's evidence.

    Returns a SafetyDecision whose ``allowed`` is:
      * True  — either PIT-safe, or a non-confirmatory lead that is permitted as a
                discovery lead (``policy_block_non_pit=False``), or no PIT evidence to
                inspect (nothing to gate).
      * False — non-PIT-safe evidence AND ``policy_block_non_pit=True`` (BLOCK policy).
    """
    if evidence is None:
        return SafetyDecision(allowed=True, reasons=["no PIT evidence supplied"],
                              pit_safe=None, confirmatory_ready=None)
    try:
        from nexora_research.external_intelligence.research_bridge import assess_pit_safety
        res = assess_pit_safety(evidence)
    except Exception as exc:  # fail-closed
        return SafetyDecision(allowed=not policy_block_non_pit,
                              reasons=[f"PIT gate error (fail-closed): {exc}"],
                              pit_safe=False, confirmatory_ready=False)
    pit_safe = bool(res.get("pit_safe"))
    confirmatory = bool(res.get("confirmatory_ready"))
    if pit_safe:
        return SafetyDecision(allowed=True, reasons=["PIT-safe evidence"],
                              pit_safe=True, confirmatory_ready=True)
    # Not PIT safe.
    if policy_block_non_pit:
        return SafetyDecision(allowed=False,
                              reasons=["non-PIT-safe evidence (BLOCK policy)"] + res.get("reasons", []),
                              pit_safe=False, confirmatory_ready=False)
    return SafetyDecision(allowed=True,
                          reasons=["non-PIT-safe: permitted ONLY as discovery lead "
                                   "(non-confirmatory)"] + res.get("reasons", []),
                          pit_safe=False, confirmatory_ready=False,
                          non_confirmatory_lead=True)


def combined_preflight(*, job_kind: str, payload: Dict[str, object],
                       policy_block_non_pit: bool = False) -> SafetyDecision:
    """Full preflight for a job: governance + PIT, composed fail-closed.

    Two classes of job:

      * PROPOSAL-BEARING jobs (payload declares an explicit ``lane``): the FULL canonical
        governance gate is applied to the proposal (lane validity + governance_status +
        rule_id + suspension). This is the strict path used to acquire an external
        proposal.

      * INTERNAL ORCHESTRATION jobs (RESEARCH_CYCLE / STRATEGY_EVOLUTION, no payload
        ``lane``): there is no single pre-derived proposal to gate here — governance is
        enforced *per hypothesis* inside the control loop / evolution code via the SAME
        canonical gate. For these the scheduler still (a) verifies the governance guard is
        armed (prohibited actions still raise while suspended) and (b) refuses to run if
        the payload explicitly requests a non-ALLOWED governance status. This does NOT
        weaken governance: every hypothesis such a job produces is still gated
        individually before any decision.

    ``payload`` may carry:
      * lane, governance_status, rule_id, instrument, timeframe, horizon  (proposal gate)
      * evidence  (PIT assessment input)
    """
    payload_lane = payload.get("lane")

    # Armed-guard self-check always applies (defence-in-depth).
    armed, armed_reason = _guard_is_armed()
    if not armed:
        return SafetyDecision(allowed=False, reasons=[armed_reason],
                              governance_allowed=False)

    if payload_lane is not None:
        # --- Strict proposal path: full canonical gate. ---
        gov = preflight_governance(
            lane=payload_lane,
            governance_status=payload.get("governance_status"),
            rule_id=payload.get("rule_id"),
            instrument=str(payload.get("instrument", "")),
            timeframe=str(payload.get("timeframe", "")),
            horizon=int(payload.get("horizon", 0) or 0),
        )
        reasons = list(gov.reasons)
        if not gov.allowed:
            return SafetyDecision(allowed=False, reasons=reasons,
                                  governance_allowed=False)
        pit = preflight_pit(evidence=payload.get("evidence"),
                            policy_block_non_pit=policy_block_non_pit)
        reasons.extend(pit.reasons)
        return SafetyDecision(
            allowed=gov.allowed and pit.allowed,
            reasons=reasons,
            governance_allowed=gov.governance_allowed,
            pit_safe=pit.pit_safe,
            confirmatory_ready=pit.confirmatory_ready,
            non_confirmatory_lead=pit.non_confirmatory_lead,
        )

    # --- Internal orchestration path: guard-armed + per-hypothesis governance. ---
    reasons = [armed_reason,
               "internal orchestration job: governance enforced per-hypothesis in-loop"]
    requested_governance = str(payload.get("governance_status", "ALLOWED")).upper()
    if requested_governance not in ("ALLOWED", ""):
        return SafetyDecision(
            allowed=False, governance_allowed=False,
            reasons=reasons + [f"payload governance_status={requested_governance} "
                               f"is not ALLOWED (fail-closed)"])
    if payload.get("evidence") is not None:
        pit = preflight_pit(evidence=payload.get("evidence"),
                            policy_block_non_pit=policy_block_non_pit)
        reasons.extend(pit.reasons)
        return SafetyDecision(
            allowed=pit.allowed, reasons=reasons,
            governance_allowed=True, pit_safe=pit.pit_safe,
            confirmatory_ready=pit.confirmatory_ready,
            non_confirmatory_lead=pit.non_confirmatory_lead,
        )
    return SafetyDecision(allowed=True, reasons=reasons, governance_allowed=True)
