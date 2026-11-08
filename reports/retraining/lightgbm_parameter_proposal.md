# NEXORA AI v2 — LightGBM Parameter Proposal (Part C)

Audit timestamp: 2026-11-07
Scope: candidate choices for `max_depth` and `reg_alpha` to close the CONFIG_READY blocker.
Mode: read-only design analysis. **No value is frozen. No backtest is invented. No training run.**
These are **DESIGN RECOMMENDATIONS ONLY**; each must be ratified by a human and then validated by controlled
experiments before being frozen into `nexora-cfg-freeze-v2`.

Related: `configuration_freeze_v2_report.md` (why these two are REQUIRES_DECISION),
`prep001_readiness_v2_report.md`.

---

## 0. Grounding facts (what the current model actually is)

From `nexora_intelligence/model.py` and `config/research.json`:

| Fact | Value | Source |
|---|---|---|
| Engine | LightGBM (`LGBMClassifier`) | `model.py`; pinned 4.7.0 |
| Objective | binary | target `y=(fwd>0)` |
| num_leaves | **15** | `model.py num_leaves=15` |
| learning_rate | 0.03 | `model.py` |
| n_estimators / max_iter | 300 | `research.json` |
| min_child_samples | 100 | `model.py` |
| feature_fraction | 0.8 | `colsample_bytree=.8` |
| bagging | 0.8 @ freq 1 | `subsample=.8`, `subsample_freq=1` |
| reg_lambda (L2) | **5** | `reg_lambda=5` |
| reg_alpha (L1) | **unset → default 0.0** | `model.py` (absent) |
| max_depth | **unset → default -1 (unlimited)** | `model.py` (absent) |
| features | **29** | `build_features()` |
| dataset rows (PREP-001) | ~70,694 bars (~56k eligible after warmup/mask) | dataset + freeze |
| horizon | 2 bars (M30) | PREP-001 |

### 0.1 Important LightGBM interaction to respect
- **`max_depth` and `num_leaves` interact.** LightGBM grows **leaf-wise**, not level-wise. `num_leaves=15`
  already caps the tree to 15 leaves; a `max_depth` that is too small can *prevent reaching 15 leaves*
  (leaves grow unevenly), while `-1` lets `num_leaves` be the only binding constraint. So `max_depth` is a
  **secondary** complexity control here — `num_leaves=15` is the primary one.
- **`reg_alpha` (L1) vs `reg_lambda` (L2).** L2=5 already shrinks leaf values; L1 additionally drives small
  leaf splits/scores toward zero → sparse, more conservative trees and implicit feature selection.
- **~29 features, thousands of rows:** the p/n ratio is low, so moderate regularisation is defensible; but
  with `num_leaves=15`, trees are already small, so heavy depth limits add little.

### 0.2 Historical experiment evidence
**None available.** No repository artifact records a `max_depth`/`reg_alpha` sweep, and the 37 historical run
configs are absent (`training_configuration_recovery_report.md`). The simulation metadata are explicitly
dummy/simulated, not experiments. **Therefore every candidate below is a design recommendation, never a
measured result.** No accuracy/AUC numbers are attributed to these candidates.

---

## 1. Candidate configurations

Three coherent candidates (max_depth, reg_alpha), each keeping the frozen params (num_leaves=15, lr=0.03,
n_estimators=300, L2=5, min_child_samples=100) unchanged.

### Candidate A — "Explicit default / permissive depth"
| Field | Value |
|---|---|
| max_depth | **-1** (unlimited; makes default explicit) |
| reg_alpha | **0.0** (no L1; makes default explicit) |

- **Justification:** This is exactly what the code runs today, made *explicit and auditable* instead of an
  incidental library default. Lowest behavioural risk: pins the current effective config without change.
- **Risk:** Unlimited depth + L1=0 offers the least explicit guard against overfitting; relies entirely on
  `num_leaves=15`, `min_child_samples=100`, `feature_fraction=0.8`, bagging and L2=5. If those drift, there is
  no depth backstop.
- **Supporting evidence:** `model.py` omits both → LightGBM defaults (-1, 0.0). This is the status-quo config.
- **Origin:** design (making defaults explicit), **not** from experiment.

### Candidate B — "Balanced leaf-aligned depth + mild L1"
| Field | Value |
|---|---|
| max_depth | **4** |
| reg_alpha | **0.1** |

