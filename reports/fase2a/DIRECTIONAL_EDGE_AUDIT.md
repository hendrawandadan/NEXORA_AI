# FASE 2A — Directional-Edge Audit of the T3 Model

**Question:** Does the predicted probability actually separate high-quality trades
from bad ones — and does any such separation survive transaction cost?

**Model:** `models/t3/individual/EURUSD/M30/h2` (T3, h=2).
**Data audited:** OOS test-split signal file `signals/t3/EURUSD/M30/h2/individual_signals.csv`
(14,051 rows; **5,509 active trades**, direction ≠ 0).
**Method:** `nexora_laboratory/directional_edge_audit.py`; artifact
`reports/fase2a/directional_edge_audit.json`.
**Cost:** simulated round-trip (optimistic 1.2 / baseline 1.7 / stress 2.2 pips) at ref 1.10.

> Signed return = `direction × realized_forward_return` (the saved file stores the
> RAW forward return; the audit re-signs it by trade direction — verified corr(rfr, direction)≈0).

---

## 1. Headline result

**The T3 model has NO cost-surviving directional edge.** It barely ranks trades
better than a coin once cost is applied, and the small gross separation it does have
is entirely consumed by spread.

| Scenario | Cost | AUC (net) | AUC (gross) | win-rate (net) | usable edge |
|---|---|---|---|---|---|
| optimistic | 1.2 pip | 0.5146 | 0.5262 | 42.7% | **No** |
| baseline | 1.7 pip | 0.5116 | 0.5262 | 38.4% | **No** |
| stress | 2.2 pip | 0.5052 | 0.5262 | 34.3% | **No** |

AUC ≈ 0.51–0.53 means the probability is **almost uninformative** for discriminating
winning vs losing trades. Net win-rate is 34–43% — well below the ~50%+ needed to
overcome a 1.7-pip round trip on a ~few-pip move.

## 2. Bucket monotonicity (baseline, 5 deciles)

| Bucket | P(right) range | n | mean gross | mean **net** | win-rate net |
|---|---|---|---|---|---|
| 0 | 0.530–0.536 | 1102 | +0.9e-6 | −1.46e-4 | 37.9% |
| 1 | 0.536–0.543 | 1102 | −1.0e-5 | −1.65e-4 | 38.3% |
| 2 | 0.543–0.553 | 1101 | −0.2e-5 | −1.57e-4 | 36.5% |
| 3 | 0.553–0.570 | 1102 | +1.2e-5 | −1.43e-4 | 38.4% |
| 4 | 0.570–0.736 | 1102 | +6.9e-5 | **−8.6e-5** | 40.7% |

- **Gross** return does rise with confidence (bucket 4 best, ~+0.7 pip) — there is a
  *tiny* monotone signal in gross terms (Spearman ≈ 0.7 across buckets).
- **Net** return is **negative in every bucket**, including the most-confident one.
  The gross edge (~0.5–0.7 pip in the top decile) is smaller than the ~1.7-pip cost.

## 3. Threshold economics (baseline cost)

Even at the most extreme confidence cut-offs, the cumulative net return stays negative:

| p_right ≥ | trades | mean net | total net |
|---|---|---|---|
| 0.50 | 5,509 | −1.39e-4 | **−0.7672** |
| 0.58 | 753 | −7.1e-5 | −0.0538 |
| 0.60 | 353 | −4.5e-5 | −0.0157 |
| 0.64 | 81 | −3.5e-5 | −0.0028 |
| 0.70 | 6 | −1.98e-4 | −0.0012 |

No threshold yields a positive total net under baseline cost. Only under the
**optimistic** cost (1.2 pip) does a very high cut-off (≈0.64, 81 trades) scrape a
marginal +0.00086 total — i.e. ~2.6 pips across 81 trades. That is noise, not an edge.

## 4. Calibration

Brier 0.2498, log-loss 0.6928 — barely better than the 0.25/0.693 of a constant-0.5
predictor. The probabilities are **not sharp** (range 0.28–0.74, clustered near 0.5)
and are close to a coin-flip in information content.

## 5. What this explains about R1

R1's NO-GO (adaptive barrier ≈ ATR) is now fully diagnosed:
- **A better barrier cannot rescue a signal with no post-cost directional edge.**
  Both arms inherited the same near-uninformative probabilities, so both were
  net-negative (≈ −1.1e-4/trade) and any barrier difference was noise (≈ 2e-6).
- The problem is **upstream** (the directional classifier), not the barrier.

## 6. Consequence for Approach #2

See `reports/fase2a/APPROACH2_HYPOTHESIS_ASSESSMENT.md`: an economic hypothesis for
Approach #2 is only worth testing if it addresses **signal quality / cost**, not
barrier geometry. The audit says barrier-only approaches (including #2 as a pure
barrier scaler) are very unlikely to succeed on this model.
