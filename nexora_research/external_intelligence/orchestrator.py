"""Orchestrator: one-call External Information Intelligence run.

Ties the full pipeline together for a single instrument:

    registry -> (connectors fetch, mock/real) -> repository (persist raw)
    -> intelligence (fundamentals / central bank / news / cross-market / responses)
    -> new information discovery (proposals)
    -> research bridge (persist + optional gated pre-registration)

SAFETY: defaults are DRY / offline. The orchestrator NEVER trains, evaluates for profit,
promotes, trades, or reopens lanes. It returns a structured ``IntelReport`` that states
exactly what was learned and -- crucially -- the HONEST bottom line: any external
information or event-response relationships found are UNVALIDATED research leads, not
evidence of trading edge.

This module performs I/O only through the isolated repository and (optionally) the
research memory store. It does not touch production.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Dict, List, Optional

from . import (
    central_bank_intelligence as cbi,
    connectors as cx,
    cross_market_intelligence as xm,
    event_response as er,
    fundamental_intelligence as fi,
    news_intelligence as ni,
    new_information as nii,
    research_bridge as rb,
    source_registry as sr,
)
from .config import DEFAULT_CONFIG, ExternalIntelConfig
from .repository import ExternalKnowledgeRepository


def _utcnow() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


@dataclass
class IntelReport:
    instrument: str
    dry_run: bool
    providers_known: int
    connectors: Dict[str, str]
    events_ingested: int = 0
    central_bank_docs: int = 0
    news_records: int = 0
    findings: int = 0
    cross_market_observations: int = 0
    event_responses: int = 0
    proposals: int = 0
    proposals_prepared: int = 0
    governance_status: str = "ALLOWED"
    notes: List[str] = field(default_factory=list)
    bottom_line: str = ""
    # Not serialized into as_dict(); exposes the discovered ResearchProposal objects so
    # callers (e.g. strategy_evolution new-info acquisition) can route them explicitly.
    discovered_proposals: List[object] = field(default_factory=list, repr=False)

    def as_dict(self) -> Dict[str, object]:
        return {
            "instrument": self.instrument,
            "dry_run": self.dry_run,
            "providers_known": self.providers_known,
            "connectors": self.connectors,
            "events_ingested": self.events_ingested,
            "central_bank_docs": self.central_bank_docs,
            "news_records": self.news_records,
            "findings": self.findings,
            "cross_market_observations": self.cross_market_observations,
            "event_responses": self.event_responses,
            "proposals": self.proposals,
            "proposals_prepared": self.proposals_prepared,
            "governance_status": self.governance_status,
            "notes": self.notes,
            "bottom_line": self.bottom_line,
        }


HONEST_BOTTOM_LINE = (
    "External-intelligence layer operates and discovers relationships, but NO evidence of "
    "a stable, net-of-cost predictive edge has been established. All event-response / "
    "cross-market / fundamental associations are UNVALIDATED research leads requiring "
    "pre-registered, leakage-controlled, walk-forward validation with human authorization. "
    "This system does not train, trade, promote, or reopen the price-derived lane."
)


def _ingest_events(repo: ExternalKnowledgeRepository, events: List[Dict[str, object]],
                   report: IntelReport) -> List[Dict[str, object]]:
    stored = []
    for ev in events:
        et = str(ev.get("event_type", ""))
        meta = fi.classify_event(et)
        try:
            r = repo.insert_economic_event(
                event_type=et,
                country=str(ev.get("country", "")),
                currency=str(ev.get("currency", meta.get("currency", ""))),
                scheduled_ts=str(ev["scheduled_ts"]),
                source_provider=str(ev.get("source_provider", "mock")),
                retrieved_at_utc=str(ev.get("retrieved_at_utc", _utcnow())),
                economic_domain=str(ev.get("economic_domain", meta.get("domain", ""))),
                importance=str(ev.get("importance", meta.get("importance", "UNKNOWN"))),
                period=str(ev.get("period", "")),
                actual=ev.get("actual"), forecast=ev.get("forecast"),
                previous=ev.get("previous"), revised_previous=ev.get("revised_previous"),
                unit=str(ev.get("unit", meta.get("unit", ""))),
                source_ref=str(ev.get("source_ref", "")),
                data_quality=str(ev.get("data_quality", "UNVERIFIED")),
                is_synthetic=bool(ev.get("is_synthetic", ev.get("provenance") == "SYNTHETIC")),
                # R2 (PIT): forward source-provided availability/vintage only; never invented.
                published_at_utc=ev.get("published_at_utc"),
                available_at_utc=ev.get("available_at_utc"),
                vintage=ev.get("vintage"),
                revision_as_of_utc=ev.get("revision_as_of_utc"),
            )
            report.events_ingested += 1 if r.get("inserted") else 0
            row = repo.get_event(r["id"]) if r.get("id") else None
            if row:
                stored.append(row)
        except (ValueError, KeyError) as exc:
            report.notes.append(f"event rejected ({et}): {exc}")
    return stored


def run_intelligence(
    *,
    instrument: str,
    repo: Optional[ExternalKnowledgeRepository] = None,
    research_store=None,
    config: ExternalIntelConfig = DEFAULT_CONFIG,
    events: Optional[List[Dict[str, object]]] = None,
    central_bank_docs: Optional[List[Dict[str, object]]] = None,
    news: Optional[List[Dict[str, object]]] = None,
    price_bars: Optional[List[Dict]] = None,
    cross_market_pairs: Optional[List[Dict]] = None,
    register: bool = False,
    record_raw_snapshot: bool = True,
) -> IntelReport:
    """Run the pipeline over supplied (already-fetched) external data.

    This function takes EXTERNAL data the caller has already obtained (via a connector
    or fixtures). It performs normalisation, persistence, intelligence, discovery, and
    optionally gated pre-registration. It is deterministic given the same inputs.
    """
    own_repo = repo is None
    if own_repo:
        repo = ExternalKnowledgeRepository()  # default isolated DB path

    report = IntelReport(
        instrument=instrument, dry_run=config.dry_run,
        providers_known=len(sr.all_providers()),
        connectors=cx.connector_status(config),
    )

    if record_raw_snapshot:
        for pid, status in report.connectors.items():
            try:
                prov = None
                try:
                    prov = sr.get_provider(pid)
                except KeyError:
                    prov = None
                repo.insert_source_snapshot(
                    provider_id=pid, tier=prov.tier if prov else 0,
                    connector_available=bool(prov.connector_available) if prov else False,
                    access_status=status, captured_at_utc=_utcnow())
            except Exception:
                pass

    # ---- Ingest events + interpret ----
    stored_events = _ingest_events(repo, events or [], report)
    event_responses_input: List[Dict[str, object]] = []
    for row in stored_events:
        interp = fi.interpret_event(row)
        repo.insert_fundamental_finding(
            subject=f"{row['event_type']}:{row['country']}:{row['scheduled_ts']}",
            interpretation=interp.interpretation, created_at_utc=_utcnow(),
            direction=interp.direction, confidence=interp.confidence,
            event_id=row["id"], surprise=interp.surprise,
            implications=interp.implications, evidence=interp.evidence,
            source_ids=interp.source_ids,
            is_synthetic=bool(row.get("is_synthetic")))
        report.findings += 1

        # ---- Event response (if bars available) ----
        if price_bars:
            # R2 (PIT): use the source-provided availability time (if any) as the
            # anti-leakage basis so a period-style scheduled_ts cannot leak future data.
            available_at = row.get("available_at_utc")
            resp = er.measure_event_response(
                event_id=row["id"], event_ts=str(row["scheduled_ts"]),
                instrument=instrument, bars=price_bars,
                available_at=str(available_at) if available_at else None)
            for hr in resp.responses:
                repo.insert_event_response(
                    event_id=row["id"], instrument=instrument, horizon=hr.horizon,
                    horizon_minutes=hr.horizon_minutes, valid=hr.valid,
                    computed_at_utc=_utcnow(), pre_price=hr.pre_price,
                    post_price=hr.post_price, return_pct=hr.return_pct,
                    direction=hr.direction, note=hr.note,
                    as_of_utc=resp.basis_ts,
                    event_available_at_utc=resp.event_available_at)
                report.event_responses += 1
            enriched = resp.as_dict()
            enriched["event_type"] = row["event_type"]
            enriched["surprise"] = interp.surprise
            # R2 (PIT): propagate the event's PIT markers so the proposal carries them.
            enriched["pit_verified"] = row.get("pit_verified")
            enriched["data_quality"] = row.get("data_quality")
            enriched["is_synthetic"] = row.get("is_synthetic")
            event_responses_input.append(enriched)

    # ---- Central bank ----
    policy_changes: List[Dict[str, object]] = []
    by_inst: Dict[str, List[Dict[str, object]]] = {}
    for d in (central_bank_docs or []):
        try:
            r = repo.insert_central_bank_doc(
                institution=str(d["institution"]), doc_type=str(d.get("doc_type", "STATEMENT")),
                title=str(d.get("title", "")), published_ts=str(d["published_ts"]),
                source_provider=str(d.get("source_provider", "mock")),
                source_ref=str(d["source_ref"]), body_text=str(d.get("body_text", "")),
                retrieved_at_utc=str(d.get("retrieved_at_utc", _utcnow())),
                tone=cbi.assess_tone(d.get("body_text", "")).tone,
                tone_confidence=cbi.assess_tone(d.get("body_text", "")).confidence,
                summary=str(d.get("summary", "")),
                is_synthetic=bool(d.get("is_synthetic", False)))
            report.central_bank_docs += 1 if r.get("inserted") else 0
            by_inst.setdefault(str(d["institution"]), []).append(d)
        except (ValueError, KeyError) as exc:
            report.notes.append(f"cb doc rejected: {exc}")
    for inst, docs in by_inst.items():
        docs_sorted = sorted(docs, key=lambda x: str(x.get("published_ts", "")))
        if len(docs_sorted) >= 2:
            pc = cbi.detect_policy_change(docs_sorted[-1], docs_sorted[-2])
            policy_changes.append(pc.as_dict())

    # ---- News ----
    for n in (news or []):
        try:
            cls = ni.classify_news(str(n["headline"]), str(n.get("body", "")),
                                   source_provider=str(n.get("source_provider", "mock")),
                                   impact_hint=n.get("impact"))
            r = repo.insert_news(
                headline=str(n["headline"]), category=cls.category,
                published_ts=str(n["published_ts"]),
                source_provider=str(n.get("source_provider", "mock")),
                retrieved_at_utc=str(n.get("retrieved_at_utc", _utcnow())),
                currencies=cls.currencies, countries=cls.countries,
                entities=cls.entities, impact=cls.impact,
                source_ref=str(n.get("source_ref", "")),
                reliability=cls.reliability,
                is_synthetic=bool(n.get("is_synthetic", False)))
            report.news_records += 1 if r.get("inserted") else 0
        except (ValueError, KeyError) as exc:
            report.notes.append(f"news rejected: {exc}")

    # ---- Cross-market ----
    breakdowns: List[Dict[str, object]] = []
    for cm in (cross_market_pairs or []):
        a = xm.correlation(cm.get("pair_a", "A"), cm.get("series_a", []),
                           cm.get("pair_b", "B"), cm.get("series_b", []),
                           min_observations=config.min_observations)
        if cm.get("series_a") and cm.get("series_b") and a.available:
            repo.insert_cross_market_observation(
                pair_a=a.pair_a, pair_b=a.pair_b, method="correlation", value=a.value or 0.0,
                n_obs=a.n_obs, computed_at_utc=_utcnow(), caveat=a.caveat)
            report.cross_market_observations += 1
            roll = xm.rolling_correlation(a.pair_a, cm.get("series_a", []),
                                          a.pair_b, cm.get("series_b", []),
                                          window=config.rolling_correlation_window)
            if roll.available:
                bd = xm.detect_correlation_breakdown(roll)
                breakdowns.append(bd)

    # ---- New information discovery ----
    proposals = nii.discover_new_information(
        instrument=instrument, event_responses=event_responses_input,
        policy_changes=policy_changes, breakdowns=breakdowns)
    report.proposals = len(proposals)
    report.discovered_proposals = list(proposals)

    # ---- Research bridge ----
    for p in proposals:
        res = rb.route_to_research_memory(
            repo, p, research_store=research_store, register=register)
        if res.hypothesis_prepared:
            report.proposals_prepared += 1
        if res.governance_status != "ALLOWED":
            report.governance_status = res.governance_status
        if not res.persisted:
            report.notes.append(f"proposal persist skipped: {res.reason}")

    report.bottom_line = HONEST_BOTTOM_LINE
    return report