- **Justification:** With `num_leaves=15`, a balanced tree of depth 4 has up to 16 leaves — depth 4 is the
  **smallest cap that still lets `num_leaves=15` be reachable** in a near-balanced tree, so it bounds depth
  without starving leaf count. Mild L1 (0.1) adds gentle sparsity on top of L2=5, appropriate for 29 features.
- **Risk:** Because LightGBM is leaf-wise, depth 4 may occasionally cap some branches before 15 leaves fill
  (slightly reducing effective capacity). L1=0.1 is a guess without a sweep; could under-fit if too strong
  for the dominant features (ret_*, atr_pct, dist_sma*).
- **Supporting evidence:** num_leaves=15 ⇒ depth ~log2(15)≈3.9 ⇒ depth 4 is the matching ceiling; 29 features
  + L2=5 ⇒ small L1 is proportionate. **No experimental confirmation.**
- **Origin:** design recommendation.

### Candidate C — "Conservative depth + stronger L1"
| Field | Value |
|---|---|
| max_depth | **3** |
| reg_alpha | **0.5** |

- **Justification:** Depth 3 (≤8 leaves) deliberately caps capacity **below** num_leaves=15, enforcing a
  compact model; combined with stronger L1 (0.5) this maximally guards against overfitting on a low-signal
  directional target (AUC near 0.50 in prior directional reports). Suitable when the goal is robustness first.
- **Risk:** Most likely to **under-fit**; depth 3 may waste num_leaves=15 (a 15-leaf tree usually needs
  depth ≥4). Stranger still if it interacts with early-stopping-absent setting (fixed 300 rounds). Highest
  chance of reduced recall on rarer signal class.
- **Supporting evidence:** low p/n, directional target inherently noisy; conservative bias is defensible.
  **No experimental confirmation.**
- **Origin:** design recommendation.

---

## 2. Comparison matrix

| | A: -1 / 0.0 | B: 4 / 0.1 | C: 3 / 0.5 |
|---|---|---|---|
| Depth control | none (default) | leaf-aligned (16 leaves max) | strong (8 leaves max) |
| L1 sparsity | none | mild | stronger |
| Overfit risk | higher | medium | lowest |
| Underfit risk | lowest | medium | highest |
| Respects num_leaves=15 | fully | mostly | caps below it |
| Behavioural change vs today | zero | moderate | large |
| From experiment? | No | No | No |

---

## 3. Recommended validation before freezing (experiments, not yet run)

Any chosen candidate must be evaluated with the same split/purge policy and **more than one seed**, reporting
validation + walk-forward metrics (`nexora_evaluator.metrics`), not a single lucky run:

1. Sweep grid: `max_depth ∈ {-1, 3, 4, 6}`, `reg_alpha ∈ {0.0, 0.1, 0.5, 1.0}`, holding all frozen params fixed.
2. For each setting: report mean/std over seeds {42, 7, 13} of AUC, log-loss, Brier, balanced-accuracy on
   validation and each walk-forward fold.
3. Prefer the simplest setting within one standard error of the best (parsimony), consistent with
   `split_policy_version`.
4. Record the winning config + metrics as evidence, then freeze it.

These experiments require explicit approval (they are training runs) and are **out of scope** for this
read-only audit. Nothing was trained here.

---

## 4. Interim recommendation (for human decision only)

- If the priority is **zero behavioural change** to reproduce status quo safely → **Candidate A** (explicit
  -1 / 0.0), pending experiments.
- If the priority is a defensible **middle ground** → **Candidate B** (4 / 0.1).
- If the priority is **maximum overfitting guard** and accepting underfit risk → **Candidate C** (3 / 0.5).

This report does **not** select among them; the choice, and the decision to run experiments, are for a human.

---

## 5. Conclusion (Part C)

- Three coherent candidates provided with justification, risk, evidence, and origin.
- **No candidate is derived from an actual experiment** — none exist in the repo; all are design proposals.
- **No backtest results were fabricated.**
- `max_depth`/`reg_alpha` remain **REQUIRES_DECISION** in the freeze manifest (`complete:false`) until a human
  picks a candidate and it is validated by the experiments in §3, after which CONFIG_READY can pass.
- No model, config, dataset, or backup was modified.
