"""Tahap B — Failure Learning classifier (pure function + memory integration).

When an experiment returns NO_GO, the loop must explain WHY in a structured,
evidence-based way -- "failure must teach". This module maps measured evidence
(from the discovery/evaluation/feature-power stages) into exactly one
``failure_type`` (priority-ordered) plus a concrete ``recommendation``, and can
record the result into the Knowledge Memory (``research_failures``).

Design
------
* ``classify_failure(evidence)`` is a PURE function (no DB, no I/O). Input is a
  dict of measured evidence; output is a ``FailureDiagnosis`` dataclass.
* Priority order matters: the FIRST cause that is supported by the evidence wins,
  because earlier causes are prerequisites (bad data invalidates everything; a
  structurally-infeasible target never gets to "overfit").
* Every diagnosis carries a non-empty ``recommendation`` by construction -- the
  classifier can NEVER return a NO_GO without a next-action (guardrail §5.6).

Evidence keys (all optional; missing = "unknown", not asserted):
    data_quality            dict: {missing_frac, spread_pct_zero, granularity_break, ok}
    feasibility             dict: {any_feasible_symmetric, any_feasible_barrier,
                                   move_to_cost_ratio, required_acc_symmetric_min}
    feature_power           dict: {n_usable, verdict, top_abs_ic}
    edge                    dict: {auc_net, edge_pips_per_sd, cost_pips,
                                   auc_excludes_chance}
    train_test              dict: {train_auc, test_auc, walk_forward_stable}
    stability               dict: {regime_fail_fraction, year_fail_fraction}

This module does NOT train, does NOT touch production, does NOT make profit claims.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional

from .store import ResearchMemoryStore


FAILURE_TYPES = (
    "DATA_QUALITY", "STRUCTURAL_INFEASIBILITY", "NO_PREDICTIVE_POWER",
    "EDGE_BELOW_COST", "OVERFIT", "REGIME_FRAGILE", "UNKNOWN",
)

# Thresholds (explicit; documented, not magic). Tuned to be conservative.
DATA_MISSING_MAX = 0.10          # >10% missing -> data quality failure
DATA_SPREAD_ZERO_MAX = 0.50      # >50% zero-spread bars -> spread unreliable
FEASIBILITY_RATIO_MIN = 1.0      # move/cost must exceed 1.0x to be feasible at all
FEATURE_MIN_USABLE = 1           # need >=1 OOS-usable feature
EDGE_AUC_MIN = 0.52              # net AUC above chance
OVERFIT_TRAIN_TEST_GAP = 0.10    # train much better than test -> overfit
STABILITY_FAIL_FRACTION_MAX = 0.34  # >1/3 of regimes/years failing -> fragile


@dataclass(frozen=True)
class FailureDiagnosis:
    failure_type: str
    recommendation: str
    evidence: Dict[str, object] = field(default_factory=dict)
    reasons: List[str] = field(default_factory=list)

    def as_dict(self) -> Dict[str, object]:
        return {"failure_type": self.failure_type,
                "recommendation": self.recommendation,
                "evidence": self.evidence, "reasons": self.reasons}


def _ev(evidence: Optional[dict], key: str) -> Optional[dict]:
    if not evidence:
        return None
    v = evidence.get(key)
    return v if isinstance(v, dict) else None


def classify_failure(evidence: Optional[dict]) -> FailureDiagnosis:
    """Classify the PRIMARY cause of a NO_GO from measured evidence (pure).

    Returns the first cause (priority order) supported by the evidence, together
    with a concrete recommendation. Always returns a diagnosis with a non-empty
    recommendation (falls back to UNKNOWN + 'acquire more evidence'), so the
    'failure must teach' rule can never be violated.
    """
    evidence = evidence or {}
    reasons: List[str] = []

    # 1) DATA_QUALITY -- invalidates everything downstream if bad.
    dq = _ev(evidence, "data_quality")
    if dq:
        missing = dq.get("missing_frac")
        zero = dq.get("spread_pct_zero")
        gran = dq.get("granularity_break")
        bad_missing = isinstance(missing, (int, float)) and missing > DATA_MISSING_MAX
        bad_zero = isinstance(zero, (int, float)) and zero > DATA_SPREAD_ZERO_MAX
        bad_gran = bool(gran)
        if bad_missing:
            reasons.append(f"missing_frac={missing} > {DATA_MISSING_MAX}")
        if bad_zero:
            reasons.append(f"spread_pct_zero={zero} > {DATA_SPREAD_ZERO_MAX} (spread unreliable)")
        if bad_gran:
            reasons.append("heterogeneous granularity (daily prefix mixed with intraday)")
        if bad_missing or bad_zero or bad_gran:
            return FailureDiagnosis(
                "DATA_QUALITY",
                "Repair/acquire trustworthy data first: use homogeneous intraday segment, "
                "and prefer a symbol with real tick Bid/Ask (e.g. GBPUSDm/USDJPYm) so spread "
                "is measured, not inferred from a sparse <SPREAD> column.",
                evidence={k: dq.get(k) for k in ("missing_frac", "spread_pct_zero", "granularity_break")},
                reasons=reasons,
            )

    # 2) STRUCTURAL_INFEASIBILITY -- move cannot beat cost at any horizon.
    feas = _ev(evidence, "feasibility")
    if feas:
        ratio = feas.get("move_to_cost_ratio")
        sym = feas.get("any_feasible_symmetric")
        bar = feas.get("any_feasible_barrier")
        no_feasible = (sym is False and bar is False)
        low_ratio = isinstance(ratio, (int, float)) and ratio < FEASIBILITY_RATIO_MIN
        req_min = feas.get("required_acc_symmetric_min")
        if no_feasible or low_ratio:
            if no_feasible:
                reasons.append("no horizon feasible on symmetric or barrier model")
            if low_ratio:
                reasons.append(f"move_to_cost_ratio={ratio} < {FEASIBILITY_RATIO_MIN}")
            if isinstance(req_min, (int, float)):
                reasons.append(f"required_acc_symmetric_min={req_min} (below reachable)")
            return FailureDiagnosis(
                "STRUCTURAL_INFEASIBILITY",
                "Do NOT train: the target's realized move is too small versus cost. "
                "Move to a longer horizon (e.g. H4/48h) or a higher-volatility instrument, "
                "or acquire cheaper-execution / lower-spread data before spending compute.",
                evidence={"move_to_cost_ratio": ratio, "any_feasible_symmetric": sym,
                          "any_feasible_barrier": bar, "required_acc_symmetric_min": req_min},
                reasons=reasons,
            )

    # 3) NO_PREDICTIVE_POWER -- features carry no OOS information.
    fp = _ev(evidence, "feature_power")
    if fp:
        n_usable = fp.get("n_usable")
        top_ic = fp.get("top_abs_ic")
        verdict = fp.get("verdict")
        if n_usable == 0 or verdict == "no_feature_clears_oos_ic_bar":
            reasons.append(f"n_usable_features={n_usable} (OOS)")
            if isinstance(top_ic, (int, float)):
                reasons.append(f"top_abs_ic={top_ic}")
            return FailureDiagnosis(
                "NO_PREDICTIVE_POWER",
                "Current feature set has no OOS information on this target. Acquire NEW "
                "information (order flow, session/vol conditioning, macro/calendar) rather "
                "than re-tuning the same features.",
                evidence={"n_usable": n_usable, "top_abs_ic": top_ic, "verdict": verdict},
                reasons=reasons,
            )

    # 4) EDGE_BELOW_COST -- there is IC, but magnitude < cost.
    edge = _ev(evidence, "edge")
    if edge:
        auc = edge.get("auc_net")
        edge_pips = edge.get("edge_pips_per_sd")
        cost = edge.get("cost_pips")
        auc_ok = (isinstance(auc, (int, float)) and auc > EDGE_AUC_MIN)
        below = (isinstance(edge_pips, (int, float)) and isinstance(cost, (int, float))
                 and edge_pips < cost)
        if auc_ok and below:
            reasons.append(f"auc_net={auc} > {EDGE_AUC_MIN} but edge_pips_per_sd={edge_pips} < cost_pips={cost}")
            return FailureDiagnosis(
                "EDGE_BELOW_COST",
                "A real but too-small edge. Either lengthen the horizon so the same edge "
                "scales above cost, raise trade size discipline (fewer, higher-conviction "
                "trades), or lower cost via better execution. Do not claim profitability.",
                evidence={"auc_net": auc, "edge_pips_per_sd": edge_pips, "cost_pips": cost},
                reasons=reasons,
            )

    # 5) OVERFIT -- train good, test bad / unstable walk-forward.
    tt = _ev(evidence, "train_test")
    if tt:
        train_auc = tt.get("train_auc")
        test_auc = tt.get("test_auc")
        stable = tt.get("walk_forward_stable")
        gap = (train_auc - test_auc) if isinstance(train_auc, (int, float)) and isinstance(test_auc, (int, float)) else None
        if (gap is not None and gap > OVERFIT_TRAIN_TEST_GAP) or stable is False:
            if gap is not None:
                reasons.append(f"train_auc-test_auc gap={round(gap,4)} > {OVERFIT_TRAIN_TEST_GAP}")
            if stable is False:
                reasons.append("walk_forward unstable across folds")
            return FailureDiagnosis(
                "OVERFIT",
                "Reduce overfitting: increase purge/embargo, simplify features, use walk-forward "
                "regularisation, and confirm on an untouched holdout. Do not reuse the test set "
                "for tuning.",
                evidence={"train_auc": train_auc, "test_auc": test_auc,
                          "walk_forward_stable": stable, "gap": gap},
                reasons=reasons,
            )

    # 6) REGIME_FRAGILE -- fails in a meaningful fraction of regimes/years.
    stab = _ev(evidence, "stability")
    if stab:
        rf = stab.get("regime_fail_fraction")
        yf = stab.get("year_fail_fraction")
        bad = any(isinstance(x, (int, float)) and x > STABILITY_FAIL_FRACTION_MAX
                  for x in (rf, yf))
        if bad:
            if isinstance(rf, (int, float)):
                reasons.append(f"regime_fail_fraction={rf} > {STABILITY_FAIL_FRACTION_MAX}")
            if isinstance(yf, (int, float)):
                reasons.append(f"year_fail_fraction={yf} > {STABILITY_FAIL_FRACTION_MAX}")
            return FailureDiagnosis(
                "REGIME_FRAGILE",
                "Edge is concentrated/absent in whole regimes or years. Condition the strategy "
                "on volatility/session regime, or reject it as non-robust. Report the failing "
                "regimes explicitly.",
                evidence={"regime_fail_fraction": rf, "year_fail_fraction": yf},
                reasons=reasons,
            )

    # 7) UNKNOWN -- no evidence isolates a cause; still must teach.
    return FailureDiagnosis(
        "UNKNOWN",
        "No single cause isolated from the available evidence. Acquire more measurement "
        "(feasibility, feature-power, train/test, regime stability) before re-running, "
        "so the failure can be diagnosed rather than repeated blindly.",
        evidence={},
        reasons=["insufficient measured evidence to isolate a primary cause"],
    )


def classify_and_record(
    store: ResearchMemoryStore,
    *,
    experiment_id: int,
    evidence: Optional[dict],
    also_record_knowledge: bool = True,
    knowledge_key: Optional[str] = None,
) -> Dict[str, object]:
    """Classify a NO_GO from evidence and persist it to Knowledge Memory.

    Records into ``research_failures`` (required), and optionally a ``DEAD_END`` /
    ``CONSTRAINT`` knowledge entry so the lesson is queryable by later stages.

    Returns a dict with the diagnosis + stored row ids.
    """
    diag = classify_failure(evidence)
    stored = store.record_failure(
        experiment_id=experiment_id,
        failure_type=diag.failure_type,
        recommendation=diag.recommendation,
        evidence={**diag.evidence, "reasons": diag.reasons},
    )
    knowledge_id = None
    if also_record_knowledge:
        kind = "CONSTRAINT" if diag.failure_type in (
            "DATA_QUALITY", "STRUCTURAL_INFEASIBILITY") else "DEAD_END"
        kk = knowledge_key or f"experiment:{experiment_id}:failure"
        k = store.record_knowledge(
            knowledge_key=kk, kind=kind,
            summary=f"{diag.failure_type}: {diag.recommendation}",
            detail={"experiment_id": experiment_id, **diag.as_dict()},
            source_experiment_id=experiment_id,
        )
        knowledge_id = k["id"]
    return {
        "diagnosis": diag.as_dict(),
        "failure_row_id": stored["id"],
        "knowledge_row_id": knowledge_id,
    }
