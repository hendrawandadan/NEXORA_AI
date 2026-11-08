# NEXORA AI v2 — PREP-001 Pending Human Decisions & Readiness State

Date: 2026-11-07
Status: **AWAITING HUMAN DECISION.** No training run. No production freeze applied.
This document records the three decisions you asked to be closed, the machinery that records them, and the
current honest readiness state.

---

## 0. Current readiness (actual CLI output, no sign-off file present)

`python -m nexora_audit readiness`

```
CONFIG_READY   : FAIL
DATASET_READY  : PASS
TIMING_READY   : UNRESOLVED
RUNNER_READY   : PASS
RECOVERY_READY : PASS
decision       : BLOCKED
governance     : present=false, valid=false, problems=["ratification file absent"]
```

`max_depth`, `l1_regularization`, `decision_time_policy` are still `REQUIRES_DECISION`; the timing contract is
still `ratified:false`. This is the correct state until a human signs the decisions below. **Nothing was
forced to PASS.**

---

## 1. How decisions are recorded (no agent self-approval)

I built a governance layer so a decision is recorded **only** by a human-authored sign-off file:

- File: `config/governance/prep001_ratification.json` (a `*.TEMPLATE.json` is provided; the template is NOT read).
- Module: `nexora_audit/governance.py` — validates the file (approver, decided_at, each timing decision,
  R1/R2/R3, candidate A/B/C, and forbids `production_freeze:true` for experiments).
- CLI: `python -m nexora_audit governance` shows the summary.
- If the file is **absent/invalid/incomplete → nothing is ratified → gates stay BLOCKED**. The tooling never
  invents a ratification.

**Proof the mechanism flips gates (isolated, temp dir, NOT applied to your config):** a valid signed payload
turns all five gates to PASS (`READY_FOR_TRAINING`). Tests: `tests/test_governance_ratification.py` → 10 passed.
Full suite → **146 passed**.

To apply a decision, a human must copy the template and fill every `<FILL_ME>`, e.g.:

```jsonc
// config/governance/prep001_ratification.json  (HUMAN-authored)
{
  "approver": "Your Name / Role",
  "decided_at": "2026-11-08T10:00:00Z",
  "references": ["reports/retraining/execution_timing_contract.md", "..."],
  "timing_contract": {
    "decision_timestamp":            { "value": "bar_t_close" },
    "earliest_executable_timestamp": { "value": "bar_t+1_open" },
    "execution_price_model":         { "value": "bar_t+1_open" },
    "spread_usage":                  { "value": "feature_only_no_cost" },
    "slippage_usage":                { "value": "none" },
    "cost_usage":                    { "value": "gross_metrics" }
  },
  "walk_forward_reconciliation": "R1",
  "walk_forward_note": "wire config to code; behaviour unchanged at 0.5",
  "experiment_configuration": {
    "candidate": "B", "max_depth": 4, "reg_alpha": 0.1, "production_freeze": false
  }
}
```

> The values above are a **recommended default** consistent with the prior reports; they are NOT applied until
> you confirm. Change any you disagree with.

---

## 2. Decision 1 — Ratify the timing contract

Fields to decide (from `execution_timing_contract.md`). PROVEN fields need no decision; the 6 below do:

| Field | Proposed default | Meaning |
|---|---|---|
| decision_timestamp | `bar_t_close` | commit to direction at bar t close |
| earliest_executable_timestamp | `bar_t+1_open` | first realistic fill is next bar open |
| execution_price_model | `bar_t+1_open` | hypothetical price (for future backtest) |
| spread_usage | `feature_only_no_cost` | spread is a feature, not yet a cost |
| slippage_usage | `none` | no slippage modeled |
| cost_usage | `gross_metrics` | evaluation is gross directional metrics |

Label horizon treatment: **PROVEN** — `horizon=2` bars; label = `sign(close[t+h]/close[t]-1)` used for training
only; features at bar t read only bars ≤ t; splits purged with embargo ≥ horizon (verified by the 11
purge-boundary tests). Ratifying the contract means confirming these PROVEN facts plus choosing the 6 execution
policy values above.

**Your decision:** ☐ accept proposed defaults  ☐ override (list changes)

---

## 3. Decision 2 — Walk-forward reconciliation (R1 / R2 / R3)

From `walk_forward_reconciliation_report.md`: the config key `walk_forward.min_train_fraction=0.5` is **read by
no code**; the pipeline hardcodes `max(int(n*0.50),1000)` on the eligible-row denominator.

| Option | Action | Behaviour change today |
|---|---|---|
| **R1** (recommended) | Wire `walk_forward_scores` to read `walk_forward.min_train_fraction` | None (still 0.5), config becomes authoritative |
| R2 | Remove the dead config key; document 0.50 as fixed in split-policy version | None; removes dead key |
| R3 | Also unify walk-forward purge to `max(horizon, embargo_bars)` to match holdout | Slightly larger purge in walk-forward |

**Your decision:** ☐ R1  ☐ R2  ☐ R3

---

## 4. Decision 3 — Approve A/B/C as the *experiment* configuration

From `lightgbm_parameter_proposal.md`. **These are experiments, not a production freeze.** No historical
experiments exist, so each is a design recommendation, not a measured result.

| Candidate | max_depth | reg_alpha | Profile |
|---|---|---|---|
| A | -1 | 0.0 | explicit status quo; zero behavioural change |
| **B** (recommended middle) | 4 | 0.1 | leaf-aligned to num_leaves=15; mild L1 |
| C | 3 | 0.5 | strongest overfit guard; highest underfit risk |

Choosing a candidate here only authorises it **as an experiment config**. Production freeze remains separate
and requires the sweep (§3 of the proposal) to be run first — which itself needs your explicit training approval.

**Your decision:** ☐ A  ☐ B  ☐ C  (as experiment only)

---

## 5. What happens after you decide

1. You (a human) fill `config/governance/prep001_ratification.json`.
2. Run `python -m nexora_audit readiness` → **all five gates PASS → READY_FOR_TRAINING**.
3. Re-emitting a *complete* frozen manifest with the decided `max_depth`/`reg_alpha` values remains a separate,
   later step (the freeze is not auto-applied).
4. **Training still does not start** until you explicitly approve a training run (the experiments in §3 of the
   proposal). PLANNED is not changed to QUEUED by this work.

---

## 6. Boundary statement

- No training; `train_one()` / `model.fit()` never called.
- No production DB, CSV, dataset, model, backup, or `config/research.json` modified.
- No PLANNED→QUEUED.
- No production freeze applied; A/B/C remains experiment-only.
- The only new runtime artifact is `config/governance/prep001_ratification.TEMPLATE.json` (template, not active).

**Awaiting your explicit choices for the three decisions in §2–§4.**
