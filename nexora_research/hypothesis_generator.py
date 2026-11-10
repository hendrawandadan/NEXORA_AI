"""Tahap C — Deterministic, evidence-based hypothesis generator.

Given the measured output of the discovery stages (horizon economics, feature
power) plus the Knowledge Memory, produce a ranked list of STRUCTURED, FALSIFIABLE
hypotheses, each with pre-registered GO criteria. No LLM, no free-form invention:
every hypothesis is a rule fired by concrete evidence, so it is auditable and
reproducible.

Rules (each hypothesis names its `rule_id` and the evidence that fired it):

  R_HORIZON_FEASIBLE
      Fire for each (timeframe, horizon) whose move/cost ratio clears a threshold
      AND whose required symmetric accuracy is realistically reachable.

  R_FEATURE_INFO
      Fire when the OOS feature-power shows at least one usable feature.

  R_CROSS_TF_AGREEMENT
      Fire when the same wall-clock horizon across timeframes shows consistent move
      size (data coherence), justifying a cross-tf robustness hypothesis.

Guardrails:
  * Deterministic: same inputs -> same hypotheses (stable ordering).
  * Falsifiable: every hypothesis has explicit GO criteria (thresholds + metric).
  * Skip dead-ends: signatures already recorded as DEAD_END are not re-emitted
    unless `allow_dead_ends=True` (an explicit "changed" decision by caller).

This module is PURE with respect to discovery inputs; it only READS the store to
avoid repeats. It does not register anything itself -- see registry.py for that.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional

from .knowledge_query import dead_end_signatures
from .store import ResearchMemoryStore

# Explicit thresholds (documented; not magic).
FEASIBLE_RATIO_MIN = 5.0           # move/cost must clear 5x to be worth a test
REACHABLE_ACC_MAX = 0.62           # required symmetric accuracy <= 62% to be plausible
FEATURE_MIN_ABS_IC = 0.02          # same bar as feature_power.min_ic_to_keep
CROSS_TF_MEDIAN_TOL_PIPS = 1.0     # same wall-clock move within 1 pip across TFs


@dataclass
class GeneratedHypothesis:
    hypothesis_key: str
    rule_id: str
    instrument: str
    timeframe: str
    horizon_bars: int
    claim: str
    signal_source: str
    market_condition: str
    go_criteria: Dict[str, object]
    evidence: Dict[str, object] = field(default_factory=dict)

    @property
    def signature(self) -> str:
        return f"{self.instrument}|{self.timeframe}|{self.horizon_bars}"

    def as_dict(self) -> Dict[str, object]:
        return {
            "hypothesis_key": self.hypothesis_key,
            "rule_id": self.rule_id,
            "instrument": self.instrument,
            "timeframe": self.timeframe,
            "horizon_bars": self.horizon_bars,
            "claim": self.claim,
            "signal_source": self.signal_source,
            "market_condition": self.market_condition,
            "go_criteria": self.go_criteria,
            "evidence": self.evidence,
            "signature": self.signature,
        }


def _go_criteria_for_horizon(required_acc: float, ratio: float) -> Dict[str, object]:
    """Pre-registered GO bar for a horizon-feasibility experiment.

    GO iff OOS directional accuracy >= required_acc + margin AND a bootstrap CI on
    net expectancy has a positive lower bound. Thresholds are frozen here at
    pre-registration time (no post-hoc tuning).
    """
    margin = 0.01
    return {
        "metric": "oos_directional_accuracy",
        "threshold": round(float(required_acc) + margin, 4),
        "secondary_metric": "net_expectancy_pips_ci_lower",
        "secondary_threshold": 0.0,
        "cost_included": True,
        "move_to_cost_ratio_at_gen": round(float(ratio), 4),
    }


def _horizon_econ_by_tf(horizon_evidence: dict) -> Dict[str, List[dict]]:
    """Normalise horizon evidence to {tf: [economics rows]}.

    Accepts either a single timeframe dict (with 'economics') or a top-level
    dict {'timeframes': {tf: {'economics': [...]}}}, matching
    run_horizon_discovery output shape.
    """
    out: Dict[str, List[dict]] = {}
    if not horizon_evidence:
        return out
    if "timeframes" in horizon_evidence and isinstance(horizon_evidence["timeframes"], dict):
        for tf, t in horizon_evidence["timeframes"].items():
            econ = t.get("economics") if isinstance(t, dict) else None
            if econ:
                out[tf] = econ
        return out
    econ = horizon_evidence.get("economics")
    tf = horizon_evidence.get("timeframe")
    if econ and tf:
        out[tf] = econ
    return out


def generate_hypotheses(
    *,
    instrument: str,
    horizon_evidence: dict,
    feature_power_evidence: Optional[dict] = None,
    store: Optional[ResearchMemoryStore] = None,
    allow_dead_ends: bool = False,
) -> List[GeneratedHypothesis]:
    """Deterministically generate ranked hypotheses from measured evidence."""
    hyps: List[GeneratedHypothesis] = []
    dead = set(dead_end_signatures(store)) if store is not None else set()

    def _skip(tf: str, h: int) -> bool:
        return (not allow_dead_ends) and (f"{instrument}|{tf}|{h}" in dead)

    econ_by_tf = _horizon_econ_by_tf(horizon_evidence)

    # ---- R_HORIZON_FEASIBLE ------------------------------------------------
    for tf in sorted(econ_by_tf):
        for row in econ_by_tf[tf]:
            if row.get("scenario") not in (None, "baseline"):
                continue
            ratio = row.get("move_to_cost_ratio")
            req = row.get("required_acc_symmetric")
            h = row.get("horizon_bars")
            if h is None or ratio is None or req is None:
                continue
            if ratio >= FEASIBLE_RATIO_MIN and req <= REACHABLE_ACC_MAX and not _skip(tf, int(h)):
                claim = (
                    f"At {tf} horizon {h} bars, the median move is {ratio:.2f}x the "
                    f"round-trip cost; a directional edge clearing cost may exist if OOS "
                    f"accuracy reaches {req:.3f}."
                )
                hyps.append(GeneratedHypothesis(
                    hypothesis_key=f"gen:{instrument}:{tf}:h{h}:feasible",
                    rule_id="R_HORIZON_FEASIBLE",
                    instrument=instrument, timeframe=tf, horizon_bars=int(h),
                    claim=claim, signal_source="price_move_vs_cost",
                    market_condition=str(row.get("cost_scenario", "baseline")),
                    go_criteria=_go_criteria_for_horizon(req, ratio),
                    evidence={"move_to_cost_ratio": ratio,
                              "required_acc_symmetric": req,
                              "median_move_pips": row.get("median_move_pips")},
                ))

    # ---- R_FEATURE_INFO ----------------------------------------------------
    if feature_power_evidence:
        usable = feature_power_evidence.get("usable_features") or []
        feats = feature_power_evidence.get("features") or []
        best = None
        for f in feats:
            name = f.get("feature")
            ic = f.get("ic")
            if name in usable and isinstance(ic, (int, float)) and abs(ic) >= FEATURE_MIN_ABS_IC:
                if best is None or abs(ic) > abs(best.get("ic", 0)):
                    best = f
        if best is not None:
            tf = feature_power_evidence.get("timeframe", "unknown")
            h = feature_power_evidence.get("horizon_bars")
            name = best["feature"]
            ic = best["ic"]
            key_extra = f"{tf}:h{h}" if h is not None else feature_power_evidence.get("label", "fp")
            if not (h is not None and _skip(tf, int(h))):
                hyps.append(GeneratedHypothesis(
                    hypothesis_key=f"gen:{instrument}:{key_extra}:{name}:info",
                    rule_id="R_FEATURE_INFO",
                    instrument=instrument, timeframe=str(tf),
                    horizon_bars=int(h) if h is not None else 0,
                    claim=(f"Feature '{name}' carries OOS information about signed forward "
                           f"return at {tf}" + (f" horizon {h}" if h is not None else "")
                           + f" (|IC|={abs(ic):.4f})."),
                    signal_source=f"feature:{name}",
                    market_condition="oos_split",
                    go_criteria={
                        "metric": "oos_ic_abs",
                        "threshold": max(FEATURE_MIN_ABS_IC, round(abs(ic) * 0.5, 4)),
                        "secondary_metric": "net_expectancy_pips_ci_lower",
                        "secondary_threshold": 0.0,
                        "cost_included": True,
                    },
                    evidence={"feature": name, "ic": ic,
                              "ic_ci_low": best.get("ic_ci_low"),
                              "ic_ci_high": best.get("ic_ci_high")},
                ))

    # ---- R_CROSS_TF_AGREEMENT ---------------------------------------------
    try:
        from nexora_datahub.loader import timeframe_minutes
    except Exception:  # pragma: no cover
        timeframe_minutes = None
    if timeframe_minutes is not None:
        buckets: Dict[int, List[tuple]] = {}
        for tf in econ_by_tf:
            try:
                tfm = timeframe_minutes(tf)
            except Exception:
                continue
            for row in econ_by_tf[tf]:
                if row.get("scenario") not in (None, "baseline"):
                    continue
                h = row.get("horizon_bars")
                med = row.get("median_move_pips")
                if h is None or med is None:
                    continue
                wall = int(h) * int(tfm)
                buckets.setdefault(wall, []).append((tf, int(h), float(med)))
        for wall in sorted(buckets):
            items = buckets[wall]
            if len(items) < 2:
                continue
            meds = [m for _, _, m in items]
            if (max(meds) - min(meds)) <= CROSS_TF_MEDIAN_TOL_PIPS:
                tfs = "/".join(sorted({tf for tf, _, _ in items}))
                h_list = ",".join(str(h) for _, h, _ in sorted(items))
                key = f"gen:{instrument}:wall{wall}min:cross_tf"
                if any(f"{instrument}|{tf}|{h}" in dead for tf, h, _ in items) and not allow_dead_ends:
                    continue
                hyps.append(GeneratedHypothesis(
                    hypothesis_key=key,
                    rule_id="R_CROSS_TF_AGREEMENT",
                    instrument=instrument, timeframe=tfs,
                    horizon_bars=int(items[0][1]),
                    claim=(f"Across {tfs} the same {wall//60}h wall-clock horizon shows "
                           f"consistent median move (~{sum(meds)/len(meds):.1f} pips), so a "
                           f"robustness hypothesis across timeframes at h={h_list} is justified."),
                    signal_source="cross_timeframe_move_consistency",
                    market_condition=f"wall={wall}min",
                    go_criteria={
                        "metric": "net_expectancy_pips_ci_lower",
                        "threshold": 0.0,
                        "secondary_metric": "oos_directional_accuracy",
                        "secondary_threshold": 0.52,
                        "cost_included": True,
                    },
                    evidence={"wall_clock_minutes": wall,
                              "members": [{"timeframe": tf, "horizon": h, "median_pips": m}
                                          for tf, h, m in items]},
                ))

    priority = {"R_HORIZON_FEASIBLE": 0, "R_FEATURE_INFO": 1, "R_CROSS_TF_AGREEMENT": 2}
    hyps.sort(key=lambda g: (priority.get(g.rule_id, 99), g.hypothesis_key))
    return hyps
