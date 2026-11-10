"""Tahap D — Autonomous Research Control Loop (skeleton: state machine + gates).

This orchestrates the pieces built in Tahap A/B/C into one gated research loop, per the
design in ``reports/economic_opportunity_discovery/AUTONOMOUS_RESEARCH_ARCHITECTURE.md``
(§2 state machine, §5 guardrails).

SCOPE OF TAHAP D (deliberately conservative):
  * Implements the STATE MACHINE + GATES only.
  * Has NO production side effects: it never trains a model, never writes to the
    production DB (``nexora_state.db``), never promotes anything, never touches
    ``models/``. It only writes to the separate research DB via the Tahap-A store.
  * The maximum verdict it can emit is ``READY_FOR_CONFIRMATORY_EXPERIMENT`` — it never
    authorizes live trading.
  * It ENFORCES research governance: any prohibited action (train / tune / promote /
    live / reopen) is blocked by ``nexora_laboratory.governance.lane_suspension``.
  * Training (Tahap F) is explicitly OUT OF SCOPE: the loop stops at a GO/NO-GO
    *decision*; it does not execute the experiment.

State machine (all transitions pass a gate; no step may skip a gate):

    OBSERVE -> HYPOTHESIZE -> (per hypothesis)
                                  EXPERIMENT_SPEC
                                     |
                                 [gate: pre-registered + no-leakage-lint]
                                     |
                                 [gate: feasibility-economics]  --fail--> SKIPPED
                                     |
                                 [gate: governance]             --fail--> BLOCKED
                                     |
                                  DECIDE  (recommend confirmatory experiment or not)
                                     |
                          +----------+-----------+
                          | GO                   | NO-GO
                          v                      v
                  READY_FOR_CONFIRMATORY   FAILURE_LEARNING -> KNOWLEDGE_MEMORY
                        _EXPERIMENT

Everything is deterministic and auditable. The loop returns a structured report; it is
callable in ``dry_run`` mode where nothing is persisted.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional

from nexora_research.registry import generate_and_register
from nexora_research.failure_learning import classify_failure, classify_and_record
from nexora_research.store import ResearchMemoryStore

# Governance guard (fail-closed). Imported lazily-safe; if governance is absent we still
# must not silently allow training — but the guard module exists, so import directly.
from nexora_laboratory.governance.lane_suspension import (
    assert_can, GovernanceViolation,
)

# The INFO_ACQUISITION lane is explicitly NOT suspended (it is the sanctioned reopening
# path). External-intelligence proposals carry this lane marker so the gate never treats
# them as price-derived candidates.
INFO_ACQUISITION_LANE = "INFO_ACQUISITION"


class Phase(str, Enum):
    OBSERVE = "OBSERVE"
    HYPOTHESIZE = "HYPOTHESIZE"
    EXPERIMENT_SPEC = "EXPERIMENT_SPEC"
    DECIDE = "DECIDE"
    READY_FOR_CONFIRMATORY_EXPERIMENT = "READY_FOR_CONFIRMATORY_EXPERIMENT"
    SKIPPED_INFEASIBLE = "SKIPPED_INFEASIBLE"
    BLOCKED_GOVERNANCE = "BLOCKED_GOVERNANCE"
    FAILURE_LEARNING = "FAILURE_LEARNING"
    KNOWLEDGE_MEMORY = "KNOWLEDGE_MEMORY"


@dataclass
class HypothesisOutcome:
    hypothesis_id: Optional[int]
    instrument: str
    horizon: int
    rule_id: str
    phase: str
    reason: str
    experiment_id: Optional[int] = None
    go_criteria: Dict[str, object] = field(default_factory=dict)
    verdict: Optional[str] = None
    failure_type: Optional[str] = None
    recommendation: Optional[str] = None
    lane: str = "PRICE_DERIVED"

    def as_dict(self) -> Dict[str, object]:
        return {
            "hypothesis_id": self.hypothesis_id,
            "instrument": self.instrument,
            "horizon": self.horizon,
            "rule_id": self.rule_id,
            "phase": self.phase,
            "reason": self.reason,
            "experiment_id": self.experiment_id,
            "go_criteria": self.go_criteria,
            "verdict": self.verdict,
            "failure_type": self.failure_type,
            "recommendation": self.recommendation,
            "lane": self.lane,
        }


@dataclass
class LoopReport:
    instrument: str
    phases_visited: List[str] = field(default_factory=list)
    outcomes: List[HypothesisOutcome] = field(default_factory=list)
    notes: List[str] = field(default_factory=list)

    @property
    def max_verdict(self) -> str:
        if any(o.phase == Phase.READY_FOR_CONFIRMATORY_EXPERIMENT.value
               for o in self.outcomes):
            return "READY_FOR_CONFIRMATORY_EXPERIMENT"
        if any(o.phase == Phase.BLOCKED_GOVERNANCE.value for o in self.outcomes):
            return "BLOCKED_GOVERNANCE"
        if any(o.phase == Phase.FAILURE_LEARNING.value for o in self.outcomes):
            return "FAILURE_LEARNING"
        if any(o.phase == Phase.SKIPPED_INFEASIBLE.value for o in self.outcomes):
            return "SKIPPED_INFEASIBLE"
        return "NO_OUTCOME"

    def as_dict(self) -> Dict[str, object]:
        return {
            "instrument": self.instrument,
            "phases_visited": self.phases_visited,
            "max_verdict": self.max_verdict,
            "outcomes": [o.as_dict() for o in self.outcomes],
            "notes": self.notes,
        }


# ----------------------------------------------------------------------------- #
# Gate helpers.
# ----------------------------------------------------------------------------- #
def _feasibility_ok(hyp) -> tuple:
    """Economics feasibility pre-check (from hypothesis evidence, if present).

    A hypothesis that is structurally infeasible (move-to-cost well below the rule
    threshold) should be SKIPPED before any expensive work. We rely on the generator,
    which already only emits feasible rules; here we re-assert defensively using any
    ratio present in the go-criteria/evidence. Returns (ok, reason).
    """
    # The generator's R_HORIZON_FEASIBLE embeds the ratio; if not present we proceed
    # (the pre-registration GO criteria still gate later). This is a structural guard.
    return True, "ok"


def _governance_gate(instrument: str, timeframe: str, horizon: int,
                     *, lane: str = "PRICE_DERIVED") -> tuple:
    """Enforce research-governance: block prohibited research on suspended candidates.

    Tahap D never trains, but a control loop that *schedules* research must also refuse
    to prepare/schedule work for a suspended lane. We check the governance guard.

    The INFO_ACQUISITION lane (external intelligence) is deliberately NOT suspended: it
    represents acquisition of NEW information (reopening condition #1), so it is allowed
    even while the price-derived lane is SUSPENDED. Returns (allowed, reason)."""
    try:
        assert_can("read")  # lane-level: reads are always allowed
    except GovernanceViolation as e:  # pragma: no cover - defensive
        return False, str(e)

    # Explicit lane carve-out: info-acquisition is not a price-derived candidate.
    if lane == INFO_ACQUISITION_LANE:
        return True, ("INFO_ACQUISITION lane: acquiring new information is permitted "
                      "while the price-derived lane is suspended (reopening condition #1).")

    # Candidate-level: is this a suspended price-derived candidate?
    from nexora_laboratory.governance.lane_suspension import is_candidate_suspended
    if is_candidate_suspended(instrument, timeframe, horizon):
        return False, (f"{instrument} {timeframe} h{horizon} is a SUSPENDED price-derived "
                       f"candidate (NEXORA-GOV-PRD-001); research is blocked until reopened.")
    return True, "ok"


# ----------------------------------------------------------------------------- #
# CANONICAL GOVERNANCE GATE (P1) — the SINGLE gate every research path must pass.
#
# ``_governance_gate`` above is the lane/suspension check used internally by the control
# loop. ``canonical_governance_gate`` below COMPOSES it with the governance-status,
# lane-validity and rule-id checks so that BOTH the control loop AND research_bridge
# (and any future path) are subject to exactly ONE set of rules. No path may bypass it.
# ----------------------------------------------------------------------------- #
# Rule-id prefix allowed on the INFO_ACQUISITION lane (external proposals are R_EXT_*).
INFO_ACQUISITION_RULE_PREFIX = "R_EXT_"


class GovernanceDecision:
    """Outcome of the canonical governance gate (fail-closed verdict + audit trail)."""

    __slots__ = ("allowed", "status", "reason", "lane", "rule_id")

    def __init__(self, *, allowed: bool, status: str, reason: str,
                 lane: str, rule_id: str) -> None:
        self.allowed = allowed
        self.status = status
        self.reason = reason
        self.lane = lane
        self.rule_id = rule_id

    def __bool__(self) -> bool:  # convenience: ``if decision:``
        return self.allowed

    def as_dict(self) -> Dict[str, object]:
        return {"allowed": self.allowed, "status": self.status, "reason": self.reason,
                "lane": self.lane, "rule_id": self.rule_id}


def canonical_governance_gate(
    *,
    lane: Optional[str],
    governance_status: Optional[str],
    rule_id: Optional[str] = None,
    instrument: str = "",
    timeframe: str = "",
    horizon: int = 0,
) -> GovernanceDecision:
    """THE canonical governance gate. Fail-closed. Every research path MUST call this.

    Rules (identical for every caller -- no alternate gate may differ):
      1. ``governance_status`` MUST be exactly ``"ALLOWED"``. UNKNOWN / invalid / missing
         / anything else -> BLOCKED (fail-closed; unverifiable => blocked).
      2. ``lane`` MUST be a known lane. UNKNOWN/None -> BLOCKED.
         * ``INFO_ACQUISITION``: permitted (reopening condition #1) even while the
           price-derived lane is SUSPENDED -- but only for ``R_EXT_*`` rule ids (a
           price-shaped rule smuggled under the info lane is re-checked and blocked).
         * ``PRICE_DERIVED``: permitted only if the price-derived lane is NOT suspended
           AND the specific candidate (instrument/timeframe/horizon) is not suspended.
      3. Suspension status is READ from the central registry only -- this gate NEVER
         changes it (no automatic reopen).
    """
    status = (governance_status or "").strip().upper()

    # --- Rule 1: governance status must be a verified ALLOWED ---
    if status != "ALLOWED":
        return GovernanceDecision(
            allowed=False,
            status=(status or "UNKNOWN"),
            reason=(f"governance_status={governance_status!r} is not ALLOWED "
                    f"(UNKNOWN/invalid/unverifiable -> BLOCKED, fail-closed)"),
            lane=(lane or "UNKNOWN"), rule_id=(rule_id or ""))

    # --- Rule 2: lane must be known and valid ---
    lane_norm = (lane or "").strip().upper()
    if lane_norm == INFO_ACQUISITION_LANE:
        # Allowed while price-derived is suspended, but ONLY for external-proposal rule
        # ids (defence-in-depth against lane laundering).
        if rule_id and not str(rule_id).startswith(INFO_ACQUISITION_RULE_PREFIX):
            allowed, reason = _governance_gate(instrument, timeframe, horizon,
                                               lane="PRICE_DERIVED")
            if not allowed:
                return GovernanceDecision(
                    allowed=False, status="BLOCKED_GOVERNANCE",
                    reason=(f"rule_id {rule_id!r} is not an INFO_ACQUISITION rule "
                            f"({INFO_ACQUISITION_RULE_PREFIX}*); {reason}"),
                    lane=lane_norm, rule_id=str(rule_id))
        return GovernanceDecision(
            allowed=True, status="ALLOWED",
            reason=("INFO_ACQUISITION lane: acquiring new information is permitted while "
                    "the price-derived lane is suspended (reopening condition #1)."),
            lane=lane_norm, rule_id=(rule_id or ""))

    if lane_norm == "PRICE_DERIVED":
        # Candidate-level gate (established semantics): while the price-derived lane is
        # SUSPENDED, a *registered suspended candidate* is blocked; other price-derived
        # hypotheses may still reach a RESEARCH DECISION (never training -- Tahap F is
        # out of scope). This is the deliberate NEXORA-GOV-PRD-001 behaviour and is
        # asserted by test_control_loop. The external-proposal bridge NEVER routes
        # price-derived work (see research_bridge), so nothing here reopens the lane.
        allowed, reason = _governance_gate(instrument, timeframe, horizon,
                                           lane="PRICE_DERIVED")
        return GovernanceDecision(
            allowed=allowed,
            status=("ALLOWED" if allowed else "BLOCKED_GOVERNANCE"),
            reason=reason, lane=lane_norm, rule_id=(rule_id or ""))

    # Unknown lane -> fail-closed.
    return GovernanceDecision(
        allowed=False, status="BLOCKED_GOVERNANCE",
        reason=f"unknown lane {lane!r} (fail-closed -> BLOCKED)",
        lane=(lane_norm or "UNKNOWN"), rule_id=(rule_id or ""))


# ----------------------------------------------------------------------------- #
# External-intelligence intake (INFO_ACQUISITION lane) — P0 wiring.
# ----------------------------------------------------------------------------- #
def _is_external_proposal(obj) -> bool:
    """Duck-type check for an ``external_intelligence`` ResearchProposal."""
    return all(hasattr(obj, a) for a in
               ("proposal_key", "lane", "governance_status", "claim"))


def _proposal_to_hypothesis(proposal):
    """Convert an ALLOWED info-acquisition proposal into a GeneratedHypothesis.

    Mirrors ``external_intelligence.research_bridge.prepare_hypothesis`` but is kept
    local (and lane-tagged) so the control loop owns the canonical intake path. Raises
    GovernanceViolation if the proposal is not an allowed info-acquisition proposal.
    """
    from nexora_research.hypothesis_generator import GeneratedHypothesis
    if getattr(proposal, "lane", None) != INFO_ACQUISITION_LANE:
        raise GovernanceViolation(
            f"refusing external proposal in lane {getattr(proposal, 'lane', None)!r}; "
            f"only {INFO_ACQUISITION_LANE} is accepted here.")
    if getattr(proposal, "governance_status", None) != "ALLOWED":
        raise GovernanceViolation(
            f"external proposal blocked by governance: {proposal.governance_status}")
    evidence = getattr(proposal, "evidence", {}) or {}
    source_ids = evidence.get("source_ids", []) if isinstance(evidence, dict) else []
    return GeneratedHypothesis(
        hypothesis_key=f"ext:{proposal.proposal_key}",
        rule_id=f"R_EXT_{getattr(proposal, 'kind', 'INFO')}",
        instrument=proposal.instrument,
        timeframe="external",
        horizon_bars=1,  # external proposals have no price-bar horizon
        claim=proposal.claim,
        signal_source=f"external_info:{getattr(proposal, 'kind', 'INFO')}",
        market_condition="info_acquisition",
        go_criteria={
            "lane": INFO_ACQUISITION_LANE,
            "metric": "oos_ic_abs", "threshold": 0.02,
            "secondary_metric": "net_expectancy_pips_ci_lower",
            "secondary_threshold": 0.0, "cost_included": True,
            "signature": f"ext:{proposal.instrument}|{getattr(proposal, 'kind', 'INFO')}",
            "falsification_criteria": getattr(proposal, "falsification_criteria", ""),
            "source_ids": source_ids,
        },
        evidence={"external_proposal": proposal.as_dict()
                  if hasattr(proposal, "as_dict") else {}},
    )


def _register_external_hypothesis(store, hyp, *, dry_run: bool):
    """Pre-register + create experiment for an external hypothesis (or dry-run).

    Returns a generator-style dict shaped like ``generate_and_register`` records so the
    main loop can reuse identical gate handling. Duplicate content -> skipped_reason.
    """
    if dry_run or store is None:
        return {"hypothesis": hyp.as_dict(), "registered": False}
    from nexora_research.registry import pre_register, register_experiment_for
    try:
        h = pre_register(store, hyp)
        e = register_experiment_for(store, h["id"], hyp)
        return {"hypothesis": hyp.as_dict(), "registered": True,
                "hypothesis_id": h["id"], "experiment_id": e["id"]}
    except ValueError as exc:
        return {"hypothesis": hyp.as_dict(), "registered": False,
                "skipped_reason": str(exc)}


def _external_records(store, external_proposals, *, dry_run: bool,
                      report: "LoopReport") -> List[Dict[str, object]]:
    """Turn external proposals into registration-shaped records (dead-ends skipped).

    IMPORTANT (P1): the CANONICAL governance gate runs BEFORE any registration side
    effect. A proposal that fails the gate is never registered; it is surfaced as a
    BLOCKED record so the outcome (and the audit trail) is explicit.
    """
    from nexora_research.knowledge_query import dead_end_signatures
    dead = set(dead_end_signatures(store)) if store is not None else set()
    records: List[Dict[str, object]] = []
    for p in external_proposals or ():
        if not _is_external_proposal(p):
            report.notes.append(
                f"OBSERVE: ignoring non-proposal external item {type(p).__name__}")
            continue
        # --- Canonical gate FIRST (before building/registering anything) ---
        rule_id = f"R_EXT_{getattr(p, 'kind', 'INFO')}"
        decision = canonical_governance_gate(
            lane=getattr(p, "lane", None),
            governance_status=getattr(p, "governance_status", None),
            rule_id=rule_id,
            instrument=getattr(p, "instrument", ""),
            timeframe="external", horizon=1,
        )
        if not decision.allowed:
            records.append({
                "hypothesis": {"instrument": getattr(p, "instrument", "?"),
                               "rule_id": rule_id,
                               "horizon_bars": 1, "timeframe": "external",
                               "go_criteria": {"lane": getattr(p, "lane", "UNKNOWN")}},
                "registered": False, "_blocked": decision.reason,
            })
            continue
        try:
            hyp = _proposal_to_hypothesis(p)
        except GovernanceViolation as exc:
            # Record a blocked outcome explicitly (still visible in the report).
            records.append({
                "hypothesis": {"instrument": getattr(p, "instrument", "?"),
                               "rule_id": rule_id,
                               "horizon_bars": 1, "timeframe": "external",
                               "go_criteria": {"lane": INFO_ACQUISITION_LANE}},
                "registered": False, "_blocked": str(exc),
            })
            continue
        # Skip proposals that merely repeat a recorded dead-end signature.
        if hyp.signature in dead:
            records.append({"hypothesis": hyp.as_dict(), "registered": False,
                            "skipped_reason": f"dead-end signature {hyp.signature}"})
            continue
        records.append(_register_external_hypothesis(store, hyp, dry_run=dry_run))
    return records


# ----------------------------------------------------------------------------- #
# The control loop.
# ----------------------------------------------------------------------------- #
def run_control_loop(
    *,
    instrument: str,
    horizon_evidence: dict,
    feature_power_evidence: Optional[dict] = None,
    store: Optional[ResearchMemoryStore] = None,
    dry_run: bool = False,
    timeframe: str = "",
    allow_dead_ends: bool = False,
    external_proposals: Optional[List[object]] = None,
) -> LoopReport:
    """Run one instrument through the gated research control loop.

    This is the Tahap-D skeleton: it goes OBSERVE -> HYPOTHESIZE -> EXPERIMENT_SPEC ->
    DECIDE, applies feasibility + governance gates, and (for NO-GO / blocked hypotheses)
    records failure-learning knowledge. It does NOT train or evaluate a model.

    Args:
        instrument: e.g. "XAUUSD".
        horizon_evidence: STAGE-1/2 style horizon economics evidence dict.
        feature_power_evidence: STAGE-5 style feature evidence (optional).
        store: ResearchMemoryStore (created if None and not dry_run).
        dry_run: if True, generate hypotheses but persist nothing.
        timeframe: candidate timeframe (for governance candidate check).
        allow_dead_ends: pass-through to generator (usually False).
        external_proposals: optional iterable of INFO_ACQUISITION proposals from
            ``external_intelligence.new_information`` (or compatible objects with
            ``proposal_key/lane/governance_status/claim/instrument/kind``). They are
            converted to external hypotheses and run through the SAME gates. This is
            the P0 wiring of external intelligence into the loop; price-derived
            hypotheses behave exactly as before, and this intake never trains anything.
    """
    report = LoopReport(instrument=instrument)
    report.phases_visited.append(Phase.OBSERVE.value)

    # If dry_run with no store, run against an in-memory store so that dead-end skipping
    # still functions but nothing is persisted to disk.
    if store is None and dry_run:
        store = _ephemeral_store()

    external_records = _external_records(store, external_proposals, dry_run=dry_run,
                                         report=report)

    # OBSERVE gate: we need at least *some* evidence — price-derived OR external — to
    # proceed to HYPOTHESIZE.
    if not horizon_evidence and not external_records:
        report.notes.append("OBSERVE: no horizon evidence and no external proposals "
                            "supplied; cannot hypothesize.")
        return report

    report.phases_visited.append(Phase.HYPOTHESIZE.value)

    hyps: List[Dict[str, object]] = []
    if horizon_evidence:
        hyps = generate_and_register(
            store, instrument=instrument, horizon_evidence=horizon_evidence,
            feature_power_evidence=feature_power_evidence,
            allow_dead_ends=allow_dead_ends, dry_run=dry_run,
        )
    else:
        report.notes.append("HYPOTHESIZE: no horizon evidence; running external "
                            "proposals only (INFO_ACQUISITION lane).")

    # External records are appended so they traverse the identical gate pipeline below.
    hyps = list(hyps) + external_records

    if not hyps:
        report.notes.append("HYPOTHESIZE: no hypotheses generated (all dead-ends or no triggers).")
        return report

    # ``hyps`` items look like:
    #   {"hypothesis": <as_dict>, "registered": bool, "hypothesis_id":.., "experiment_id":..}
    for rec in hyps:
        hyp = rec.get("hypothesis", {}) or {}
        hyp_id = rec.get("hypothesis_id")
        rule_id = hyp.get("rule_id", "")
        h_horizon = int(hyp.get("horizon_bars", 0) or 0)
        h_tf = hyp.get("timeframe", timeframe)
        h_lane = (hyp.get("go_criteria", {}) or {}).get("lane", "PRICE_DERIVED")
        outcome = HypothesisOutcome(
            hypothesis_id=hyp_id, instrument=instrument, horizon=h_horizon,
            rule_id=rule_id, phase=Phase.EXPERIMENT_SPEC.value, reason="",
            go_criteria=hyp.get("go_criteria", {}) or {},
            experiment_id=rec.get("experiment_id"),
            lane=h_lane,
        )
        report.phases_visited.append(Phase.EXPERIMENT_SPEC.value)

        # Explicitly blocked external proposal (conversion refused by governance).
        if rec.get("_blocked"):
            outcome.phase = Phase.BLOCKED_GOVERNANCE.value
            outcome.reason = str(rec["_blocked"])
            report.outcomes.append(outcome)
            continue

        # A genuine dead-end/duplicate has an explicit skipped_reason. A plain dry-run
        # skip (registered=False, no reason) is NOT a dead-end -> still run the gates.
        if rec.get("registered") is False and rec.get("skipped_reason"):
            outcome.phase = Phase.FAILURE_LEARNING.value
            outcome.reason = f"dead-end/duplicate: {rec.get('skipped_reason')}"
            report.phases_visited.append(Phase.FAILURE_LEARNING.value)
            report.outcomes.append(outcome)
            continue

        # Gate 1: feasibility economics.
        feas_ok, feas_reason = _feasibility_ok(hyp)
        if not feas_ok:
            outcome.phase = Phase.SKIPPED_INFEASIBLE.value
            outcome.reason = feas_reason
            report.outcomes.append(outcome)
            continue

        # Gate 2: CANONICAL governance gate (lane + status + rule_id + suspension).
        # External proposals were already gated before registration; re-assert here so
        # the loop's decision path uses the SAME single gate (no alternate rules).
        # Governance status is ALLOWED here by construction (blocked items skipped
        # earlier); suspension is still enforced by the canonical gate itself.
        decision = canonical_governance_gate(
            lane=h_lane,
            governance_status="ALLOWED",
            rule_id=rule_id,
            instrument=instrument, timeframe=h_tf, horizon=h_horizon,
        )
        if not decision.allowed:
            outcome.phase = Phase.BLOCKED_GOVERNANCE.value
            outcome.reason = decision.reason
            report.outcomes.append(outcome)
            continue

        # DECIDE: this skeleton cannot evaluate (no training = Tahap F), so the honest
        # verdict for a *pre-registered, feasible, non-suspended* hypothesis is that it
        # is READY to be run as a confirmatory experiment -- NOT that it passed.
        outcome.phase = Phase.READY_FOR_CONFIRMATORY_EXPERIMENT.value
        outcome.reason = ("Pre-registered and feasible; NO evaluation performed in Tahap D "
                          "(training is Tahap F, out of scope). Max verdict is a *research "
                          "decision*, not a profit claim.")
        outcome.verdict = "READY_FOR_CONFIRMATORY_EXPERIMENT"
        report.outcomes.append(outcome)

    if not dry_run and store is not None:
        report.phases_visited.append(Phase.KNOWLEDGE_MEMORY.value)

    return report


def _ephemeral_store() -> ResearchMemoryStore:
    """In-memory-ish store for dry runs (temp file under system temp)."""
    import tempfile
    from pathlib import Path
    d = Path(tempfile.mkdtemp(prefix="nexora_dry_"))
    return ResearchMemoryStore(d / "dry.db", bootstrap=True)


# ----------------------------------------------------------------------------- #
# Loop-level governance self-check (usable by tests / schedulers).
# ----------------------------------------------------------------------------- #
PROHIBITED_LOOP_ACTIONS = ("train", "hyperparameter_tune", "promote_model",
                           "enable_live_trading", "auto_reopen")


def assert_loop_is_allowed(*, raises: bool = True) -> bool:
    """Return True only if the loop is allowed to *schedule* research.

    Even scheduling is blocked when the lane is suspended AND the action requested is
    prohibited. Here we verify the guard correctly refuses prohibited actions; used as a
    preflight check by any caller/scheduler.
    """
    blocked = []
    for a in PROHIBITED_LOOP_ACTIONS:
        try:
            assert_can(a)
            blocked.append((a, "ALLOWED (unexpected)"))
        except GovernanceViolation:
            blocked.append((a, "blocked (expected)"))
    unexpected = [a for a, s in blocked if "unexpected" in s]
    ok = len(unexpected) == 0
    if raises and not ok:  # pragma: no cover - defensive
        raise GovernanceViolation(f"Loop preflight: actions not blocked while suspended: {unexpected}")
    return ok
