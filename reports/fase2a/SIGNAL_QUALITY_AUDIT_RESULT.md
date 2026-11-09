# FASE 2A — Upstream Signal-Quality Audit: RESULT (Audit A + Audit B)

**Status:** Read-only audit executed. No training, no config/model changes.
**Data:** EURUSD M30, 70,694 bars, 2020-01-02 → 2026-11-06.
**Split:** same as PREP-001 T3 (train 42,295 / valid 14,098 / test **14,051**, test
starts 2025-09-22).
**Artifact:** `reports/fase2a/signal_quality_audit.json`.

---

## Headline

**The binary-direction M30 target is economically infeasible at realistic cost, and the
features carry real but ≈3×-too-small information to fix it.** Two independent audits
agree, and a multiple-testing-aware reading of the feature ICs says the tiny structure
that exists is a weak mean-reversion signature, not a tradeable edge.

---

## Audit A — Break-even horizon vs cost

**Real spread measured from the MT5 `<SPREAD>` column: median 3.0 pips** (30 points;
p90 = 5.0 pips). With 0.2 pip slippage → **baseline round-trip cost = 3.2 pips**.
(Our earlier R1/audit used 1.2–2.2 pips — too optimistic. 3.0+ is the honest number.)

Required directional accuracy to break even (symmetric payoff) vs the model's actual
OOS accuracy (51.1%):

| h (bars) | median move | req. acc @3.2 pip cost | actual acc | feasible? |
|---|---|---|---|---|
| 2 | 4.5 pip | **85.6%** | 51.1% | ❌ |
| 3 | 5.5 pip | 79.1% | — | ❌ |
| 4 | 6.4 pip | 75.0% | — | ❌ |
| 8 | 9.6 pip | 66.7% | — | ❌ |
| 12 | 12.3 pip | 63.0% | — | ❌ |
| 24 | 18.8 pip | 58.5% | — | ❌ |
| 48 | 28.5 pip | 55.6% | — | ❌ |

- At the trained horizon (h=2) you would need **~86% accuracy** to beat a 3.2-pip cost;
  the model delivers 51%. That is a **~35-point gap** — not closeable by tuning.
- Even at h=48 (a 28-pip move) you still need **55.6%** vs the ~51% the signal shows.
- **No horizon in {2..48} is feasible** under the real spread (symmetric model).

> The barrier-model column shows lower required hit-rates at long h, but that is a
> **degenerate artefact**: it scales the barrier with the (growing) median move, so the
> cost/scale ratio shrinks mechanically. It does not reflect free money — the payoff
> also scales, and the symmetric model (fixed normalized payoff) is the honest gate.
> **Verdict A: no feasible horizon at 3.2-pip cost.**

## Audit B — OOS feature power (test split only)

Per-feature Spearman IC vs signed forward return, block-bootstrap 95% CI (block=24):

| Feature | IC | 95% CI | MI (bits) |
|---|---|---|---|
| dist_sma50 | −0.0341 | [−0.0555, −0.0137] | 0.00081 |
| rsi14 | −0.0328 | [−0.0569, −0.0125] | 0.00078 |
| ema_slope20 | −0.0317 | [−0.0523, −0.0104] | 0.00091 |
| ema_slope50 | −0.0292 | [−0.0500, −0.0087] | 0.00067 |
| ret_32 | −0.0276 | [−0.0502, −0.0055] | 0.00055 |

- **12 of 29 features** have a CI excluding zero with |IC| ≥ 0.02 — but the effect is
  **uniformly negative** (≈ −0.02 to −0.034) and the features measure overlapping
  states (distance-from-MA, RSI, EMA slope, recent return). This is a **single weak
  mean-reversion factor**, not 12 independent edges.
- **Multiple-testing reality**: testing ~29 features at 95% CI with no true signal
  yields ~1.45 false "usable" features by chance. The consistency of the negative sign
  argues these are real (one shared factor), but **the magnitude is the problem**, not
  the sign.
- **Economic ceiling (the decisive number):** for the best feature (`dist_sma50`,
  IC −0.034), the implied linear edge per 1-sd move is **≈ 0.097 pips**, versus a
  **3.2-pip** round-trip cost — a ratio of **0.03**. You would need the edge to be
  **~33× larger** to break even.

**Verdict B:** the features are **not information-poor in the absolute sense** (a
mean-reversion factor exists and is statistically detectable), but they are
**economically insufficient by ~30×** at M30/h=2 against a 3-pip spread.

---

## Combined conclusion

| Question | Answer |
|---|---|
| Does any horizon beat cost? | **No** (symmetric break-even ≥55.6% at best vs ~51% actual) |
| Do features carry OOS structure? | **Yes** — a weak, consistent mean-reversion factor |
| Is that structure tradeable at M30/h=2? | **No** — edge ≈0.097 pip vs 3.2-pip cost (~3%) |
| Root cause | Signal magnitude ≪ transaction cost at short horizons |

## Recommendation (evidence-driven)

1. **Retire the M30 binary-direction target** as a strategy basis. It cannot clear cost
   at any horizon in {2..48}; h=2 is ~35 accuracy-points short.
2. **Do not add architecture/hyperparameters** — PREP-001 (A/B/C) and R1 (barrier) are
   already ruled out as the constraint.
3. **Two real options to create a tradeable edge:**
   - **(a) Reduce cost / raise move-per-trade:** trade a **higher timeframe or much
     longer horizon** where move ≫ spread, and/or an instrument with tighter relative
     spread. The gap shrinks with h; h≥48 is the closest and still needs better signal.
   - **(b) Add genuinely new information:** the existing 29 features reduce to a single
     weak mean-reversion factor. Directional return needs *new* data (order flow, session
     microstructure, macro/news), not more technicals.
4. **If pursuing meta-labeling / triple-barrier** (already scaffolded): it only helps
   *conditional on* a signal with gross edge ≥ cost. With ~0.1-pip feature edge, meta-
   labeling cannot manufacture a 3-pip edge. So (3a)/(3b) must come first.

## What this audit did NOT do
- No model training; no production/config/DB writes.
- Test split read once; IC computed OOS with block bootstrap (autocorrelation-aware).
- No edge claimed beyond what CIs support.

---

*Closes the "why is PREP-001/R1 no-edge" loop at the source: it is economic
(feature magnitude vs spread), not architectural. Remediation is horizon/cost or new
data — not more models on the same target.*
