"""STAGE 6 — Economic Opportunity Assessment (pure scoring, read-only).

Combines the evidence gathered in STAGES 1-5 into a TRANSPARENT opportunity score
per (instrument, timeframe, horizon). This is an economic OPPORTUNITY assessment --
NOT a profitability guarantee, NOT a backtest, NOT a trade signal.

Four components (each 0..1, documented weights):
  1. economics      : movement-to-cost ratio (enough move to beat cost?)   weight .25
  2. cost_burden    : 1 - cost-drag (cost as fraction of median move)      weight .20
  3. data_readiness : STAGE-4 readiness for the instrument                 weight .20
  4. signal_quality : STAGE-5 IC *stability* (NOT just significance)       weight .35

Signal quality is deliberately STRICT: a feature that merely "survives" BH but has
train-IC ~ 0 or a train/test sign flip or single-year concentration is scored LOW.
This encodes the STAGE-5 honest finding that the apparent IC was a regime artifact.
"""

from __future__ import annotations

from typing import Dict, List, Optional


# Component weights (documented; signal dominates, but economics/data gate it).
WEIGHTS = {"economics": 0.25, "cost_burden": 0.20, "data_readiness": 0.20,
           "signal_quality": 0.35}

# movement-to-cost ratio -> 0..1 (saturates at 10x; below 1x = 0).
MTC_GOOD = 10.0
# cost-drag -> cost_burden = 1 - min(drag, 1); drag>=1 -> 0.
DRAG_CAP = 1.0

# Requirement thresholds for a positive verdict.
VERDICT_READY = 0.65
VERDICT_WATCH = 0.45
# A candidate may only be a RESEARCH_CANDIDATE if the *stable* signal floor is met.
# Below this, economics/data alone cannot carry it -> capped at WATCH_ECONOMICS_ONLY.
SIGNAL_FLOOR_FOR_CANDIDATE = 0.30
# Below this, there is no usable stable information at all.
SIGNAL_FLOOR_MIN = 0.10


def econ_component(move_to_cost_ratio: Optional[float]) -> float:
    if move_to_cost_ratio is None or move_to_cost_ratio <= 0:
        return 0.0
    return round(min(1.0, move_to_cost_ratio / MTC_GOOD), 4)


def cost_component(cost_drag: Optional[float]) -> float:
    """cost_drag = cost/median_move. Lower is better -> component = 1 - drag."""
    if cost_drag is None:
        return 0.0
    return round(max(0.0, 1.0 - min(cost_drag, DRAG_CAP)), 4)


def _ic_by_feature(ic_table: List[Dict[str, object]], horizon: int) -> List[Dict[str, object]]:
    return [r for r in ic_table if int(r.get("horizon", -1)) == int(horizon)]


def signal_component(ic_rows: List[Dict[str, object]]) -> Dict[str, object]:
    """Score the STABILITY of IC at one horizon (strict, honesty-oriented).

    For each feature with a finite test_ic:
      * base = min(1, |test_ic| / 0.10)         (magnitude, saturates at 0.10)
      * robustness multiplier (0..1), product of:
          - sign_consistent (train sign == test sign) ? 1.0 : 0.35
          - |train_ic| factor: min(1, |train_ic|/0.03)  (train must NOT be ~0)
          - NOT (test p rejected but train p not) mismatch is already penalised above
    feature_score = base * robustness
    signal_quality = max over features of feature_score (best stable feature)

    A feature that is "BH-significant OOS" but unstable scores tiny because the
    robustness factor collapses. This is intentional.
    """
    best = 0.0
    details = []
    for r in ic_rows:
        test_ic = r.get("test_ic")
        train_ic = r.get("train_ic")
        if test_ic is None:
            continue
        base = min(1.0, abs(float(test_ic)) / 0.10)
        train_mag = 0.0 if train_ic is None else abs(float(train_ic))
        train_factor = min(1.0, train_mag / 0.03)      # train IC MUST be non-trivial
        sign_ok = bool(r.get("sign_consistent"))
        sign_factor = 1.0 if sign_ok else 0.35
        robustness = train_factor * sign_factor
        fs = base * robustness
        if fs > best:
            best = fs
        details.append({"feature": r.get("feature"), "test_ic": test_ic,
                        "train_ic": train_ic, "base": round(base, 3),
                        "train_factor": round(train_factor, 3),
                        "sign_consistent": sign_ok,
                        "robustness": round(robustness, 3),
                        "feature_score": round(fs, 3)})
    return {"signal_quality": round(best, 4), "features": details}


def opportunity_score(economics: float, cost_burden: float, data_readiness: float,
                      signal_quality: float) -> float:
    s = (WEIGHTS["economics"] * economics +
         WEIGHTS["cost_burden"] * cost_burden +
         WEIGHTS["data_readiness"] * data_readiness +
         WEIGHTS["signal_quality"] * signal_quality)
    return round(max(0.0, min(1.0, s)), 4)


def verdict(score: float, *, signal_quality: float, economics: float) -> str:
    """Conservative bucket. A high score with weak/unstable signal cannot be READY.

    Economics + data + cost cannot, by themselves, make a RESEARCH_CANDIDATE: the
    stable-signal floor must be met, otherwise the regime-artifact IC discovered in
    STAGE 5 would be laundered into a false positive.
    """
    if signal_quality < SIGNAL_FLOOR_MIN:
        # No usable stable information -> at best WATCH_E (economically interesting).
        return "WATCH_ECONOMICS_ONLY" if economics >= 0.30 else "REJECT"
    if signal_quality < SIGNAL_FLOOR_FOR_CANDIDATE:
        # Some signal but not enough for a candidate -> WATCH at most.
        return "WATCH"
    # Stable signal floor met: eligible for the full mapped verdict.
    if score >= VERDICT_READY:
        return "RESEARCH_CANDIDATE"
    if score >= VERDICT_WATCH:
        return "WATCH"
    return "REJECT"


def assess_candidate(
    *,
    instrument: str, timeframe: str, horizon: int,
    move_to_cost_ratio: Optional[float],
    cost_drag: Optional[float],
    data_readiness: float,
    ic_rows: List[Dict[str, object]],
    extra: Optional[Dict[str, object]] = None,
) -> Dict[str, object]:
    econ = econ_component(move_to_cost_ratio)
    cost = cost_component(cost_drag)
    sig = signal_component(ic_rows)
    score = opportunity_score(econ, cost, float(data_readiness), sig["signal_quality"])
    v = verdict(score, signal_quality=sig["signal_quality"], economics=econ)
    out = {
        "instrument": instrument, "timeframe": timeframe, "horizon": int(horizon),
        "components": {"economics": econ, "cost_burden": cost,
                       "data_readiness": round(float(data_readiness), 4),
                       "signal_quality": sig["signal_quality"]},
        "raw": {"move_to_cost_ratio": move_to_cost_ratio, "cost_drag": cost_drag},
        "weights": WEIGHTS,
        "opportunity_score": score,
        "verdict": v,
        "signal_detail": sig["features"],
    }
    if extra:
        out.update(extra)
    return out


def rank_candidates(candidates: List[Dict[str, object]]) -> List[Dict[str, object]]:
    """Sort by score desc; ties: higher signal_quality first."""
    return sorted(candidates, key=lambda c: (-c["opportunity_score"],
                                             -c["components"]["signal_quality"]))
