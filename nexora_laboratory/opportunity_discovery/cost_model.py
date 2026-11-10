"""STAGE 3 — Transaction Cost Analysis (pure, read-only).

Turns the REAL spread distribution measured in STAGE 2 (tick Bid/Ask for
GBPUSDm/USDJPYm/XAUUSDm; documented bar-estimates otherwise) into explicit, audited
trading COST SCENARIOS and cost-vs-move analysis.

Cost model (per round trip, in pips):
    cost = spread + slippage + commission

  * spread      : taken from the measured distribution. We do NOT invent it.
                  Scenarios anchor on real quantiles:
                      optimistic  = p50 (median)   spread
                      baseline    = p90            spread
                      stress      = p99            spread
                  Slippage is an explicit ASSUMPTION per scenario (documented).
  * commission  : Exness account type is UNKNOWN for the 'm' symbols -> NOT_AVAILABLE.
                  We therefore run the cost band at commission=0 (primary) and note
                  that a commission-bearing account would only INCREASE cost. No
                  commission number is fabricated.

Session view: cost is also expressed per execution session (ASIA/LONDON/NY/LATE)
using the measured per-session median spread, so execution-window decisions can be
grounded (e.g. LATE/rollover is expensive).

Cost-vs-move: for each horizon we compute cost as a fraction of the median move and
the "cost drag" (how much of the move is eaten). This is descriptive economics,
NOT a profitability claim and NOT a model result. No look-ahead (uses realised move
sizes only to size cost relative to typical movement).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional

# Cost scenarios anchored on real distribution quantiles + explicit slippage.
# Slippage is an ASSUMPTION (not in data); documented so it is auditable.
SCENARIO_QUANTILE = {"optimistic": "p50", "baseline": "p90", "stress": "p99"}
SCENARIO_SLIPPAGE_PIPS = {"optimistic": 0.2, "baseline": 0.2, "stress": 0.5}
# Slippage differs by instrument class (gold/JPY wider tick, but we keep 1 assumption
# per class rather than inventing numbers). FX majors vs gold:
SCENARIO_SLIPPAGE_PIPS_BY_CLASS = {
    "fx": {"optimistic": 0.2, "baseline": 0.2, "stress": 0.5},
    "metal": {"optimistic": 0.5, "baseline": 0.5, "stress": 1.5},
}

# Measured spread quantiles per instrument (STAGE 2 ground truth).
# For bar-only instruments these are ESTIMATES (documented). Source labels make the
# provenance explicit so nobody mistakes estimates for tick truth.
MEASURED_SPREAD_PIPS: Dict[str, Dict[str, object]] = {
    "GBPUSDm": {
        "source": "tick", "quantiles": {"p50": 1.15, "p90": 1.55, "p99": 6.85},
        "by_session_median": {"ASIA": 1.15, "LONDON": 1.15, "NY": 1.15, "LATE": 1.55},
        "by_session_mean": {"ASIA": 1.25862, "LONDON": 1.20715, "NY": 1.20211, "LATE": 4.28356},
        "class": "fx",
    },
    "USDJPYm": {
        "source": "tick", "quantiles": {"p50": 1.05, "p90": 1.15, "p99": 7.85},
        "by_session_median": {"ASIA": 1.05, "LONDON": 1.05, "NY": 1.05, "LATE": 1.85},
        "by_session_mean": {"ASIA": 1.09051, "LONDON": 1.07143, "NY": 1.15689, "LATE": 4.21951},
        "class": "fx",
    },
    "XAUUSDm": {
        "source": "tick", "quantiles": {"p50": 2.05, "p90": 3.05, "p99": 9.05},
        "by_session_median": {"ASIA": 2.05, "LONDON": 2.05, "NY": 2.05, "LATE": 2.05},
        "by_session_mean": {"ASIA": 2.34831, "LONDON": 2.35794, "NY": 2.35596, "LATE": 2.58404},
        "class": "metal",
    },
    # Bar-only (ESTIMATED spread; no tick on disk). Marked explicitly.
    "EURUSD": {
        "source": "estimate", "quantiles": {"p50": 3.0, "p90": 4.8, "p99": 9.0},
        "by_session_median": {}, "by_session_mean": {}, "class": "fx",
    },
    "XAUUSD": {
        # from tick XAUUSDm; bar XAUUSD has no reliable tick of its own -> reuse metal
        "source": "tick(XAUUSDm proxy)", "quantiles": {"p50": 2.05, "p90": 3.05, "p99": 9.05},
        "by_session_median": {}, "by_session_mean": {}, "class": "metal",
    },
}


@dataclass(frozen=True)
class CostScenario:
    name: str
    spread_pips: float
    slippage_pips: float
    commission_pips: float = 0.0
    commission_status: str = "NOT_AVAILABLE"

    @property
    def round_trip_pips(self) -> float:
        return float(self.spread_pips + self.slippage_pips + self.commission_pips)

    def as_dict(self) -> Dict[str, object]:
        return {"name": self.name, "spread_pips": round(self.spread_pips, 4),
                "slippage_pips": round(self.slippage_pips, 4),
                "commission_pips": round(self.commission_pips, 4),
                "commission_status": self.commission_status,
                "round_trip_pips": round(self.round_trip_pips, 4)}


def instrument_scenarios(instrument: str, *, commission_pips: float = 0.0) -> List[CostScenario]:
    """Build optimistic/baseline/stress cost scenarios from measured spread."""
    prof = MEASURED_SPREAD_PIPS[instrument]
    q = prof["quantiles"]
    cls = prof.get("class", "fx")
    slip = SCENARIO_SLIPPAGE_PIPS_BY_CLASS.get(cls, SCENARIO_SLIPPAGE_PIPS)
    out = []
    for name in ("optimistic", "baseline", "stress"):
        spread = float(q[SCENARIO_QUANTILE[name]])
        out.append(CostScenario(
            name=name, spread_pips=spread, slippage_pips=slip[name],
            commission_pips=commission_pips,
            commission_status=("NOT_AVAILABLE" if commission_pips == 0 else "ASSUMED"),
        ))
    return out


def session_costs(instrument: str, *, commission_pips: float = 0.0,
                  slippage_pips: Optional[float] = None) -> Dict[str, Dict[str, object]]:
    """Round-trip cost per execution session using measured per-session median spread.

    Slippage defaults to the baseline assumption for the instrument class. Commission
    is NOT_AVAILABLE by default (0 in the primary band).
    """
    prof = MEASURED_SPREAD_PIPS[instrument]
    cls = prof.get("class", "fx")
    if slippage_pips is None:
        slippage_pips = SCENARIO_SLIPPAGE_PIPS_BY_CLASS.get(cls, SCENARIO_SLIPPAGE_PIPS)["baseline"]
    med = prof.get("by_session_median") or {}
    mean = prof.get("by_session_mean") or {}
    out: Dict[str, Dict[str, object]] = {}
    for sess, spread in med.items():
        out[sess] = {
            "spread_pips": round(float(spread), 4),
            "spread_mean_pips": round(float(mean[sess]), 4) if sess in mean else None,
            "slippage_pips": round(float(slippage_pips), 4),
            "commission_pips": commission_pips,
            "round_trip_pips": round(float(spread) + slippage_pips + commission_pips, 4),
        }
    return out


def cost_vs_move(cost_pips: float, median_move_pips: Optional[float]) -> Dict[str, object]:
    """Cost as fraction of the median move (drag) at a given horizon.

    drag = cost / move  (0..1+). If drag >= 1 the cost eats the entire typical move
    at that horizon (structurally unattractive). Descriptive only.
    """
    if median_move_pips is None or median_move_pips <= 0:
        return {"cost_pips": round(cost_pips, 4), "median_move_pips": median_move_pips,
                "cost_fraction_of_move": None, "crossover": False}
    frac = cost_pips / median_move_pips
    return {
        "cost_pips": round(cost_pips, 4),
        "median_move_pips": round(median_move_pips, 4),
        "cost_fraction_of_move": round(frac, 4),
        "move_to_cost_ratio": round(median_move_pips / cost_pips, 4) if cost_pips > 0 else None,
        "crossover": bool(frac >= 1.0),
    }


def analyze_instrument_costs(
    instrument: str,
    *,
    horizons_with_median_move: Optional[Dict[str, float]] = None,
    commission_pips: float = 0.0,
) -> Dict[str, object]:
    """Full cost analysis for one instrument.

    Parameters
    ----------
    instrument : key in MEASURED_SPREAD_PIPS.
    horizons_with_median_move : optional {label: median_move_pips} (e.g. from STAGE 2
        economics) to compute cost-drag per horizon.
    commission_pips : primary band commission (default 0 = NOT_AVAILABLE treated as 0).
    """
    prof = MEASURED_SPREAD_PIPS[instrument]
    scenarios = instrument_scenarios(instrument, commission_pips=commission_pips)
    sess = session_costs(instrument, commission_pips=commission_pips)

    drag = {}
    if horizons_with_median_move:
        for label, med_move in horizons_with_median_move.items():
            drag[label] = {
                s.name: cost_vs_move(s.round_trip_pips, med_move) for s in scenarios
            }

    # execution-window recommendation: avoid the most expensive session.
    cheapest = max(
        (k for k in sess if sess[k]["round_trip_pips"] > 0),
        key=lambda k: -sess[k]["round_trip_pips"], default=None,
    )
    most_expensive = max(sess, key=lambda k: sess[k]["round_trip_pips"], default=None)

    return {
        "instrument": instrument,
        "spread_source": prof["source"],
        "commission_status": ("NOT_AVAILABLE" if commission_pips == 0 else "ASSUMED"),
        "scenarios": {s.name: s.as_dict() for s in scenarios},
        "by_session": sess,
        "cheapest_session": cheapest,
        "most_expensive_session": most_expensive,
        "cost_drag_by_horizon": drag,
        "note": ("Spread from measured data; slippage/commission are explicit "
                 "assumptions (commission NOT_AVAILABLE). No profit claim."),
    }
