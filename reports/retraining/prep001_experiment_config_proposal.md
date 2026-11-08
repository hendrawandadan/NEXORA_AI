# PREP-001 LightGBM Experiment Configuration Proposal (A/B/C)

Date: 2026-11-07
Scope: TASK D — user approved A/B/C **as experiment configurations only, NOT a production freeze**.
These configs are defined in `nexora_audit/experiment_config.py` and are **not wired** into
`nexora_intelligence.model.create_model()` by default. Wiring is a separate, later, human-approved step.

---

## 1. Shared fixed parameters (from current `create_model`)

`nexora_intelligence/model.py::create_model` (LightGBM branch) fixes:
`n_estimators=max_iter(300)`, `learning_rate=0.03`, `num_leaves=15`, `min_child_samples=100`,
`subsample=0.8`, `subsample_freq=1`, `colsample_bytree=0.8`, `reg_lambda=5`. The sweep varies only
`max_depth` and `reg_alpha` on top of these, per the approved decision.

## 2. Approved candidates

| Candidate | max_depth | reg_alpha | LightGBM defaults? | Rationale |
|---|---|---|---|---|
| **A (baseline)** | -1 | 0.0 | yes (-1, 0.0) | Reproduces today's implicit defaults → zero behaviour change; reference point. |
| **B (primary)** | 4 | 0.1 | no | depth 4 ⇒ ≤16 leaves, aligned with `num_leaves=15`; mild L1. |
| **C (conservative)** | 3 | 0.5 | no | depth 3 caps ≤8 leaves < num_leaves=15; strongest overfit guard, highest underfit risk. |

`production_freeze = False` for all three (enforced by the config module and tests).

## 3. Module: `nexora_audit/experiment_config.py`

- `ExperimentConfig(name, max_depth, reg_alpha, profile, production_freeze=False)` frozen dataclass.
- `BUDGET_CANDIDATES = {"A": …, "B": …, "C": …}`.
- `EXPERIMENT_ONLY = True` sentinel.
- `get_candidate(name)` — case-insensitive, raises `KeyError` on unknown.
- `as_overrides()` — returns exactly `{"max_depth": …, "reg_alpha": …}` to merge during a sweep.
- `validate_all()` — structural sanity (all experiment-only, correct types).
- `summary()` — dict view for reports.

**It does not import or mutate `create_model`.** Freeze remains OFF.

## 4. Tests (isolated, no training)

File: `tests/test_prep001_experiment_config.py` — **6 passed**:
three candidates defined; values match the approved decision; all are experiment-only (not freeze);
overrides are exactly depth+alpha; `get_candidate` validates and is case-insensitive; `validate_all` passes.

## 5. How the sweep WOULD run (design only, not executed)

For each candidate in {A,B,C}:
1. `create_model(engine="lightgbm", seed, max_iter=300)` → then `.set_params(**get_candidate(x).as_overrides())`.
2. `train_one(...)` under R3 splits.
3. Compare held-out + walk-forward metrics; select winner only after human review.

**Not executed in this phase.** Running it requires explicit human approval of a training run (and a ratified
timing contract + complete governance), which are still absent.

## 6. Caveats preserved

- No historical A/B/C experiment exists; these are **design recommendations**, not measured results.
- LightGBM is leaf-wise: `max_depth` is a secondary control to `num_leaves=15`.
- C carries the highest underfit risk (depth 3 < log2(15)≈3.9).
- Production freeze stays OFF; promotion remains a separate human gate.
