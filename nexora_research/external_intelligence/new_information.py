"""New Information Discovery -- turn external intelligence into RESEARCH PROPOSALS.

This is the mission-critical capability: from what the external-intelligence layer has
learned (events, central-bank shifts, cross-market breakdowns, event responses), detect
NOVEL information and frame a *testable, falsifiable* research proposal per finding.

A proposal is NOT a trading signal. Each proposal must state:
  * what new information was found and why it differs from prior knowledge,
  * why it matters for the market,
  * what data is required to validate it,
  * the hypothesis it can be tested as,
  * how it could be FALSIFIED,
  * data-leakage risks,
  * whether the research would violate governance.

Proposals target the INFO_ACQUISITION lane only. That lane is permitted even while the
Price-Derived Research Lane is SUSPENDED (NEXORA-GOV-PRD-001); we NEVER emit a proposal
that re-opens the price-derived lane. Registration/execution happens elsewhere through
the existing pre-registration + governance gates (see research_bridge).

Pure functions; caller supplies already-computed intelligence dicts.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from typing import Dict, List, Optional

GOVERNANCE_DECISION = "NEXORA-GOV-PRD-001"
LANE_INFO = "INFO_ACQUISITION"   # allowed lane; NOT price-derived


@dataclass
class ResearchProposal:
    proposal_key: str
    instrument: str
    kind: str                       # EVENT_RESPONSE / CB_SHIFT / XMARKET_BREAKDOWN / ...
    claim: str
    new_information: str
    why_different: str
    market_relevance: str
    data_requirements: List[str] = field(default_factory=list)
    hypothesis: str = ""
    falsification_criteria: str = ""
    leakage_risks: List[str] = field(default_factory=list)
    governance_status: str = "ALLOWED"   # INFO_ACQUISITION lane
    governance_note: str = ""
    evidence: Dict[str, object] = field(default_factory=dict)
    lane: str = LANE_INFO

    def as_dict(self) -> Dict[str, object]:
        return {
            "proposal_key": self.proposal_key, "instrument": self.instrument,
            "kind": self.kind, "claim": self.claim,
            "new_information": self.new_information, "why_different": self.why_different,
            "market_relevance": self.market_relevance,
            "data_requirements": self.data_requirements, "hypothesis": self.hypothesis,
            "falsification_criteria": self.falsification_criteria,
            "leakage_risks": self.leakage_risks,
            "governance_status": self.governance_status,
            "governance_note": self.governance_note, "evidence": self.evidence,
            "lane": self.lane,
        }

    @property
    def is_actionable(self) -> bool:
        return (self.governance_status == "ALLOWED" and self.lane == LANE_INFO
                and bool(self.falsification_criteria.strip())
                and bool(self.data_requirements))


def _gov_note() -> str:
    return (f"INFO_ACQUISITION lane only. Price-derived lane remains SUSPENDED "
            f"({GOVERNANCE_DECISION}); this proposal does not re-open or launder it. "
            f"Registration requires pre-registration + user authorization.")


def _leakage_risks_common() -> List[str]:
    return [
        "Using revised/as-of data that was unavailable at the fact time (look-ahead).",
        "Aligning event timestamps without accounting for release embargo/delay.",
        "Survivorship bias in the instrument/country universe.",
        "Overlapping event windows contaminating train/test splits (needs purge/embargo).",
    ]


def _key(instrument: str, kind: str, discriminator: str) -> str:
    return f"ni:{instrument}:{kind}:{discriminator}"


def proposals_from_event_responses(
    event_responses: List[Dict[str, object]], *, instrument: str,
) -> List[ResearchProposal]:
    """Propose research when an event's surplus response shows a consistent pattern.

    Expects items shaped like event_response.EventResponse.as_dict() enriched with a
    'surprise' key (float|None) and 'event_type'. We propose only when a surprise is
    present AND at least one horizon has a valid response.
    """
    out: List[ResearchProposal] = []
    for er in event_responses:
        et = er.get("event_type", "EVENT")
        surprise = er.get("surprise")
        if surprise is None:
            continue
        valid = [r for r in er.get("responses", []) if r.get("valid")]
        if not valid:
            continue
        # Find a horizon with non-flat direction to frame a testable relationship.
        moved = [r for r in valid if r.get("direction") in ("UP", "DOWN")]
        if not moved:
            continue
        disc = f"{et}:{surprise:+.3f}".replace("/", "_")
        key = _key(instrument, "EVENT_RESPONSE", disc)
        horizons = ", ".join(r["horizon"] for r in moved)
        out.append(ResearchProposal(
            proposal_key=key, instrument=instrument, kind="EVENT_RESPONSE",
            claim=(f"When {et} surprise is {surprise:+.3f}, {instrument} shows a non-flat "
                   f"response at horizons [{horizons}]. This association may be exploitable "
                   f"if it persists out-of-sample net of cost."),
            new_information=(f"External fundamental surprise ({et}={surprise:+.3f}) linked "
                             f"to an observed post-release move in {instrument}."),
            why_different=("Prior knowledge was price-derived only; this ties a "
                           "fundamental SURPRISE (external information) to response."),
            market_relevance=(f"Event-driven response in {instrument} can precede/represent "
                              f"regime shifts not captured by price-only features."),
            data_requirements=[
                f"Point-in-time (as-of) {et} actual+consensus history",
                f"Intraday {instrument} bars covering each event+horizon without gaps",
                "Release timestamps in UTC aligned to bar timestamps",
                "Purged/embargoed walk-forward split by event",
            ],
            hypothesis=(f"H0: {et} surprise has zero association with {instrument} forward "
                        f"return at these horizons. H1: non-zero, stable association."),
            falsification_criteria=("Reject H1 if OOS association is insignificant or "
                                    "sign-flips across folds/years, or net-of-cost expectancy "
                                    "CI-lower <= 0."),
            leakage_risks=_leakage_risks_common(),
            governance_status="ALLOWED", governance_note=_gov_note(),
            evidence={"event_response": er},
        ))
    return out


def proposals_from_cb_shift(policy_change: Dict[str, object], *, instrument: str
                            ) -> List[ResearchProposal]:
    """Propose research when a central-bank document shows a clear policy shift."""
    shift = policy_change.get("policy_shift", "UNCHANGED")
    if shift in ("UNCHANGED", "UNKNOWN"):
        return []
    inst = policy_change.get("institution", "UNKNOWN")
    key = _key(instrument, "CB_SHIFT", f"{inst}:{shift}")
    return [ResearchProposal(
        proposal_key=key, instrument=instrument, kind="CB_SHIFT",
        claim=(f"A {inst} policy shift to {shift} (evidence: new/removed lexicon markers) "
               f"may predict a directional move in {instrument} around/after the statement."),
        new_information=(f"Detected policy-tone shift {shift} at {inst} from document "
                         f"{policy_change.get('latest_published_ts','?')}."),
        why_different=("Central-bank language is EXTERNAL information, not a price "
                       "transformation; prior experiments never conditioned on it."),
        market_relevance=(f"Policy-tone shifts drive rate expectations and thus {instrument}."),
        data_requirements=[
            f"{inst} statement/minutes archive with publish timestamps",
            f"{instrument} intraday bars around each release",
            "Consensus rate-expectation proxy (documented source)",
            "Purged/embargoed event-based split",
        ],
        hypothesis=(f"H0: {inst} tone shift {shift} has no forward association with "
                    f"{instrument}. H1: stable directional association exists."),
        falsification_criteria=("Reject H1 if the sign or magnitude is unstable across "
                                "folds or the net effect is indistinguishable from zero."),
        leakage_risks=_leakage_risks_common(),
        governance_status="ALLOWED", governance_note=_gov_note(),
        evidence={"policy_change": policy_change},
    )]


def proposals_from_xmarket_breakdown(breakdown: Dict[str, object], *, instrument: str
                                     ) -> List[ResearchProposal]:
    """Propose research when a cross-market relationship breaks down (regime-dependence)."""
    if not breakdown.get("available") or not breakdown.get("breakdown"):
        return []
    pair_a = breakdown.get("pair_a", "?")
    pair_b = breakdown.get("pair_b", "?")
    key = _key(instrument, "XMARKET_BREAKDOWN", f"{pair_a}_{pair_b}")
    return [ResearchProposal(
        proposal_key=key, instrument=instrument, kind="XMARKET_BREAKDOWN",
        claim=(f"The correlation between {pair_a} and {pair_b} is regime-dependent "
               f"(span={breakdown.get('span')}, sign_flips={breakdown.get('sign_flips')}); "
               f"a regime-conditioned relationship with {instrument} warrants testing."),
        new_information=(f"Rolling-correlation instability detected between {pair_a} and "
                         f"{pair_b}."),
        why_different=("Regime-conditional cross-asset linkage is external-structural "
                       "information; prior price-only features ignored regime breaks."),
        market_relevance=(f"Correlation breakdowns can change how {instrument} transmits "
                          f"information from {pair_a}/{pair_b}."),
        data_requirements=[
            f"Aligned price series for {pair_a}, {pair_b}, {instrument}",
            "A documented regime/volatility proxy",
            "Rolling windows with no look-ahead",
            "Purged/embargoed walk-forward split",
        ],
        hypothesis=(f"H0: {pick(instrument)} association with the {pair_a}-{pair_b} "
                    f"relationship is regime-invariant. H1: it is regime-dependent."),
        falsification_criteria=("Reject H1 if regime-conditioned associations are not "
                                "significant OOS or do not survive net of cost."),
        leakage_risks=_leakage_risks_common(),
        governance_status="ALLOWED", governance_note=_gov_note(),
        evidence={"breakdown": breakdown},
    )]


def pick(x: str) -> str:  # tiny helper kept for message clarity
    return x


def discover_new_information(*, instrument: str,
                             event_responses: Optional[List[Dict]] = None,
                             policy_changes: Optional[List[Dict]] = None,
                             breakdowns: Optional[List[Dict]] = None
                             ) -> List[ResearchProposal]:
    """Aggregate all proposal rules, deterministically ordered."""
    proposals: List[ResearchProposal] = []
    proposals += proposals_from_event_responses(event_responses or [], instrument=instrument)
    for pc in (policy_changes or []):
        proposals += proposals_from_cb_shift(pc, instrument=instrument)
    for bd in (breakdowns or []):
        proposals += proposals_from_xmarket_breakdown(bd, instrument=instrument)
    # de-dup by proposal_key, keep first
    seen, unique = set(), []
    for p in proposals:
        if p.proposal_key in seen:
            continue
        seen.add(p.proposal_key)
        unique.append(p)
    priority = {"EVENT_RESPONSE": 0, "CB_SHIFT": 1, "XMARKET_BREAKDOWN": 2}
    unique.sort(key=lambda p: (priority.get(p.kind, 99), p.proposal_key))
    return unique


def proposal_content_key(proposal: ResearchProposal) -> str:
    payload = f"{proposal.proposal_key}|{proposal.claim}|{proposal.lane}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()
