# FASE 2A — Upstream Signal-Quality Audit: SCOPE (pre-registration, no execution)

**Status:** SCOPE ONLY. No training, no experiments run by this document.
**Motivation:** PREP-001 (NO-GO) and R1 adaptive-barrier (NO-GO) and the directional-edge
audit all root-cause the same thing: the T3 classifier has ~no cost-surviving directional
edge. Barrier geometry (R1) and hyperparameters (PREP-001 A/B/C) were both ruled out as
the binding constraint. The next question is **upstream**: is the target/horizon
economically achievable at all, and does any feature carry OOS predictive power?

This document scopes **two** read-only diagnostics and pre-registers their acceptance
criteria **before** running them.

---

## 0. Evidence that triggered this audit (established, not to be re-litigated)

- **Real cost is HIGHER than earlier assumed.** EURUSD M30 `<SPREAD>` (MT5 points,
  5-digit): nonzero median = **30 points = 3.0 pips**, p90 = 5.0 pips
  (88.8% of rows record 0 = broker feed omits it). Earlier R1/audit used 1.2–2.2 pips;
  3.0+ is the realistic assumption.
- **Move size vs horizon** (median |open→open| move, pips):

  | h (bars) | 2 | 4 | 8 | 12 | 24 | 48 |
  |---|---|---|---|---|---|---|
  | median \|move\| (pip) | 4.5 | 6.4 | 9.6 | 12.3 | 18.8 | 28.5 |
  | ≈break-even accuracy @2.5 pip cost | **77.8%** | 69.5% | 63.0% | 60.2% | 56.6% | 54.4% |

- **Model accuracy ≈ 51%**, AUC ≈ 0.52 (PREP-001). At h=2 a ~78% hit-rate is needed to
  beat a 2.5-pip cost — a ~27 point gap. This is the core economic problem.

**Conclusion driving the scope:** the binding constraint is the *signal's edge vs cost at
a given horizon*, not the model architecture, the barrier, or hyperparameters.

---

## 1. Audit A — Break-even horizon vs cost (does ANY horizon/target clear cost?)

**Research question:** For each horizon h (and each target formulation), what directional
accuracy/edge would be required to break even after a **realistic cost**, and what is the
**actual OOS accuracy/AUC** at that horizon? Identify whether a *feasible* (horizon, cost)
region exists at all.

**Procedure (read-only):**
1. For h ∈ {2, 3, 4, 6, 8, 12, 24, 48} bars, compute realized |open→open| move
   distribution (median/mean/p75) — already measured above; formalize in a module.
2. Cost model: round-trip cost C(h) in pips = `spread_median (3.0) + slippage_assumption`
   (documented as SIMULATED; test at spread conservative 3.0 and stress 5.0 p90).
3. Break-even accuracy: `acc* = 0.5 + C / (2 * median|move|_h)` (symmetric-payoff model),
   plus a **payoff-asymmetry variant** (barrier-style, TP/ SL ratio) to avoid over-simple
   assumptions.
4. Compare to PREP-001 **actual** OOS accuracy/AUC per horizon **only if** models exist
   for that horizon; otherwise report the *required* accuracy as the bar to clear.

**Acceptance / decision rule:**
- **FEASIBLE region exists** iff some h has `required_accuracy - actual_accuracy <= 0`
  (i.e. actual clears break-even) at baseline cost 3.0 pips. → investigate that h next.
- If **no horizon** clears break-even with actual ≈51% accuracy, the **h=2 M30 binary
  target is economically infeasible** given cost → do NOT build more models at h=2; require
  a *different* target (volatility, meta-label, longer horizon, or higher-timeframe).

> Pre-registered expectation (honest): at h=2..8, required accuracy (63–78%) is far above
> the ~51% observed → **expected verdict: h=2 target infeasible at 3-pip cost.** This is a
> valid, decisive result.

---

## 2. Audit B — OOS feature power (does any feature predict returns after cost?)

**Research question:** Does any of the 29 features carry **out-of-sample** information about
future returns (IC / mutual information) that is economically meaningful, or is the signal
information-poor upstream of the model?

**Procedure (read-only, no model retraining required):**
1. Compute per-feature **OOS information coefficient (IC)**: Spearman corr(feature_t,
   fwd_return_{t+h}) on the **test split only** (chronological; no leakage).
2. Report **HHI/permutation-free** metrics: IC mean, IC t-stat via block bootstrap,
   mutual information (discretized) vs sign of forward return.
3. Compare per-horizon: which features' IC grows with h (trend/slow features) vs decays.
4. Flag **feature leakage / redundancy** (corr among features; features that are essentially
   the target in disguise, e.g. `spread_relative`).

**Acceptance / decision rule:**
- **Some feature has usable power** iff OOS |IC| is stable (95% block-bootstrap CI excludes
  0) **and** economically large enough to imply post-cost edge at the best horizon from
  Audit A. → propose a feature-focused model for that horizon.
- If **no feature** has stable OOS IC above a practical threshold (e.g. |IC| ≳ 0.02 with
  CI excluding 0), the **current feature set is information-poor** for directional return →
  the fix is new data/features (order flow, session structure, macro), not more models.

> Pre-registered honest note: earlier evidence (corr signal-vs-return ≈0.019) suggests
> **few or no features will clear a cost-relevant IC bar**. Audit B will confirm or refute
> that at the *feature* level, which changes the remediation path.

---

## 3. Anti-leakage / methodology (same discipline as R1)

1. Chronological train/valid/test; **test touched once** at evaluation.
2. Feature power computed on **test split only** (OOS), using the existing split boundaries
   (`train_start`/`test_start` from `report.json`); no refitting on test.
3. Block bootstrap for IC CIs (respect autocorrelation of returns).
4. Every metric is **net-of-cost**, not accuracy-only.
5. Deliverables cite the exact data hash + split + cost assumptions (freeze-style).

## 4. Deliverables (after separate approval to execute)

- `nexora_laboratory/break_even.py` — horizon vs cost feasibility (Audit A), pure function.
- `nexora_laboratory/feature_power.py` — OOS IC / MI with block-bootstrap CI (Audit B).
- `tools/run_signal_quality_audit.py` — read-only runner producing a JSON + MD report.
- Unit tests: break-even math correctness, label/IC forward-only (no look-ahead),
  bootstrap determinism, and a **no-edge fixture** that the audit correctly flags.

## 5. Explicit non-goals

- NOT training new models.
- NOT changing baseline ATR or any production config.
- NOT touching test more than once.
- NOT claiming an edge without CI evidence.

## 6. Expected outcome & why it's the right next step

Given the data, the most likely honest outcomes are:
- **Audit A:** h=2 (and nearby) is economically infeasible at 3-pip cost → conclusively
  retire the current binary-direction M30 h=2 target.
- **Audit B:** features are information-poor for directional return → remediation is
  *data/features*, not architecture.

Either outcome **redirects effort away from dead ends** (more hyperparameter tuning, more
barrier geometry) toward the actual constraint: **signal information vs transaction cost.**
This keeps the project honest and prevents further NO-GO loops on the barrier/model axis.

---

*Pre-registration only. Execution requires explicit approval, consistent with the project's
"no experiment without pre-registered criteria" discipline.*
