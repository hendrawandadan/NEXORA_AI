"""Discovery-only job handlers for the research scheduler (Item 2.5, Phase 2).

Each handler runs ONE unit of research work and returns a structured result dict. The
handlers are the ONLY place the scheduler actually calls research components:

  * RESEARCH_CYCLE   -> nexora_research.control_loop.run_control_loop
  * INFO_ACQUISITION -> nexora_research.external_intelligence (orchestrator) +
                        research_bridge / control_loop intake
  * STRATEGY_EVOLUTION -> nexora_research.strategy_evolution.evolve_proposals

HARD GUARANTEES (every handler):
  * Discovery-only. NONE of them trains, tunes, promotes a model, enables live trading,
    or reopens a lane. They only produce research decisions / leads / proposals.
  * Dry-run by default. With ``dry_run=True`` they persist nothing (control loop dry_run,
    orchestrator dry_run, evolution record_proposals=False).
  * Inputs (external data) are supplied by the caller. With ``use_mock_provider=True``
    a small deterministic in-memory mock provider is used — NO live network I/O.
  * Governance + PIT gating happens in ``safety.combined_preflight`` BEFORE the handler;
    a handler also defensively refuses to register/route anything not ALLOWED.

A handler that hits a governance/PIT block should return
``{"_blocked": reason, ...}`` so the scheduler marks the job BLOCKED (terminal). Errors
raise and are turned into FAILED/RETRY by the queue.
"""

from __future__ import annotations

from typing import Dict, List

from . import config as cfg


# ---------------------------------------------------------------------------
# Mock provider (deterministic; used by tests / offline dry runs).
# ---------------------------------------------------------------------------
def mock_external_inputs(instrument: str) -> Dict[str, object]:
    """Deterministic mock external-intelligence inputs (NO network)."""
    return {
        "events": [
            {"event_type": "CPI", "country": "US", "currency": "USD",
             "scheduled_ts": "2026-01-15T13:30:00Z", "actual": 3.2, "forecast": 2.9,
             "previous": 3.0, "unit": "%", "source_provider": "mock",
             "source_ref": "mock://cpi", "data_quality": "UNVERIFIED",
             "is_synthetic": True},
        ],
        "central_bank_docs": [
            {"institution": "FED", "doc_type": "STATEMENT", "title": "mock statement 1",
             "published_ts": "2026-01-10T18:00:00Z", "source_provider": "mock",
             "source_ref": "mock://fed1", "body_text": "The Committee sees inflation "
             "risks and may tighten policy going forward."},
            {"institution": "FED", "doc_type": "STATEMENT", "title": "mock statement 2",
             "published_ts": "2026-02-10T18:00:00Z", "source_provider": "mock",
             "source_ref": "mock://fed2", "body_text": "The Committee will be patient "
             "and accommodative; growth is slowing."},
        ],
        "news": [
            {"headline": "Inflation surprise lifts dollar", "published_ts":
             "2026-01-15T13:35:00Z", "source_provider": "mock",
             "body": "CPI came in above consensus, supporting Fed tightening."},
        ],
        "instrument": instrument,
    }


# ---------------------------------------------------------------------------
# RESEARCH_CYCLE handler.
# ---------------------------------------------------------------------------
def run_research_cycle(payload: Dict[str, object], *, dry_run: bool = True,
                       store=None) -> Dict[str, object]:
    """Run the research control loop for one instrument (discovery-only)."""
    from nexora_research.control_loop import run_control_loop

    instrument = str(payload.get("instrument", ""))
    if not instrument:
        raise ValueError("RESEARCH_CYCLE requires payload.instrument")
    horizon_evidence = payload.get("horizon_evidence") or {}
    feature_power = payload.get("feature_power_evidence")
    timeframe = str(payload.get("timeframe", ""))

    report = run_control_loop(
        instrument=instrument,
        horizon_evidence=horizon_evidence,
        feature_power_evidence=feature_power,
        store=store,
        dry_run=dry_run,
        timeframe=timeframe,
    )
    return {
        "job_kind": cfg.JOB_RESEARCH_CYCLE,
        "instrument": instrument,
        "dry_run": dry_run,
        "max_verdict": report.max_verdict,
        "phases_visited": list(report.phases_visited),
        "outcomes": [o.as_dict() for o in report.outcomes],
        "notes": list(report.notes),
    }


