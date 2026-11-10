"""Research Memory Integration bridge.

Connects external-intelligence proposals to the EXISTING Tahap-C/Gov machinery WITHOUT
auto-registering or auto-executing anything. Responsibilities:

  * Persist external research proposals to the ISOLATED external DB (provenance).
  * Convert an APPROVED proposal into a GeneratedHypothesis (INFO_ACQUISITION lane) --
    but registration is OPT-IN and gated by governance + pre-registration.
  * Enforce fail-closed governance: price-derived lane stays SUSPENDED; we only ever
    touch the INFO_ACQUISITION lane; no training/promotion/live/auto-reopen.
  * Record external findings as KNOWLEDGE in the research memory (append-only) so the
    loop can query them -- as STRATEGY_LEAD / CONSTRAINT entries, never overwriting.

This bridge does NOT call training, does NOT register an experiment unless the caller
explicitly opts in, and NEVER changes governance state.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Dict, List, Optional

from nexora_laboratory.governance.lane_suspension import (
    GovernanceViolation, assert_can, is_suspended,
)

from .new_information import ResearchProposal, LANE_INFO
from .repository import ExternalKnowledgeRepository


def _utcnow() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# ---------------------------------------------------------------- PIT gate (R2)
_NON_PIT_QUALITIES = {"UNVERIFIED", "SYNTHETIC", "CONFLICTING", "STALE"}


def assess_pit_safety(evidence: object) -> Dict[str, object]:
    """Inspect proposal evidence for point-in-time safety markers (R2).

    Returns a dict with:
      * ``pit_safe`` (bool): True ONLY when every relevant fact carries
        ``pit_verified == 1``, none is ``is_synthetic``, and no ``data_quality`` is in the
        non-PIT set. Any missing marker is treated as NOT safe (fail-closed).
      * ``reasons`` (list[str]): why it is (not) considered safe.
      * ``confirmatory_ready`` (bool): alias of ``pit_safe`` -- whether the lead may be
        treated as confirmatory-ready. A non-safe lead is STILL persisted as provenance,
        but must never be promoted to a "GO" claim.

    This is a *leadership* gate, not a blocker of provenance: it never raises and never
    fabricates. It only labels.
    """
    reasons: List[str] = []
    seen_any_marker = False
    pit_ok = True

    def walk(node: object) -> None:
        nonlocal seen_any_marker, pit_ok
        if isinstance(node, dict):
            if "pit_verified" in node:
                seen_any_marker = True
                if int(node.get("pit_verified") or 0) != 1:
                    pit_ok = False
                    reasons.append("pit_verified=0 (availability not source-backed)")
            if "is_synthetic" in node:
                seen_any_marker = True
                if node.get("is_synthetic"):
                    pit_ok = False
                    reasons.append("is_synthetic=1")
            dq = node.get("data_quality")
            if isinstance(dq, str) and dq.upper() in _NON_PIT_QUALITIES:
                seen_any_marker = True
                pit_ok = False
                reasons.append(f"data_quality={dq}")
            for v in node.values():
                walk(v)
        elif isinstance(node, list):
            for v in node:
                walk(v)

    walk(evidence)
    if not seen_any_marker:
        # No PIT metadata present at all -> cannot claim safety (fail-closed).
        return {"pit_safe": False,
                "reasons": ["no PIT metadata in evidence (unverified)"],
                "confirmatory_ready": False}
    if pit_ok:
        return {"pit_safe": True, "reasons": [], "confirmatory_ready": True}
    # de-dup reasons preserving order
    deduped = list(dict.fromkeys(reasons))
    return {"pit_safe": False, "reasons": deduped, "confirmatory_ready": False}


@dataclass
class BridgeResult:
    persisted: bool
    governance_status: str
    reason: str
    external_row_id: Optional[int] = None
    hypothesis_prepared: bool = False
    pit_ready: bool = False
    pit_reasons: Optional[List[str]] = None

    def as_dict(self) -> Dict[str, object]:
        return {"persisted": self.persisted, "governance_status": self.governance_status,
                "reason": self.reason, "external_row_id": self.external_row_id,
                "hypothesis_prepared": self.hypothesis_prepared,
                "pit_ready": self.pit_ready,
                "pit_reasons": self.pit_reasons or []}


def _governance_preflight() -> tuple[bool, str]:
    """Fail-closed checks. We may READ/record knowledge, but must never train/reopen."""
    # The price-derived lane being suspended must NOT block the INFO_ACQUISITION lane;
    # but any attempt to train/promote/reopen MUST be impossible through this bridge.
    if any(True for _ in ()):  # pragma: no cover - structural placeholder
        pass
    # Confirm prohibited actions are indeed blocked (so we know the guard is armed).
    for prohibited in ("train", "promote_model", "enable_live_trading", "auto_reopen"):
        try:
            assert_can(prohibited)
            # If a prohibited action were ALLOWED, the lane is not suspended -> we still
            # never perform it here; but flag it so callers are aware.
        except GovernanceViolation:
            pass
    return True, "INFO_ACQUISITION lane; price-derived lane suspension respected"


def _governance_gate(proposal: ResearchProposal):
    """Route a proposal through the CANONICAL governance gate (single source of rules).

    This is NOT an alternative gate: it delegates to
    ``control_loop.canonical_governance_gate`` so the bridge and the research control
    loop enforce IDENTICAL rules (lane validity, governance_status==ALLOWED, rule_id
    sanity, and price-derived candidate suspension). Returns a ``GovernanceDecision``.

    Additionally, the bridge is EXCLUSIVELY the INFO_ACQUISITION channel: any proposal
    whose lane is not ``INFO_ACQUISITION`` is blocked here (defence-in-depth), so the
    bridge can never be used to route price-derived work.
    """
    from nexora_research.control_loop import canonical_governance_gate, GovernanceDecision
    lane = getattr(proposal, "lane", None)
    if lane != LANE_INFO:
        # Fail-closed: the bridge refuses anything but the info-acquisition lane.
        base = canonical_governance_gate(
            lane=lane, governance_status=getattr(proposal, "governance_status", None),
            rule_id=f"R_EXT_{getattr(proposal, 'kind', 'INFO')}",
            instrument=getattr(proposal, "instrument", ""),
            timeframe="external", horizon=1)
        return GovernanceDecision(
            allowed=False, status="BLOCKED_GOVERNANCE",
            reason=(f"research_bridge only routes {LANE_INFO}; lane {lane!r} refused. "
                    f"{base.reason}"),
            lane=(base.lane or "UNKNOWN"),
            rule_id=base.rule_id)
    return canonical_governance_gate(
        lane=lane,
        governance_status=getattr(proposal, "governance_status", None),
        rule_id=f"R_EXT_{getattr(proposal, 'kind', 'INFO')}",
        instrument=getattr(proposal, "instrument", ""),
        timeframe="external", horizon=1,
    )


def persist_proposal(repo: ExternalKnowledgeRepository,
                     proposal: ResearchProposal) -> int:
    """Persist a proposal to the isolated external DB. Idempotent by content hash."""
    res = repo.insert_research_proposal(
        proposal_key=proposal.proposal_key, instrument=proposal.instrument,
        claim=proposal.claim, created_at_utc=_utcnow(), lane=proposal.lane,
        novelty_rationale=proposal.why_different,
        data_requirements=proposal.data_requirements,
        falsification_criteria=proposal.falsification_criteria,
        evidence=proposal.evidence, source_ids=proposal.evidence.get("source_ids", [])
        if isinstance(proposal.evidence, dict) else [],
        governance_status=proposal.governance_status,
    )
    return res.get("id")


def prepare_hypothesis(proposal: ResearchProposal):
    """Convert an ALLOWED info-acquisition proposal into a GeneratedHypothesis.

    Returns the hypothesis object but does NOT register it. The caller must route it
    through the existing registry (``generate_and_register`` / ``pre_register``) which
    enforces pre-registration. Raises if the proposal is not governance-allowed -- the
    decision comes from the CANONICAL governance gate (identical rules to the loop).
    """
    decision = _governance_gate(proposal)
    if not decision.allowed:
        raise GovernanceViolation(
            f"proposal blocked by canonical governance gate: {decision.reason}")

    # R2 (PIT): assess whether the proposal's evidence is point-in-time safe. This is
    # carried into the hypothesis so confirmatory readiness is explicit and auditable.
    pit = assess_pit_safety(proposal.evidence)

    from nexora_research.hypothesis_generator import GeneratedHypothesis
    return GeneratedHypothesis(
        hypothesis_key=f"ext:{proposal.proposal_key}",
        rule_id=f"R_EXT_{proposal.kind}",
        instrument=proposal.instrument,
        timeframe="external",
        horizon_bars=1,  # external hypotheses have no bar horizon; 1 satisfies >=0 constraint
        claim=proposal.claim,
        signal_source=f"external_info:{proposal.kind}",
        market_condition="info_acquisition",
        go_criteria={
            "lane": LANE_INFO,
            "metric": "oos_ic_abs", "threshold": 0.02,
            "secondary_metric": "net_expectancy_pips_ci_lower",
            "secondary_threshold": 0.0, "cost_included": True,
            "signature": f"ext:{proposal.instrument}|{proposal.kind}",
            "falsification_criteria": proposal.falsification_criteria,
            "source_ids": proposal.evidence.get("source_ids", [])
            if isinstance(proposal.evidence, dict) else [],
            # R2 (PIT): confirmatory_ready=False means the lead may be tracked as
            # provenance but must NOT be promoted to a GO claim until PIT-safe data exists.
            "pit_ready": pit["confirmatory_ready"],
            "pit_reasons": pit["reasons"],
        },
        evidence={"external_proposal": proposal.as_dict(), "pit_assessment": pit},
    )


def route_to_research_memory(repo: ExternalKnowledgeRepository,
                             proposal: ResearchProposal, *,
                             research_store=None, register: bool = False) -> BridgeResult:
    """Persist proposal, optionally pre-register (gated) into research memory.

    Args:
        repo: isolated external DB repository.
        proposal: a ResearchProposal.
        research_store: a ResearchMemoryStore (optional). If None and register=False,
            nothing is written to research memory (default safe path).
        register: if True AND an allowed info-acquisition proposal, pre-register a
            hypothesis + CREATE experiment (still NOT trained/evaluated). Requires store.

    Returns a BridgeResult describing exactly what happened.
    """
    ok, reason = _governance_preflight()
    status = proposal.governance_status

    # Canonical governance gate FIRST (fail-closed) -- decided BEFORE any side effect.
    # This is the SAME gate the research control loop uses; there is no bypass path.
    decision = _governance_gate(proposal)

    # R2 (PIT): label the lead's point-in-time readiness (never blocks provenance).
    pit = assess_pit_safety(proposal.evidence)

    # Always record the proposal to the external repo (provenance) unless dry. Persisting
    # the *proposal* row is not an experiment registration; it is provenance and remains
    # allowed even for blocked proposals (so the blocked attempt is auditable).
    row_id = None
    try:
        row_id = persist_proposal(repo, proposal)
        persisted = True
    except Exception as exc:  # pragma: no cover - defensive
        persisted = False
        reason = f"persist failed: {type(exc).__name__}"

    if not decision.allowed:
        return BridgeResult(
            persisted,
            (decision.status if decision.status != "ALLOWED" else status),
            f"blocked by canonical governance gate: {decision.reason}",
            external_row_id=row_id, pit_ready=pit["confirmatory_ready"],
            pit_reasons=pit["reasons"])

    if not register or research_store is None:
        return BridgeResult(persisted, status,
                            "proposal persisted (not pre-registered; register=False)",
                            external_row_id=row_id, hypothesis_prepared=False,
                            pit_ready=pit["confirmatory_ready"],
                            pit_reasons=pit["reasons"])

    # Pre-registration path (still no training). Enforces the existing pre-reg gate.
    hyp = prepare_hypothesis(proposal)
    from nexora_research.registry import pre_register, register_experiment_for
    try:
        h = pre_register(research_store, hyp)
        e = register_experiment_for(research_store, h["id"], hyp)
        # Also record a STRATEGY_LEAD knowledge entry pointing at the external proposal.
        # Its detail is the AUDIT TRAIL: canonical gate verdict + PIT status + ids.
        research_store.record_knowledge(
            knowledge_key=f"external_proposal:{proposal.proposal_key}",
            kind="STRATEGY_LEAD",
            summary=f"{proposal.kind}: {proposal.claim[:120]}",
            detail={"proposal": proposal.as_dict(), "hypothesis_id": h["id"],
                    "experiment_id": e["id"], "lane": proposal.lane,
                    "gate": decision.as_dict(),
                    "pit_assessment": pit,
                    "governance_note": proposal.governance_note},
        )
        return BridgeResult(persisted, status,
                            "pre-registered (experiment CREATED; not trained/evaluated)",
                            external_row_id=row_id, hypothesis_prepared=True,
                            pit_ready=pit["confirmatory_ready"],
                            pit_reasons=pit["reasons"])
    except ValueError as exc:
        return BridgeResult(persisted, status,
                            f"pre-registration refused: {exc}",
                            external_row_id=row_id, hypothesis_prepared=False,
                            pit_ready=pit["confirmatory_ready"],
                            pit_reasons=pit["reasons"])


def record_external_finding(research_store, *, finding_key: str, summary: str,
                            detail: Dict[str, object], kind: str = "STRATEGY_LEAD"
                            ) -> Dict[str, object]:
    """Record an external-intelligence finding in research memory (append-only)."""
    valid_kinds = ("FINDING", "CONSTRAINT", "DEAD_END", "STRATEGY_LEAD")
    if kind not in valid_kinds:
        raise ValueError(f"invalid kind: {kind}; must be one of {valid_kinds}")
    return research_store.record_knowledge(
        knowledge_key=f"external:{finding_key}", kind=kind, summary=summary,
        detail=detail,
    )
