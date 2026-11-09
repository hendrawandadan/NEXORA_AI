# FASE 2A — ATR vs Vol-Targeted Adaptive Barrier: EXPERIMENT RESULT

**Verdict: NO-GO.** Adaptive barrier does **not** meet the pre-registered criteria;
**ATR remains the baseline.** This is a valid, expected outcome (design §2 anticipated
H0 would likely not be rejected), not a project failure.

**Date:** 2026-11-08
**Instrument / timeframe:** EURUSD M30, 2020-01-02 → 2026-11-06 (70,694 bars)
**Signal source:** frozen primary model `models/t3/individual/EURUSD/M30/h2` (T3, h=2).
Both arms consume the **identical** signal probabilities; only the barrier differs.
**Artifact:** `reports/fase2a/adaptive_vs_atr/adaptive_vs_atr_report.json`

---

## 1. Protocol actually executed

| Component | Setting (frozen) |
|---|---|
| Walk-forward | 3 expanding folds, initial = max(0.5·n, 1000) |
| Purge | `purge_bars(2, T3, 24) = 24` bars (≥ horizon+h and ≥ vertical) |
| Entry timing | open of bar t+1 (no leakage) |
| Execution | simulated bid/ask via `ExecutionConfig(half_spread_price)` |
| Cost engine | `components_for_scenario` (optimistic / baseline / stress) |
| Label core | frozen `triple_barrier.label_events` (shared, byte-identical) |
| ATR baseline | `BarrierConfig(k_up=1.5, k_dn=1.0, vertical=16)` — FROZEN |
| Adaptive #1 | `VolTargetConfig(horizon=16, k_vol=1.25, vertical=16)` — FROZEN |

Scenario differences enter through the **simulated half-spread** (0.5·round-trip pips:
optimistic 0.5, baseline 0.75, stress 1.0 pip per side); slippage (0.2 pip) is subtracted
once as a non-spread component in executable mode. This is why the three scenarios give
strictly different net returns below.

OOS trade count: **15,592** per arm (identical candidate set — apple-to-apple).

---

## 2. Net-of-cost results (the decision metric, not IC)

Mean **net** return per trade (executable, cost-aware):

| Scenario | Adaptive | ATR | Δ (ad−atr) | Bootstrap 95% CI | p(Δ≤0) |
|---|---|---|---|---|---|
| optimistic | −6.23e-05 | −6.54e-05 | +3.14e-06 | [−3.66e-05, +4.31e-05] | 0.44 |
| **baseline** | **−1.078e-04** | **−1.104e-04** | **+2.64e-06** | **[−3.60e-05, +4.29e-05]** | **0.45** |
| stress | −1.526e-04 | −1.516e-04 | −1.02e-06 | [−4.04e-05, +3.88e-05] | 0.51 |

All net means are **negative** after cost for both arms — the signal itself is not
cost-profitable at these thresholds — and the adaptive−ATR difference is **statistically
indistinguishable from zero** (CI straddles 0 in every scenario).

Per-fold baseline Δ: fold 1 **+4.88e-05**, fold 2 **+2.05e-05**, fold 3 **−5.60e-05**
(adaptive better in 2 of 3 folds — not the required 3).

---

## 3. Pre-registered GO/NO-GO (§6, literal)

| # | Criterion | Result | Pass |
|---|---|---|---|
| 6.1 | Net > ATR in ≥3 baseline folds | 2 / 3 folds positive | ❌ |
| 6.2 | Baseline bootstrap 95% CI excludes 0 | CI includes 0 | ❌ |
| 6.3 | Consistent under **stress** | adaptive < ATR under stress | ❌ |
| 6.4 | Trade count adequate | 15,592 / fold ≫ 50 | ✅ |
| 6.5 | Not a single-regime artefact | adaptive better in 2/3 regimes | ✅ |
| 6.6 | No leakage | enforced by purged folds + tests | ✅ |

Because GO requires **all** criteria (§6: "Adaptive hanya boleh menggantikan ATR jika
seluruh kriteria praregistrasi terpenuhi"), the verdict is **NO-GO**.

---

## 4. Per-regime (baseline scenario)

| Regime | Adaptive net | ATR net |
|---|---|---|
| calm | −1.456e-04 | −0.998e-04 |
| mid | −0.824e-04 | −1.222e-04 |
| high | −0.881e-04 | −1.113e-04 |

Adaptive is slightly better in *mid* and *high* vol but **worse in calm** regimes — no
robust, regime-independent edge. (n = 5,833 / 4,918 / 4,841 per arm.)

---

## 5. Diagnosis & interpretation

1. **The vol forecast is good, the economics are not.** Earlier IC of predicted vol vs
   realized range was ~0.58 — the model *does* forecast volatility. But a better barrier
   placement does not translate into positive net return once spread is crossed, because
   the underlying directional signal has no post-cost edge at these thresholds.
2. **Symmetric k_vol barrier** ≈ neutral vs ATR 1.5/1.0×ATR on average; differences are
   ~2–3e-06 of return, dwarfed by the ~1e-04 cost level.
3. **NO-GO closes Option 1.** Per design §6, ATR stays baseline. Options 2 (regime-scale)
   and 3 (economic-optimal multiplier) remain unexplored and would need a new, separately
   pre-registered experiment.

## 6. Leakage assurance

- Labels/entries use only bars after entry; ATR & vol features are trailing.
- Vol model fit on **train folds only** (`tests/test_adaptive_experiment.py::
  test_adaptive_fit_is_train_only`).
- Purged walk-forward geometry matches `pipeline.walk_forward_scores`
  (`test_walk_forward_geometry_matches_pipeline_rule`), purge ≥ horizon.
- Target semantics proven forward-only (`tests/test_adaptive_barrier.py`).
- 30 protocol-integrity tests pass.

## 7. What was NOT changed

`triple_barrier.py` label/exec logic, `cost_engine.py`, `event_attribution.py`, the
primary model, dataset, and baseline config are untouched by this experiment. No tuning
on the test window; the test was evaluated once.
