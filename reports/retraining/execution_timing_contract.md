# NEXORA AI v2 — Execution Timing Contract Proposal (PREP-001)

Audit timestamp: 2026-11-07
Mode: static analysis of `nexora_vision/features.py`, `nexora_learning/pipeline.py`, dataset structure,
plus a runtime leakage probe (no training).
Status: **PROPOSAL — not ratified.** This document defines the timing contract and clearly separates what is
**PROVEN** from the data/code from what is a **NEW DESIGN DECISION** that cannot be proven from history.

Module: `nexora_audit/timing_contract.py` (`build_timing_contract()`), tests in `tests/test_nexora_config_freeze_v2.py`.
CLI: `python -m nexora_audit timing`.

Contract hash (`nexora-timing-v1`): `f460fa9fa77c5d652be068dd6cb8c8428d94325ccfb2d97cddbe9ba482b0111f`
(`ratified:false`).

---

## 1. Field-by-field contract

Timestamps are relative to the M30 bar `t` that produced the features. EURUSD M30; horizon `h = 2` bars.

| # | Field | Status | Definition / value |
|---|---|---|---|
| 1 | candle_close_timestamp | **PROVEN** | `ts` of M30 bar `t`; the instant OHLCV for bar `t` is complete. |
| 2 | feature_availability_timestamp | **PROVEN** | On/after close of bar `t`. All 29 features are trailing windows of bars ≤ `t` (`features.py` uses only `.shift/.rolling/.ewm`). |
| 3 | prediction_timestamp | **PROVEN** | On/after close of bar `t`; prediction depends only on bar-`t` features. |
| 4 | prediction_horizon | **PROVEN** | `h = 2` M30 bars; label = `sign(close[t+h]/close[t]-1)`. |
| 5 | decision_timestamp | **NEW_DESIGN** | Proposed: bar `t` close (uses bar-`t` probability only). Not encoded anywhere in the repo. |
| 6 | earliest_executable_timestamp | **NEW_DESIGN** | Proposed: bar `t+1` **open**. Cannot be proven from a directional-only evaluation. |
| 7 | execution_price_model | **NEW_DESIGN** | Proposed: bar `t+1` open (hypothetical). Unused until a cost-aware backtest exists. |
| 8 | no_future_information_rule | **PROVEN** | Prediction uses bars ≤ `t`; label uses `t+h` for training only. |
| 9 | spread_usage | **NEW_DESIGN** | `spread_relative` is a feature (1.0 when no spread column). PREP-001 dataset has no spread column → cost impact unmodeled. |
| 10 | slippage_usage | **NEW_DESIGN** | None currently modeled. |
| 11 | cost_usage | **NEW_DESIGN** | None; evaluation is gross directional ML metrics, not execution P&L. |

---

## 2. What is provable (no future information)

```text
 time ──────────────────────────────────────────────────────────────────────────►
  ... [bar t-1]   [bar t = M30 bar used for features]   [bar t+1]          [bar t+h]
                        │
                        │ 1. bar t closes                       (PROVEN)
                        │ 2. features(rows ≤ t) computed        (PROVEN, no look-ahead)
                        │ 3. prediction for bar t valid          (PROVEN)
                        │      label = sign(close[t+h]/close[t]-1) — future, TRAINING ONLY
                        ▼
           ┌──────────────────────────────┐
           │ decision @ bar t close        │  ◄── NEW DESIGN (proposed)
           │ earliest exec @ bar t+1 open  │  ◄── NEW DESIGN (proposed)
           └──────────────────────────────┘
```

- **No look-ahead in features:** `features.py` uses only trailing `.shift(k)`, `.rolling(n)`, `.ewm(...)`.
  Verified by `test_features_have_no_future_dependency`: perturbing the series tail never changes earlier
  feature rows.
- **Label is future-only and masked from inputs:** `pipeline.prepare` builds `fwd` from future closes and the
  mask excludes the last `h` rows; targets are never fed as features.
- **Split is purged:** chronological 0.6/0.2 + embargo `max(h,24)`; walk-forward folds are expanding and purged
  by `h`. Therefore a training row at `t` never shares its `t+h` outcome with a validation/test row inside the
  embargo gap.

These facts establish that **prediction-time** information is safe. They do **not** establish an execution clock.

---

## 3. Difference between prediction, decision, and execution (explicit)

- **Prediction time** = bar `t` close: the model outputs `P(up)` for the next `h` bars.
- **Decision time** = when the strategy converts `P(up)` into a direction. The repo only defines a *margin*
  band at evaluation (`Pt>=.5+margin → +1`, `<=.5-margin → -1`, else 0); it does **not** record when a live
  decision is taken. Proposed: same instant as prediction (bar `t` close).
- **Earliest executable time** = the first market instant a resulting order could fill. The repo has **no**
  venue/clock rule. Proposed: bar `t+1` open. Using bar `t` close as an execution price would assume same-tick
  fill and is optimistic; using `t+1` open is the conservative, realistic choice.

The current evaluation never simulates filling: `signals.csv` stores `direction` plus
`realized_forward_return = fwd[te]`, i.e. a **gross directional** outcome from `t` to `t+h`, without spread,
slippage or commission. So "prediction time" facts are proven, but "execution timing and cost" are not.

---

## 4. Proposed execution price, spread, slippage, cost

All are **NEW DESIGN** because the strategy/history cannot prove them:

| Concern | Proposed rule | Rationale |
|---|---|---|
| Execution price | bar `t+1` open | Conservative; avoids same-bar-close fill assumption |
| Spread | use recorded `spread` if present; else not applied | PREP-001 CSV has no spread column → currently unmodeled |
| Slippage | none until a cost-aware backtest is defined | No slippage model exists |
| Commission | none currently | `nexora_evaluator.metrics` are gross directional metrics |

A cost-aware backtest is required before any claim that directional accuracy equals profitability.

---

## 5. Required tests before ratification

1. **Purge-boundary test against dataset timestamps:** assert no test/validation row's `[t, t+h]` interval
   overlaps a training row's interval across the embargo gap, using real timestamps (not just indices).
2. **Execution-clock determinism:** once `t+1` open is chosen, assert simulated trades use `open[t+1]`,
   never `close[t]`.
3. **Cost application:** once spread/slippage are defined, assert they reduce evaluated return and that
   `spread_relative` feature is not silently used as cost.

---

## 6. Ratification & effect on readiness

- The contract is **not ratified** (`ratified:false`); six fields are NEW_DESIGN.
- `readiness.check_timing_ready(contract)` therefore returns **UNRESOLVED**, keeping TIMING_READY from passing.
- To pass: a human must accept/override each NEW_DESIGN field (decision clock, execution price, spread,
  slippage, cost), after which the contract flips to `ratified:true` and this gate can pass — but only along
  with the CONFIG_READY decisions from `configuration_freeze_v2_report.md`.

No future information is used anywhere in this contract; the only unproven parts are deliberate execution
policy choices, explicitly flagged as new design.
