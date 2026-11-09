# FASE 2A — Approach #2 (Regime-Conditional Barrier): Hypothesis Assessment

**Purpose:** decide whether Approach #2 has a **strong enough economic hypothesis** to
justify a new pre-registered experiment. Per the agreed sequence, Approach #2 is only
tested if this assessment says YES.

**Approach #2 (design §3.1 Option 2):** classify regime (calm/high-vol) from features
≤ t, then set the barrier to a per-regime scale fitted on past data.

**Verdict: NO — not worth pre-registering as a barrier experiment.** Reason: the
directional-edge audit shows there is **no regime in which the signal carries a usable,
cost-surviving edge**, so re-scaling the barrier by regime cannot create one.

---

## 1. The decisive evidence (no speculation)

Directional edge by regime, baseline cost 1.7 pips, OOS 5,509 trades
(`directional_edge_audit.py`, regimes from trailing realized-vol deciles):

| Regime | n | AUC (net) | gross mean | **net mean** | win-rate net |
|---|---|---|---|---|---|
| calm | 1,799 | 0.5121 | −1.13e-05 | **−1.59e-04** | 37.4% |
| mid | 1,632 | 0.5087 | −4.38e-06 | **−1.35e-04** | 37.6% |
| high | 2,078 | 0.5101 | +5.11e-06 | **−1.25e-04** | 39.9% |

- AUC ≈ 0.51 in **every** regime → the probability does not separate good/bad trades
  within any regime.
- Mean **net** return is negative in **every** regime. The high-vol regime is only
  *least bad* (gross turns slightly positive: +5.1e-06 ≈ 0.05 pip, still ≪ 1.7 pip cost).
- This corroborates R1's per-regime finding (adaptive "won" mid/high but all means
  stayed negative) — that was noise around a negative baseline, not an edge.

## 2. Why a regime-conditional barrier cannot fix this

A barrier choice (ATR vs adaptive vs per-regime scale) changes **where** profit/loss
are booked and **which** trades close early/late. It **cannot manufacture directional
information** that the classifier does not contain. Formally:

- Expected net per trade ≈ `E[direction · signed_move] − cost`. Regime-scaling the
  barrier changes the *distribution* of signed_move (truncation at barriers), but if
  `P(correct)` is ≈ coin-flip in every regime, the expectation stays ≈ `−cost`.
- The audit shows `P(correct | regime)` is coin-flip in all three regimes, and gross
  edge is ~0.05 pip vs a ~1.7 pip cost. No barrier geometry closes a 1.7-pip gap when
  the raw directional separation is ~0.05 pip.

Therefore the *economic hypothesis* for Approach #2 ("barriers scaled to regime will
improve net return") has **no mechanism** here: the thing it would improve (barrier
placement) is not the binding constraint; the classifier's directional content is.

## 3. The hypothesis COULD become testable if the precondition changes

Approach #2 would deserve a pre-registered experiment **only if** at least one holds:

1. **A directional model with a gross edge ≥ ~1.5–2 pip** exists (so cost is beatable
   and barrier geometry can matter). The current T3 model does not.
2. **A cost regime exists where the net is plausibly positive** (e.g. zero-commission
   or materially tighter spread, or a longer horizon with a larger move vs cost).
3. The signal is shown to be **regime-differentially predictive** (AUC meaningfully
   > 0.55 in some regime). Currently all regimes are ≈ 0.51.

None of these hold, so per the agreed sequencing we **stop before pre-registering #2**.

## 4. Recommended next investigation (upstream, not barrier)

The binding constraint is the **directional classifier's quality vs cost**, not the
barrier. The higher-value next step is an audit of *why* the model has ~no edge:

- Horizon vs cost: are h=2 M30 moves (~few pip) simply too small vs 1.7 pip cost?
  Recommend auditing expected move per horizon against cost (break-even horizon).
- Feature signal: does any feature have OOS predictive power after cost?
- Class balance / calibration sharpening: probability is near-constant (0.28–0.74).

This keeps the project honest: fix the input edge before optimising the barrier.
