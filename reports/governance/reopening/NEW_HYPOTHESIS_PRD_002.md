# Reopening Proposal — New Hypothesis (DRAFT for owner review)

> **Status:** PROPOSAL ONLY. The Price-Derived Research Lane remains **SUSPENDED**
> (NEXORA-GOV-PRD-001). Nothing here reopens the lane, trains, tunes, promotes, or
> enables live trading. This document is the human-readable justification that backs
> a `REOPENING_PROPOSAL` packet built with `tools/build_lane_reopening_proposal.py`.

## 1. Why reopen (registry `reopening_conditions`)

We invoke **two** documented conditions:

- **"new data source providing additional information"** — see §2.
- **"a new measurement method with scientific justification that is testable"** — see §3.

We do **not** claim the failed hypotheses now "work". The suspension background in
`config/governance/price_derived_lane_suspension.json` stands: 0/20 candidates were
walk-forward stable, and no stable predictive edge was established.

## 2. New data source

(Owner to attach provenance + date span.) The candidate additional data is a
**point-in-time-correct** source not used in STAGE-5 / walk-forward:

- intra-bar order-flow / tick-imbalance aggregates (if available under a permissible
  licence for the in-scope instruments), or
- an event/macro calendar joined strictly by decision time (no look-ahead).

The data must pass the PIT gate (`research_bridge.assess_pit_safety`) and the
"data and leakage inspection" step before any hypothesis is pre-registered. If the
new source cannot be shown PIT-safe, the proposal is **NO-GO**.

## 3. New measurement method (scientifically justified + testable)

**Hypothesis (falsifiable):** For `EURUSD H4 h12` (currently a suspended candidate),
a *volume-imbalance-weighted range-position* feature computed over the same 20-bar
window carries directional information **net of costs**, with IC that is sign-stable
across walk-forward folds — unlike the failed price-only `rng_*` features which
showed **IC sign reversal** (STAGE-5 evidence: `new_information_assessment.json`,
EURUSD/H1 shows survivors but EURUSD/H4 `rng_60` flips; the point is precisely that
H4 needs a *new method*, not a re-run of the old one).

Why this is **substantively different** from the failed hypothesis:

| Failed (NEXORA-GOV-PRD-001) | This proposal |
|---|---|
| Price-derived range/position only | Range position **weighted by a new information source** |
| IC sign-reversed across folds | Pre-registered **sign-stability** requirement |
| No cost model in decision | **Net-of-cost** GO/NO-GO criterion |
| Feature measured in isolation | Feature measured against a **no-information baseline** |

## 4. Pre-registered GO/NO-GO criteria (set BEFORE looking at OOS results)

- **GO** only if, across ≥ 6 walk-forward folds:
  - sign-consistent test IC at each fold, **and**
  - IC survives Bonferroni at α = 0.05 over the declared test count, **and**
  - net-of-cost expectancy > 0 on the held-out folds, **and**
  - the feature beats its matched no-information baseline.
- **NO-GO** if any fold flips sign, or costs erase the edge, or the new data fails
  the PIT/leakage inspection.

## 5. Scope requested

- Candidate: **EURUSD H4 h12** (a genuinely suspended candidate).
- Reopening the lane is **all-or-nothing at the registry level**, so this proposal is
  the gatekeeper for the whole lane. Training on **any** candidate still requires the
  separate PREP-001 execution authorization (`nexora_audit.authorization`).

## 6. Procedure status

Each step in the registry `reopening_procedure` must be mapped with a status. This
draft maps "document the reason" / "create a new hypothesis" / "pre-registration" as
DONE by this document; everything else is PENDING and must be executed — and remain
subject to owner approval — *after* reopening is ratified.
