"""Execution timing contract (Part B) for PREP-001.

This module *proposes* a decision/execution timing contract and distinguishes,
for every boundary, whether the rule is:

* PROVEN    - directly demonstrable from the data/code (no design choice needed).
* NEW_DESIGN- a forward-looking design decision that cannot be proven from the
             existing strategy/historical evaluation, so it must be ratified by a
             human before it is fixed.

It never uses future information: the label (close[t+h]) is only used for
training targets, never as an input to a prediction at bar t.

The contract is intentionally explicit about the gap between "prediction time",
"decision time" and "earliest executable time", because the current repository
does not encode an execution policy.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from typing import Any, Dict, List

from .canonical_config import canonical_json

TIMING_HASH_VERSION = "nexora-timing-v1"

PROVEN = "PROVEN"
NEW_DESIGN = "NEW_DESIGN"
UNRESOLVED = "UNRESOLVED"
# OWNER_APPROVED: value chosen by the project owner (documented approval). This is
# an *implementation* status, NOT a human HMAC ratification. `ratified` stays False
# until a separate signed sign-off exists; OWNER_APPROVED != human-ratified.
OWNER_APPROVED = "OWNER_APPROVED"


@dataclass
class TimingField:
    name: str
    definition: str
    status: str            # PROVEN | NEW_DESIGN | UNRESOLVED | OWNER_APPROVED
    evidence: str
    value: Any = None
    owner_approval: str = "PENDING"   # PENDING | OWNER_APPROVED

    def as_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "definition": self.definition,
            "status": self.status,
            "evidence": self.evidence,
            "value": self.value,
            "owner_approval": self.owner_approval,
        }


@dataclass
class TimingContract:
    fields: List[TimingField] = field(default_factory=list)

    def field(self, name: str) -> TimingField | None:
        for item in self.fields:
            if item.name == name:
                return item
        return None

    def unresolved(self) -> List[str]:
        return [f.name for f in self.fields if f.status in (NEW_DESIGN, UNRESOLVED)]

    def requires_design(self) -> List[str]:
        return [f.name for f in self.fields if f.status == NEW_DESIGN]

    def owner_approved_fields(self) -> List[str]:
        return [f.name for f in self.fields if f.status == OWNER_APPROVED]

    def hash_body(self) -> Dict[str, Any]:
        return {
            "hash_version": TIMING_HASH_VERSION,
            "fields": {f.name: f.value for f in self.fields},
        }

    def contract_hash(self) -> Dict[str, Any]:
        digest = hashlib.sha256(canonical_json(self.hash_body()).encode("utf-8")).hexdigest()
        design = self.requires_design()
        return {
            "hash": digest,
            "hash_version": TIMING_HASH_VERSION,
            # ratified flips to True only after a separate human HMAC sign-off.
            # OWNER_APPROVED fields are documented decisions, NOT ratification.
            "ratified": False,
            "owner_approved": not design,
            "new_design_fields": design,
            "owner_approved_fields": self.owner_approved_fields(),
            "unresolved_fields": self.unresolved(),
        }

    def to_dict(self) -> Dict[str, Any]:
        return {
            "contract_hash": self.contract_hash(),
            "fields": [f.as_dict() for f in self.fields],
        }


def build_timing_contract(horizon: int = 2, timeframe: str = "M30") -> TimingContract:
    """Assemble the timing contract proposal.

    All timestamps are described relative to the M30 bar close that produced the
    features. Anything that would require assuming an execution venue rule is
    flagged NEW_DESIGN.
    """
    fields: List[TimingField] = [
        TimingField(
            "candle_close_timestamp",
            "ts of the M30 bar used to compute features; the instant the bar's OHLCV is complete.",
            PROVEN,
            "Bar timestamp is `df.ts`; features use only rows <= this bar (features.py: shift/rolling/ewm).",
            value="bar_t_close",
        ),
        TimingField(
            "feature_availability_timestamp",
            "Earliest instant all 29 features for bar t are known.",
            PROVEN,
            "All features are trailing windows of bars <= t; available at/after close of bar t. "
            "test_features_have_no_future_dependency proves tail perturbation never changes earlier rows.",
            value="bar_t_close + epsilon",
        ),
        TimingField(
            "prediction_timestamp",
            "Instant a model prediction for bar t may be produced.",
            PROVEN,
            "Prediction depends only on features for bar t, so it is valid at/after close of bar t.",
            value="bar_t_close + epsilon",
        ),
        TimingField(
            "prediction_horizon",
            "Number of bars the directional label spans.",
            PROVEN,
            f"horizon={horizon} bars of {timeframe}; label = sign(close[t+h]/close[t]-1) (pipeline.prepare).",
            value={"horizon_bars": horizon, "timeframe": timeframe},
        ),
        TimingField(
            "decision_timestamp",
            "Instant the strategy commits to a position/direction for the horizon.",
            OWNER_APPROVED,
            "Owner-approved (PREP-001 B2): decision is taken at the OPEN of bar t+1, using features "
            "and probability computed from bar t (known at close of bar t). The decision instant is the "
            "start of bar t+1; the Open[t+1] price is NOT assumed known before bar t+1 begins, so no "
            "look-ahead. This matches the execution_price_model/entry price.",
            value="bar_t+1_open",
            owner_approval=OWNER_APPROVED,
        ),
        TimingField(
            "earliest_executable_timestamp",
            "Earliest market instant a resulting order could realistically be filled.",
            OWNER_APPROVED,
            "Owner-approved (PREP-001 B2): earliest executable instant is the OPEN of bar t+1, identical "
            "to the decision instant for T3. An order cannot fill before bar t+1 starts (it would use "
            "Open[t+1] information before it exists). No same-bar-as-decision earlier fill is allowed.",
            value="bar_t+1_open",
            owner_approval=OWNER_APPROVED,
        ),
        TimingField(
            "execution_price_model",
            "Price used hypothetically for evaluation if execution is simulated.",
            OWNER_APPROVED,
            "Owner-approved (PREP-001 B2): execution uses the OPEN price. T3 entry = Open[t+1], "
            "T3 exit = Open[t+h+1]. For T1 (statistical) this field is descriptive only; T1 remains "
            "close-to-close direction and is NOT an execution backtest.",
            value="open_price",
            owner_approval=OWNER_APPROVED,
        ),
        TimingField(
            "no_future_information_rule",
            "Prediction at bar t must not read any bar > t.",
            PROVEN,
            "features.py uses only trailing operators; label is masked from inputs; split uses embargo>=horizon.",
            value="features <= t only; label uses t+h for training only",
        ),
        TimingField(
            "spread_usage",
            "Whether spread affects prediction or cost in evaluation.",
            OWNER_APPROVED,
            "Owner-approved (PREP-001 B2): spread is DEFERRED. Not applied as a transaction cost in the "
            "initial gross evaluation; spread_relative remains a feature only. To be modelled in a later "
            "cost-aware phase.",
            value="deferred",
            owner_approval=OWNER_APPROVED,
        ),
        TimingField(
            "slippage_usage",
            "Whether slippage is applied in evaluation.",
            OWNER_APPROVED,
            "Owner-approved (PREP-001 B2): slippage is DEFERRED (not modelled in initial gross evaluation).",
            value="deferred",
            owner_approval=OWNER_APPROVED,
        ),
        TimingField(
            "cost_usage",
            "Whether commission/spread/slippage reduce evaluated returns.",
            OWNER_APPROVED,
            "Owner-approved (PREP-001 B2): transaction costs are DEFERRED. Initial T3 evaluation is GROSS "
            "and must never be described as net profitability. A separate cost model is future work.",
            value="deferred",
            owner_approval=OWNER_APPROVED,
        ),
    ]
    return TimingContract(fields=fields)


def is_ratified(contract: TimingContract) -> bool:
    return contract.contract_hash().get("ratified", False)
