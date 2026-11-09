"""FASE 2A - Transaction Cost Engine v2 (component-separated, no double counting).

CORRECTION (review items 1, 6, 7, 8). Total cost is composed from explicit
components, each applied exactly once:

    total = spread_component + commission_component + slippage_component + swap_component

Two COST APPLICATION MODES (use exactly ONE per evaluation, never both):
    (A) EXECUTABLE mode: bid/ask reconstructed from mid-price (OHLC) plus an
        assumed half-spread; gross_return already contains the spread crossing.
        -> ``spread_already_in_prices=True`` so we DO NOT subtract spread again.
    (B) FLAT mode: gross_return uses mid prices; subtract total component cost
        once here (spread + slippage + commission + swap).

DATA REALITY (verified): no historical bid/ask exists; only OHLC + a <SPREAD>
column that is 88.8% zero. Therefore:
    - We do NOT claim historical spread is known.
    - spread is an explicit ASSUMPTION (from scenario); results = SIMULATED EXECUTION.
    - commission and swap are NOT_AVAILABLE (not silently real zero): for M30
      intraday (no overnight) swap is "assumed 0 for intraday, NOT empirical";
      commission is UNKNOWN unless a value is supplied.

Unit convention (EURUSD 5-decimal): 1 pip = 0.0001 price units = 10 broker points.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict

PIP_SIZE = 0.0001
POINTS_PER_PIP = 10

STATUS_ASSUMED = "ASSUMED"
STATUS_NOT_AVAILABLE = "NOT_AVAILABLE"
STATUS_ASSUMED_INTRADAY = "ASSUMED_ZERO_INTRADAY"


@dataclass(frozen=True)
class CostComponents:
    """Each cost component in PIPS with an explicit status."""

    round_trip_spread_pips: float = 1.5
    slippage_pips: float = 0.2
    commission_pips: float = 0.0
    swap_pips: float = 0.0

    spread_status: str = STATUS_ASSUMED
    slippage_status: str = STATUS_ASSUMED
    commission_status: str = STATUS_NOT_AVAILABLE
    swap_status: str = STATUS_ASSUMED_INTRADAY

    def total_pips(self, include_spread: bool = True) -> float:
        total = self.slippage_pips + self.commission_pips + self.swap_pips
        if include_spread:
            total += self.round_trip_spread_pips
        return round(total, 9)

    def as_dict(self) -> dict:
        return {
            "round_trip_spread_pips": self.round_trip_spread_pips,
            "slippage_pips": self.slippage_pips,
            "commission_pips": self.commission_pips,
            "swap_pips": self.swap_pips,
            "status": {
                "spread": self.spread_status,
                "slippage": self.slippage_status,
                "commission": self.commission_status,
                "swap": self.swap_status,
            },
            "note": (
                "spread is an ASSUMPTION (no historical bid/ask available; <SPREAD> "
                "column is 88.8% zero). commission is NOT_AVAILABLE unless supplied. "
                "swap assumed 0 for intraday (not empirical). Results = SIMULATED EXECUTION."
            ),
        }


# Approved scenario assumptions (round-trip spread, slippage) in pips.
SCENARIO_PIPS: Dict[str, tuple] = {
    "optimistic": (1.0, 0.2),
    "baseline": (1.5, 0.2),
    "stress": (2.0, 0.2),
}


def components_for_scenario(name: str, commission_pips: float = 0.0) -> CostComponents:
    key = (name or "").strip().lower()
    if key not in SCENARIO_PIPS:
        raise KeyError(f"unknown scenario {name!r}; allowed: {sorted(SCENARIO_PIPS)}")
    spread, slip = SCENARIO_PIPS[key]
    return CostComponents(
        round_trip_spread_pips=spread,
        slippage_pips=slip,
        commission_pips=commission_pips,
    )


def pips_to_price(pips: float) -> float:
    return pips * PIP_SIZE


def cost_fraction_from_pips(pips: float, reference_price: float) -> float:
    """Component-pips -> return fraction, using the ACTUAL entry price (review 7)."""
    if reference_price <= 0:
        raise ValueError("reference_price must be positive")
    return pips_to_price(pips) / float(reference_price)


def total_cost_fraction(
    comp: CostComponents, reference_price: float, spread_already_in_prices: bool,
) -> float:
    """Total cost as return fraction with strict no-double-count semantics.

    If ``spread_already_in_prices`` is True (EXECUTABLE mode), the spread
    component is EXCLUDED here because it is already embedded in bid/ask prices.
    """
    return cost_fraction_from_pips(
        comp.total_pips(include_spread=not spread_already_in_prices), reference_price
    )


def summarize() -> Dict[str, dict]:
    return {name: components_for_scenario(name).as_dict() for name in SCENARIO_PIPS}


if __name__ == "__main__":
    import json
    print(json.dumps(summarize(), indent=2))
