"""FASE 2A - Transaction Cost Engine (EURUSD 5-digit convention).

Converts the APPROVED research cost scenarios into a return fraction that can be
subtracted from a gross price return. This module is deliberately explicit about
units so that costs are applied exactly ONCE (no double counting).

Approved scenarios (RESEARCH ASSUMPTIONS, not real broker costs):
    optimistic : 1.0 pip round-trip + 0.2 pip slippage  = 1.2 pip total
    baseline   : 1.5 pip round-trip + 0.2 pip slippage  = 1.7 pip total
    stress     : 2.0 pip round-trip + 0.2 pip slippage  = 2.2 pip total

Unit convention (EURUSD quoted to 5 decimals, e.g. 1.12184):
    - 1 pip  = 0.0001  (== 10 "points"; the export's <SPREAD> column is in points)
    - 1 point = 0.00001
The engine returns cost as a FRACTION OF PRICE (0.00012 for 1.2 pip at 1.0 EURUSD),
which is directly comparable to a gross fractional return like open->open.

The dataset's <SPREAD> column is NOT used as a real cost (it is 88.8% zero); it
remains only a relative feature (`spread_relative`) elsewhere. This avoids paying
two independent spread estimates.
"""

from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Dict, Tuple

PIP_SIZE = 0.0001          # price units per pip for EURUSD (5-decimal quote)
POINTS_PER_PIP = 10        # 1 pip == 10 broker "points"

SCENARIOS: Dict[str, Tuple[float, float]] = {
    # name: (round_trip_pips, slippage_pips)
    "optimistic": (1.0, 0.2),
    "baseline": (1.5, 0.2),
    "stress": (2.0, 0.2),
}

ASSUMPTION_NOTE = (
    "RESEARCH ASSUMPTION, not actual broker cost. Scenario values are preset "
    "assumptions; <SPREAD> column is not used as a real cost to avoid double counting."
)


@dataclass(frozen=True)
class CostScenario:
    name: str
    round_trip_pips: float
    slippage_pips: float

    @property
    def total_pips(self) -> float:
        return round(self.round_trip_pips + self.slippage_pips, 6)

    def as_return_fraction(self, reference_price: float = 1.0) -> float:
        """Total cost expressed as a fraction of price.

        ``reference_price`` is the price the return is measured against. For an
        open->open fractional return, using ``reference_price`` = entry price is
        exact; using 1.0 gives an approximation whose relative error is <~10%.
        Sizing-agnostic: this is a per-unit-notional round-trip cost.
        """
        return (self.total_pips * PIP_SIZE) / float(reference_price)

    def as_dict(self) -> Dict[str, object]:
        return {
            **asdict(self),
            "total_pips": self.total_pips,
            "assumption": ASSUMPTION_NOTE,
        }


def get_scenario(name: str) -> CostScenario:
    key = (name or "").strip().lower()
    if key not in SCENARIOS:
        raise KeyError(f"unknown scenario {name!r}; allowed: {sorted(SCENARIOS)}")
    rt, slip = SCENARIOS[key]
    return CostScenario(name=key, round_trip_pips=rt, slippage_pips=slip)


def all_scenarios() -> Dict[str, CostScenario]:
    return {name: get_scenario(name) for name in SCENARIOS}


def cost_return_fraction(name: str, reference_price: float = 1.0) -> float:
    """Convenience: total cost (round-trip + slippage) as a return fraction."""
    return get_scenario(name).as_return_fraction(reference_price)


def apply_cost(gross_return: float, name: str, reference_price: float = 1.0) -> float:
    """Net return = gross_return - cost_fraction (single subtraction, no double count)."""
    return float(gross_return) - cost_return_fraction(name, reference_price)


def summarize() -> Dict[str, Dict[str, object]]:
    return {name: sc.as_dict() for name, sc in all_scenarios().items()}


if __name__ == "__main__":
    import json

    print(json.dumps(summarize(), indent=2))
    for name in SCENARIOS:
        sc = get_scenario(name)
        print(f"{name:>10}: {sc.total_pips:.1f} pip -> return_frac(1.0)={sc.as_return_fraction():.6f}")
