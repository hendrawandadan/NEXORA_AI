"""Tahap C — Pre-registration registry + deterministic experiment-spec builder.

Ties the hypothesis generator (hypothesis_generator.py) to the Knowledge Memory
(store.py) through an explicit, auditable pre-registration flow:

    generate_hypotheses(...)            # rules fire on evidence
        -> pre_register(hyp)            # persists PRE_REGISTERED + signature
        -> build_experiment_spec(hyp)   # deterministic, frozen spec (hashed)
        -> create_experiment(...)       # persists CREATED experiment bound to hyp

Everything is deterministic and hash-bound, so the spec can never be silently
changed after seeing results. No training, no production writes.

The hypothesis signature (instrument|timeframe|horizon) is embedded into the
stored hypothesis evidence via a parallel DEAD_END/CONSTRAINT record only upon
failure; here we simply expose the signature in the hypothesis go_criteria so it
is discoverable by knowledge_query.dead_end_signatures through the failure path.
"""

from __future__ import annotations

import json
from typing import Dict, List, Optional

from .hypothesis_generator import GeneratedHypothesis
from .store import ResearchMemoryStore


def pre_register(
    store: ResearchMemoryStore,
    hyp: GeneratedHypothesis,
) -> Dict[str, object]:
    """Persist a generated hypothesis as PRE_REGISTERED (content-hashed).

    The generator's signature is preserved inside go_criteria (as
    ``signature``) so it travels with the immutable content hash and can be matched
    by failure records later.
    """
    go = dict(hyp.go_criteria)
    go["signature"] = hyp.signature
    go["rule_id"] = hyp.rule_id
    # R1: lane is a first-class column. It travels in go_criteria (the external bridge
    # sets INFO_ACQUISITION; price-derived generator output defaults to PRICE_DERIVED).
    lane = go.get("lane", "PRICE_DERIVED")
    return store.register_hypothesis(
        hypothesis_key=hyp.hypothesis_key,
        instrument=hyp.instrument,
        timeframe=hyp.timeframe,
        horizon_bars=hyp.horizon_bars,
        claim=hyp.claim,
        market_condition=hyp.market_condition,
        signal_source=hyp.signal_source,
        go_criteria=go,
        status="PRE_REGISTERED",
        lane=lane,
    )


def build_experiment_spec(
    hyp: GeneratedHypothesis,
    *,
    dataset_path: Optional[str] = None,
    cost_scenarios: Optional[List[Dict[str, object]]] = None,
    split: Optional[Dict[str, object]] = None,
    target_type: str = "T3",
    engine: str = "auto",
    seed: int = 42,
) -> Dict[str, object]:
    """Build a deterministic experiment spec from a hypothesis.

    The spec is the exact recipe that will be executed. Defaults are explicit and
    frozen; the spec is hashed by store.create_experiment so any later edit is
    detectable.
    """
    return {
        "hypothesis_key": hyp.hypothesis_key,
        "signature": hyp.signature,
        "instrument": hyp.instrument,
        "timeframe": hyp.timeframe,
        "horizon_bars": hyp.horizon_bars,
        "rule_id": hyp.rule_id,
        "target_type": target_type,
        "dataset_path": dataset_path,
        "engine": engine,
        "seed": seed,
        "split": split or {"train_fraction": 0.6, "validation_fraction": 0.2,
                           "embargo_bars": 24},
        "cost_scenarios": cost_scenarios or [
            {"name": "optimistic", "spread_pips": 1.5, "slippage_pips": 0.2},
            {"name": "baseline", "spread_pips": 3.0, "slippage_pips": 0.2},
            {"name": "stress", "spread_pips": 4.8, "slippage_pips": 0.5},
        ],
        "pre_registered_go_criteria": hyp.go_criteria,
        "evidence_at_spec": hyp.evidence,
    }


def register_experiment_for(
    store: ResearchMemoryStore,
    registered_hypothesis_id: int,
    hyp: GeneratedHypothesis,
    *,
    experiment_key: Optional[str] = None,
    spec_overrides: Optional[Dict[str, object]] = None,
) -> Dict[str, object]:
    """Create a deterministic experiment bound to an already-registered hypothesis."""
    spec = build_experiment_spec(hyp)
    if spec_overrides:
        spec.update(spec_overrides)
    key = experiment_key or f"exp:{hyp.hypothesis_key}"
    return store.create_experiment(
        experiment_key=key,
        hypothesis_id=registered_hypothesis_id,
        spec=spec,
        status="CREATED",
    )


def generate_and_register(
    store: ResearchMemoryStore,
    *,
    instrument: str,
    horizon_evidence: dict,
    feature_power_evidence: Optional[dict] = None,
    allow_dead_ends: bool = False,
    dry_run: bool = False,
) -> List[Dict[str, object]]:
    """End-to-end: generate -> (optionally) pre-register + create experiment.

    Returns a list of result dicts; when ``dry_run`` no DB rows are written.
    Duplicate hypotheses (same content hash) are reported, not crashed on.
    """
    from .hypothesis_generator import generate_hypotheses

    hyps = generate_hypotheses(
        instrument=instrument,
        horizon_evidence=horizon_evidence,
        feature_power_evidence=feature_power_evidence,
        store=store,
        allow_dead_ends=allow_dead_ends,
    )
    out: List[Dict[str, object]] = []
    for hyp in hyps:
        rec: Dict[str, object] = {"hypothesis": hyp.as_dict()}
        if dry_run:
            rec["registered"] = False
            out.append(rec)
            continue
        try:
            h = pre_register(store, hyp)
            e = register_experiment_for(store, h["id"], hyp)
            rec.update({"registered": True, "hypothesis_id": h["id"],
                        "experiment_id": e["id"], "spec_sha256": e["spec_sha256"]})
        except ValueError as exc:
            rec.update({"registered": False, "skipped_reason": str(exc)})
        out.append(rec)
    return out