# ---------------------------------------------------------------------------
# INFO_ACQUISITION handler.
# ---------------------------------------------------------------------------
def run_info_acquisition(payload: Dict[str, object], *, dry_run: bool = True,
                         store=None, use_mock_provider: bool = True,
                         external_repo=None,
                         rate_limiter=None) -> Dict[str, object]:
    """Run external-intelligence acquisition + route proposals through the loop.

    Discovery-only. In dry_run nothing is persisted. Uses the mock provider unless the
    caller supplies real (already-fetched) inputs in the payload.
    """
    from nexora_research.external_intelligence import orchestrator
    from nexora_research.external_intelligence.config import ExternalIntelConfig

    instrument = str(payload.get("instrument", ""))
    if not instrument:
        raise ValueError("INFO_ACQUISITION requires payload.instrument")

    # Provider rate limit (configurable). Blocked acquisition is reported, not crashed.
    if rate_limiter is not None:
        provider = "mock" if use_mock_provider else str(payload.get("provider", "default"))
        if not rate_limiter.try_acquire(provider):
            return {"job_kind": cfg.JOB_INFO_ACQUISITION, "instrument": instrument,
                    "executed": False, "rate_limited": True,
                    "reason": f"provider {provider} rate-limited"}

    # Build inputs: explicit payload wins, else mock provider.
    if payload.get("events") or payload.get("central_bank_docs") or payload.get("news"):
        inputs = {k: payload.get(k) for k in
                  ("events", "central_bank_docs", "news", "price_bars", "cross_market_pairs")}
    elif use_mock_provider:
        inputs = mock_external_inputs(instrument)
    else:
        raise ValueError("INFO_ACQUISITION with non-mock provider requires explicit inputs")

    config = ExternalIntelConfig(dry_run=dry_run)
    repo = external_repo
    if repo is None and not dry_run:
        from nexora_research.external_intelligence.repository import ExternalKnowledgeRepository
        repo = ExternalKnowledgeRepository()

    intel = orchestrator.run_intelligence(
        instrument=instrument, repo=repo, research_store=store, config=config,
        events=inputs.get("events"), central_bank_docs=inputs.get("central_bank_docs"),
        news=inputs.get("news"), price_bars=inputs.get("price_bars"),
        cross_market_pairs=inputs.get("cross_market_pairs"),
        register=False, record_raw_snapshot=not dry_run,
    )
    proposals = list(getattr(intel, "discovered_proposals", []) or [])

    loop_max_verdict = ""
    loop_outcomes: List[Dict[str, object]] = []
    # Route discovered proposals through the canonical control loop (governance + PIT
    # gates run per-proposal inside the loop). Only when there is something to route.
    if proposals:
        from nexora_research.control_loop import run_control_loop
        loop_report = run_control_loop(
            instrument=instrument, horizon_evidence=None, store=store,
            dry_run=dry_run, external_proposals=proposals)
        loop_max_verdict = loop_report.max_verdict
        loop_outcomes = [o.as_dict() for o in loop_report.outcomes]

    return {
        "job_kind": cfg.JOB_INFO_ACQUISITION,
        "instrument": instrument,
        "dry_run": dry_run,
        "executed": True,
        "used_mock_provider": use_mock_provider,
        "intel_report": intel.as_dict(),
        "external_proposals": len(proposals),
        "loop_max_verdict": loop_max_verdict,
        "loop_outcomes": loop_outcomes,
    }


# ---------------------------------------------------------------------------
# STRATEGY_EVOLUTION handler.
# ---------------------------------------------------------------------------
def run_strategy_evolution(payload: Dict[str, object], *, dry_run: bool = True,
                           store=None) -> Dict[str, object]:
    """Derive evolution proposals from Knowledge Memory (discovery-only).

    ``record_proposals`` is forced False when nothing is persisted (dry run) and is only
    honoured when an explicit non-dry store is supplied. Proposals NEVER train/evaluate.
    """
    if store is None:
        # No memory to reason over — return an explicit empty result.
        return {"job_kind": cfg.JOB_STRATEGY_EVOLUTION, "dry_run": dry_run,
                "proposals": [], "count": 0,
                "note": "no research store supplied"}
    from nexora_research.strategy_evolution import evolve_proposals
    candidate_instruments = payload.get("candidate_instruments")
    proposals = evolve_proposals(
        store, candidate_instruments=candidate_instruments,
        record_proposals=(not dry_run))
    return {
        "job_kind": cfg.JOB_STRATEGY_EVOLUTION,
        "dry_run": dry_run,
        "count": len(proposals),
        "proposals": [p.as_dict() for p in proposals],
    }


# ---------------------------------------------------------------------------
# Dispatch.
# ---------------------------------------------------------------------------
HANDLERS = {
    cfg.JOB_RESEARCH_CYCLE: run_research_cycle,
    cfg.JOB_INFO_ACQUISITION: run_info_acquisition,
    cfg.JOB_STRATEGY_EVOLUTION: run_strategy_evolution,
}


def dispatch(job_kind: str, payload: Dict[str, object], *, dry_run: bool = True,
             store=None, use_mock_provider: bool = True, external_repo=None,
             rate_limiter=None) -> Dict[str, object]:
    """Dispatch a job to its handler. Only the three discovery-only kinds are allowed."""
    kind = (job_kind or "").strip().upper()
    if kind in cfg.FORBIDDEN_JOB_KINDS:
        raise ValueError(f"forbidden job kind {job_kind!r}: DISCOVERY-ONLY scheduler")
    handler = HANDLERS.get(kind)
    if handler is None:
        raise ValueError(f"unknown job kind {job_kind!r}")
    if kind == cfg.JOB_INFO_ACQUISITION:
        return handler(payload, dry_run=dry_run, store=store,
                       use_mock_provider=use_mock_provider, external_repo=external_repo,
                       rate_limiter=rate_limiter)
    return handler(payload, dry_run=dry_run, store=store)
