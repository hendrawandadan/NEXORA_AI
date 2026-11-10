"""Tahap E — Strategy Evolution (evidence-grounded proposal generator).

Capability #8 from AUTONOMOUS_RESEARCH_ARCHITECTURE.md: from the Knowledge Memory,
propose DERIVED research hypotheses — NOT free invention. Every proposal must:

  * be grounded in recorded evidence (a GO/NO-GO/knowledge/failure entry),
  * be substantively DIFFERENT from hypotheses already recorded as dead-ends
    (governance reopening condition: "new hypothesis substantively different from the
    failed hypothesis"),
  * carry a recorded CHANGE basis justifying why it is not a blind repeat, and
  * pass the governance gate: while the PRICE-DERIVED lane is SUSPENDED
    (NEXORA-GOV-PRD-001), price-derived proposals are REFUSED unless an explicit
    reopening is authorized in the registry (never auto).

Output is a list of ``EvolutionProposal`` (structured, serializable). Proposals do NOT
train anything and do NOT register experiments by themselves; a caller may route an
approved proposal through the Tahap-C registry (pre-registration gate) via
``to_hypothesis`` + ``registry.pre_register``.

This module is READ-ONLY w.r.t. the research DB unless ``record_proposals=True`` is
passed, in which case proposals are appended as ``PROPOSAL`` knowledge entries (never
overwriting).
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from .knowledge_query import list_knowledge, dead_end_signatures
from .hypothesis_generator import GeneratedHypothesis
from .store import ResearchMemoryStore

# Lane id for the new-information-source path (mirrors external_intelligence).
INFO_ACQUISITION_LANE = "INFO_ACQUISITION"

# Governance: the price-derived lane decision id (must match config/governance).
PRICE_DERIVED_LANE_DECISION = "NEXORA-GOV-PRD-001"

# Failure types that justify a specific evolution move (from Tahap B).
_FAIL_EDGE_BELOW_COST = "EDGE_BELOW_COST"
_FAIL_OVERFIT = "OVERFIT"
_FAIL_NO_PRED = "NO_PREDICTIVE_POWER"
_FAIL_REGIME = "REGIME_FRAGILE"
_FAIL_STRUCT = "STRUCTURAL_INFEASIBILITY"
_FAIL_DATA = "DATA_QUALITY"


@dataclass
class EvolutionProposal:
    proposal_key: str
    rule_id: str
    instrument: str
    timeframe: str
    horizon_bars: int
    claim: str
    change_basis: str            # WHY this is not a blind repeat (governance requirement)
    derived_from: Dict[str, object] = field(default_factory=dict)  # evidence citations
    signal_source: str = "price_derived"
    lane: str = "PRICE_DERIVED"
    go_criteria: Dict[str, object] = field(default_factory=dict)
    governance_status: str = "UNKNOWN"     # ALLOWED / BLOCKED_GOVERNANCE
    governance_reason: str = ""

    @property
    def signature(self) -> str:
        return f"{self.instrument}|{self.timeframe}|{self.horizon_bars}"

    @property
    def allowed(self) -> bool:
        return self.governance_status == "ALLOWED"

    def as_dict(self) -> Dict[str, object]:
        return {
            "proposal_key": self.proposal_key,
            "rule_id": self.rule_id,
            "instrument": self.instrument,
            "timeframe": self.timeframe,
            "horizon_bars": self.horizon_bars,
            "claim": self.claim,
            "change_basis": self.change_basis,
            "derived_from": self.derived_from,
            "signal_source": self.signal_source,
            "lane": self.lane,
            "go_criteria": self.go_criteria,
            "governance_status": self.governance_status,
            "governance_reason": self.governance_reason,
            "signature": self.signature,
            "allowed": self.allowed,
        }

    def to_hypothesis(self) -> GeneratedHypothesis:
        """Convert an (allowed) proposal into a Tahap-C hypothesis for pre-registration."""
        return GeneratedHypothesis(
            hypothesis_key=f"evo:{self.proposal_key}",
            rule_id=self.rule_id,
            instrument=self.instrument,
            timeframe=self.timeframe,
            horizon_bars=self.horizon_bars,
            claim=self.claim,
            signal_source=self.signal_source,
            market_condition="evolution_derived",
            go_criteria=self.go_criteria,
            evidence={"change_basis": self.change_basis,
                      "derived_from": self.derived_from},
        )


# ----------------------------------------------------------------------------- #
# Governance gate for proposals (prices-derived lane suspension aware).
# ----------------------------------------------------------------------------- #
def _governance_status(instrument: str, timeframe: str, horizon: int,
                       lane: str = "PRICE_DERIVED") -> Tuple[str, str]:
    """Return (status, reason). Uses the central governance guard + registry."""
    try:
        from nexora_laboratory.governance.lane_suspension import (
            is_suspended, is_candidate_suspended, GovernanceViolation, assert_can,
        )
    except Exception:  # pragma: no cover
        return "UNKNOWN", "governance module unavailable"

    if lane != "PRICE_DERIVED":
        return "ALLOWED", f"lane {lane} not suspended"

    if not is_suspended():
        return "ALLOWED", "price-derived lane is not suspended"
    # Lane suspended: everything price-derived is blocked for scheduling/training.
    if is_candidate_suspended(instrument, timeframe, horizon):
        return ("BLOCKED_GOVERNANCE",
                f"{instrument} {timeframe} h{horizon} is a suspended candidate "
                f"({PRICE_DERIVED_LANE_DECISION}).")
    return ("BLOCKED_GOVERNANCE",
            f"price-derived lane SUSPENDED ({PRICE_DERIVED_LANE_DECISION}); new "
            f"price-derived work requires explicit reopening authorization.")


# ----------------------------------------------------------------------------- #
# Evidence aggregation.
# ----------------------------------------------------------------------------- #
def _failure_evidence(store: ResearchMemoryStore) -> List[Dict[str, object]]:
    rows = []
    for f in store.list_failures():
        try:
            ev = json.loads(f.get("evidence_json") or "{}")
        except (TypeError, ValueError):
            ev = {}
        spec = ev.get("hypothesis_spec") or {}
        rows.append({
            "failure_type": f.get("failure_type"),
            "signature": ev.get("signature") or (
                f"{spec.get('instrument')}|{spec.get('timeframe')}|{spec.get('horizon_bars')}"
                if spec.get("instrument") else None),
            "instrument": spec.get("instrument"),
            "timeframe": spec.get("timeframe"),
            "horizon_bars": spec.get("horizon_bars"),
            "recommendation": f.get("recommendation"),
        })
    return rows


def _go_evidence(store: ResearchMemoryStore) -> List[Dict[str, object]]:
    """Knowledge entries that recorded a positive/GO-like outcome."""
    out = []
    for entry in list_knowledge(store, kind="EVALUATION", latest_only=True):
        try:
            detail = json.loads(entry.get("detail_json") or "{}")
        except (TypeError, ValueError):
            detail = {}
        if str(detail.get("verdict", "")).upper() == "GO":
            out.append({"summary": entry.get("summary"), "detail": detail})
    return out


# ----------------------------------------------------------------------------- #
# Proposal rules (each states a CHANGE basis -> governance reopening condition).
# ----------------------------------------------------------------------------- #
def evolve_proposals(
    store: ResearchMemoryStore,
    *,
    candidate_instruments: Optional[List[str]] = None,
    record_proposals: bool = False,
) -> List[EvolutionProposal]:
    """Derive evolution proposals from the Knowledge Memory.

    Args:
        store: research memory.
        candidate_instruments: instruments to consider for *transfer* (default: from
            the GO/failure evidence, deduped).
        record_proposals: if True, append each proposal as a PROPOSAL knowledge entry.
    """
    failures = _failure_evidence(store)
    dead = set(dead_end_signatures(store))
    go_entries = _go_evidence(store)

    proposals: List[EvolutionProposal] = []

    # Group failures by instrument for reasoning.
    by_inst: Dict[str, List[Dict[str, object]]] = {}
    for f in failures:
        inst = f.get("instrument") or "UNKNOWN"
        by_inst.setdefault(inst, []).append(f)

    def _safe_add(p: EvolutionProposal):
        # Refuse to emit anything that merely repeats a recorded dead-end signature,
        # unless it carries an explicit change basis (always does here) AND is a
        # different signature. Governance gate applied after.
        if p.signature in dead and "shift" not in p.rule_id and "transfer" not in p.rule_id:
            return
        status, reason = _governance_status(p.instrument, p.timeframe, p.horizon_bars, p.lane)
        p.governance_status = status
        p.governance_reason = reason
        proposals.append(p)

    # --- R_EVOLVE_HORIZON_SHIFT -------------------------------------------
    # If a horizon-class failed EDGE_BELOW_COST or OVERFIT, the *same* horizon is a
    # dead-end; propose a DIFFERENT horizon class (scaled), with a change basis.
    for inst, fails in by_inst.items():
        for f in fails:
            ft = f.get("failure_type")
            if ft not in (_FAIL_EDGE_BELOW_COST, _FAIL_OVERFIT, _FAIL_REGIME):
                continue
            h = f.get("horizon_bars")
            tf = f.get("timeframe")
            if not isinstance(h, int) or h <= 0 or not tf:
                continue
            # Propose a longer horizon (2x) as a distinct class; different signature.
            new_h = h * 2
            _safe_add(EvolutionProposal(
                proposal_key=f"evo:{inst}:{tf}:h{new_h}:horizon_shift",
                rule_id="R_EVOLVE_HORIZON_SHIFT",
                instrument=str(inst), timeframe=str(tf), horizon_bars=int(new_h),
                claim=(f"{inst} {tf} failed at h={h} ({ft}); test a longer horizon h={new_h} "
                       f"where move/cost ratio is structurally higher, holding signal source "
                       f"fixed to isolate horizon effect."),
                change_basis=(f"Different horizon class (h={new_h} vs failed h={h}); longer "
                              f"horizon has higher move-to-cost per discovery — a recorded "
                              f"change, not a repeat."),
                derived_from={"failure_type": ft, "failed_horizon": h, "source": "failure_learning"},
                go_criteria={"metric": "net_expectancy_pips_ci_lower", "threshold": 0.0,
                             "secondary_metric": "oos_directional_accuracy",
                             "secondary_threshold": 0.52, "cost_included": True},
            ))

    # --- R_EVOLVE_INSTRUMENT_TRANSFER -------------------------------------
    # If a family GO'd on one instrument, propose testing it on ANOTHER instrument
    # (structural transfer). Requires the target not be a recorded dead-end.
    target_instruments = candidate_instruments or sorted({k for k in by_inst})
    for g in go_entries:
        det = g.get("detail", {})
        src_inst = det.get("instrument")
        tf = det.get("timeframe")
        h = det.get("horizon_bars")
        if not src_inst or not tf or not isinstance(h, int):
            continue
        for tgt in target_instruments:
            if tgt == src_inst:
                continue
            _safe_add(EvolutionProposal(
                proposal_key=f"evo:{tgt}:{tf}:h{h}:transfer_from_{src_inst}",
                rule_id="R_EVOLVE_INSTRUMENT_TRANSFER",
                instrument=str(tgt), timeframe=str(tf), horizon_bars=int(h),
                claim=(f"The family that GO'd on {src_inst} {tf} h{h} is proposed for "
                       f"structural transfer to {tgt} (same tf/horizon)."),
                change_basis=(f"Instrument transfer: a GO'd family on {src_inst} is tested on "
                              f"{tgt} — a substantive change in market, not a repeat of the "
                              f"identical experiment."),
                derived_from={"source_instrument": src_inst, "go_summary": g.get("summary")},
                go_criteria=det.get("go_criteria") or {
                    "metric": "net_expectancy_pips_ci_lower", "threshold": 0.0,
                    "cost_included": True},
            ))

    # --- R_EVOLVE_NEW_INFO_SOURCE -----------------------------------------
    # If price-derived features showed NO_PREDICTIVE_POWER on an instrument, the honest
    # move is a NEW INFO SOURCE (governance reopening condition #1). We propose this as
    # a research action (not a price-derived hypothesis), so it is not lane-blocked.
    for inst, fails in by_inst.items():
        if any(f.get("failure_type") == _FAIL_NO_PRED for f in fails):
            p = EvolutionProposal(
                proposal_key=f"evo:{inst}:new_info_source",
                rule_id="R_EVOLVE_NEW_INFO_SOURCE",
                instrument=str(inst), timeframe="N/A", horizon_bars=0,
                claim=(f"Price-derived features had NO_PREDICTIVE_POWER for {inst}. Rather "
                       f"than re-run the same features, acquire a NEW information source "
                       f"(e.g. order-flow, macro, cross-asset lead) for {inst}."),
                change_basis=("New information source (governance reopening condition #1): "
                              "the failed path used price-derived features only."),
                derived_from={"failure_type": _FAIL_NO_PRED},
                signal_source="new_information_source",
                lane="INFO_ACQUISITION",
                go_criteria={"metric": "oos_ic_abs", "threshold": 0.02,
                             "secondary_metric": "net_expectancy_pips_ci_lower",
                             "secondary_threshold": 0.0, "cost_included": True},
            )
            status, reason = _governance_status(p.instrument, p.timeframe, p.horizon_bars, p.lane)
            p.governance_status = status
            p.governance_reason = reason
            proposals.append(p)  # info-acquisition lane is NOT suspended

    # Deterministic ordering.
    priority = {"R_EVOLVE_NEW_INFO_SOURCE": 0, "R_EVOLVE_HORIZON_SHIFT": 1,
                "R_EVOLVE_INSTRUMENT_TRANSFER": 2}
    proposals.sort(key=lambda p: (priority.get(p.rule_id, 99), p.proposal_key))

    if record_proposals:
        for p in proposals:
            store.record_knowledge(
                knowledge_key=f"proposal:{p.proposal_key}",
                kind="STRATEGY_LEAD",
                summary=f"{p.rule_id}: {p.claim[:120]}",
                detail=p.as_dict(),
            )

    return proposals


# ----------------------------------------------------------------------------- #
# P0 (roadmap item 2.4): EXECUTE the new-information-source acquisition.
#
# An R_EVOLVE_NEW_INFO_SOURCE proposal says "acquire a new info source". This function
# turns that proposal into an ACTUAL acquisition: it runs the external-intelligence
# orchestrator for the instrument, then routes the discovered external proposals into
# the research control loop (INFO_ACQUISITION lane). It NEVER trains/evaluates for
# profit/promotes/trades/reopens the price-derived lane.
# ----------------------------------------------------------------------------- #
@dataclass
class AcquisitionExecution:
    """Structured result linking trigger -> acquisition -> external proposals -> loop."""
    proposal_key: str
    instrument: str
    executed: bool
    refused_reason: str = ""
    intel_report: Optional[Dict[str, object]] = None
    external_proposals: int = 0
    loop_max_verdict: str = ""
    loop_outcomes: List[Dict[str, object]] = field(default_factory=list)
    notes: List[str] = field(default_factory=list)

    def as_dict(self) -> Dict[str, object]:
        return {
            "proposal_key": self.proposal_key, "instrument": self.instrument,
            "executed": self.executed, "refused_reason": self.refused_reason,
            "intel_report": self.intel_report, "external_proposals": self.external_proposals,
            "loop_max_verdict": self.loop_max_verdict, "loop_outcomes": self.loop_outcomes,
            "notes": self.notes,
        }


def execute_new_info_acquisition(
    store: ResearchMemoryStore,
    proposal: EvolutionProposal,
    *,
    events: Optional[List[Dict]] = None,
    central_bank_docs: Optional[List[Dict]] = None,
    news: Optional[List[Dict]] = None,
    price_bars: Optional[List[Dict]] = None,
    cross_market_pairs: Optional[List[Dict]] = None,
    horizon_evidence: Optional[Dict] = None,
    external_repo=None,
    dry_run: bool = True,
    record: bool = False,
) -> AcquisitionExecution:
    """Execute an R_EVOLVE_NEW_INFO_SOURCE proposal via real acquisition + control loop.

    Fail-closed:
      * Only ``R_EVOLVE_NEW_INFO_SOURCE`` proposals on the INFO_ACQUISITION lane that
        are governance-ALLOWED are executed; anything else is refused (returns
        ``executed=False`` with a reason) -- never silently run.
      * ``dry_run`` defaults True: the external repo + research loop persist nothing.
      * Never trains, evaluates for profit, promotes, trades, or reopens the lane.

    Args:
        store: research memory (used by the control loop).
        proposal: an EvolutionProposal from ``evolve_proposals``.
        events/central_bank_docs/news/price_bars/cross_market_pairs: external data the
            caller has already fetched (the orchestrator never does live network I/O).
        horizon_evidence: optional price-derived horizon evidence to also run through the
            loop (kept separate; governance still blocks price-derived candidates).
        external_repo: isolated ExternalKnowledgeRepository (created if None & not dry).
        dry_run: when True, persist nothing in the external repo / research loop.
        record: when True, also record a STRATEGY_LEAD linking trigger->execution.
    """
    ece = AcquisitionExecution(proposal_key=proposal.proposal_key,
                               instrument=proposal.instrument, executed=False)

    # ---- Gate: only the new-info-source rule on the info lane, ALLOWED. ----
    if proposal.rule_id != "R_EVOLVE_NEW_INFO_SOURCE":
        ece.refused_reason = (f"rule_id {proposal.rule_id} is not R_EVOLVE_NEW_INFO_SOURCE")
        return ece
    if proposal.lane != INFO_ACQUISITION_LANE:
        ece.refused_reason = (f"lane {proposal.lane} != {INFO_ACQUISITION_LANE}")
        return ece
    if not proposal.allowed:
        ece.refused_reason = (f"proposal not governance-allowed: {proposal.governance_status}"
                              f" ({proposal.governance_reason})")
        return ece

    from nexora_research.external_intelligence import orchestrator
    from nexora_research.external_intelligence.config import ExternalIntelConfig
    from nexora_research.control_loop import run_control_loop, INFO_ACQUISITION_LANE as LOOP_INFO

    config = ExternalIntelConfig(dry_run=dry_run)
    repo = external_repo
    if repo is None and not dry_run:
        from nexora_research.external_intelligence.repository import ExternalKnowledgeRepository
        repo = ExternalKnowledgeRepository()

    # ---- 1) ACQUIRE: run the external-intelligence orchestrator. ----
    intel = orchestrator.run_intelligence(
        instrument=proposal.instrument, repo=repo, research_store=store,
        config=config, events=events, central_bank_docs=central_bank_docs,
        news=news, price_bars=price_bars, cross_market_pairs=cross_market_pairs,
        register=False, record_raw_snapshot=not dry_run,
    )
    ece.intel_report = intel.as_dict()
    ext_proposals = list(getattr(intel, "discovered_proposals", []) or [])
    ece.external_proposals = len(ext_proposals)

    if not ext_proposals:
        ece.executed = True
        ece.notes.append("acquisition ran but discovered no new-information proposals; "
                         "nothing to route to the control loop.")
        if record:
            store.record_knowledge(
                knowledge_key=f"acquisition:{proposal.proposal_key}",
                kind="STRATEGY_LEAD",
                summary=f"new-info acquisition for {proposal.instrument}: no proposals",
                detail=ece.as_dict())
        return ece

    # ---- 2) ROUTE: feed external proposals into the research control loop. ----
    loop_report = run_control_loop(
        instrument=proposal.instrument, horizon_evidence=horizon_evidence,
        store=store, dry_run=dry_run, external_proposals=ext_proposals,
    )
    ece.loop_max_verdict = loop_report.max_verdict
    ece.loop_outcomes = [
        {"phase": o.phase, "verdict": o.verdict, "lane": o.lane,
         "hypothesis_id": o.hypothesis_id, "experiment_id": o.experiment_id}
        for o in loop_report.outcomes if o.lane == LOOP_INFO
    ]
    ece.notes.extend(loop_report.notes)
    ece.executed = True

    if record:
        store.record_knowledge(
            knowledge_key=f"acquisition:{proposal.proposal_key}",
            kind="STRATEGY_LEAD",
            summary=(f"new-info acquisition for {proposal.instrument}: "
                     f"{ece.external_proposals} proposals, verdict {ece.loop_max_verdict}"),
            detail=ece.as_dict())

    return ece
