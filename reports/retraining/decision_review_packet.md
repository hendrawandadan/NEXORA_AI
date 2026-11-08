# NEXORA AI v2 — PREP-001 Decision Review Packet

Date: 2026-11-07
Purpose: response to the five review criteria you specified. Every claim below was re-verified against the
current source during this review (files cited). **No training. No DB/CSV/dataset/model/backup change.**
**No production freeze. Nothing queued.**

Current readiness (actual, no sign-off file): `CONFIG_READY=FAIL, DATASET_READY=PASS, TIMING_READY=UNRESOLVED,
RUNNER_READY=PASS, RECOVERY_READY=PASS → BLOCKED`. Governance: `present=false`.

---

## Criterion 1 — Does the timing recommendation match the actual implementation?

**Verdict: YES — verified line-by-line.** PROVEN claims hold; only the 6 execution-policy fields are design.

| Timing field | Proposed | Verified against |
|---|---|---|
| candle/feature availability | features known at `bar_t_close` | `nexora_vision/features.py`: only `.shift(k>0)`, `.rolling`, `.ewm` → bar t uses bars ≤ t. ✔ |
| prediction timestamp | `bar_t_close + ε` | model predicts from bar-t features only. ✔ |
| prediction horizon | 2 bars (M30) | `pipeline.prepare`: `fwd[:-h]=close[h:]/close[:-h]-1`; h from job. ✔ |
| decision_timestamp | `bar_t_close` (DESIGN) | repo has no decision clock; genuine choice. ✔ flagged |
| earliest_executable | `bar_t+1_open` (DESIGN) | no venue rule in repo; genuine choice. ✔ flagged |
| execution_price_model | `bar_t+1_open` (DESIGN) | no realized execution price exists; for future backtest. ✔ flag |
| spread_usage | feature-only, not cost (DESIGN) | `features.py`: `spread_relative=1.0` when no spread column; PREP-001 has none. ✔ |
| slippage_usage / cost_usage | none / gross (DESIGN) | `nexora_evaluator.metrics` returns gross directional metrics, no costs. ✔ |
| no-future-info | proven | 11 purge-boundary tests (`tests/test_purge_boundary.py`, **11 passed**). ✔ |

So the recommended defaults are **consistent with the code**; the six are correctly labelled as human decisions,
not facts. **No correction needed.**

---

## Criterion 2 — Are R1/R2/R3 consequences described correctly?

**Verdict: YES — verified.** Ground truth from `nexora_learning/pipeline.py`:
- `walk_forward_scores` hardcodes `initial = max(int(n*0.50), 1000)`, `n = len(eligible)`.
- `config/research.json` declares `walk_forward.min_train_fraction=0.5` but **no code reads it**.

| Option | Real consequence | Behaviour change now |
|---|---|---|
| R1 | make `walk_forward_scores` read `walk_forward.min_train_fraction` (keeps `max(int(n*frac),1000)`) | **None** at 0.5; config becomes authoritative (config edits take effect) |
| R2 | delete the dead config key; document 0.50 as a constant baked into `split_policy_version` | **None**; removes the false impression config is read |
| R3 | also change walk-forward purge from `horizon` to `max(horizon, embargo_bars)=24` | **Small**: slightly larger purge per fold (folds start fraction unchanged) |

These match what the reports state. The one subtlety worth flagging: **R1 and R2 are behaviour-neutral
today**; only R3 changes a number (walk-forward purge 2→24). No option silently alters the 0.6/0.2 holdout.
**Accurate.**

---

## Criterion 3 — Are the LightGBM parameters sensible as *experiment* configs?

**Verdict: YES, as experiments only — grounded in current `model.py`.**

Current fixed params: `num_leaves=15`, `learning_rate=0.03`, `min_child_samples=100`,
`feature_fraction=0.8`, bagging 0.8, `reg_lambda=5`, 29 features, 300 rounds.

| Candidate | max_depth | reg_alpha | Sanity check |
|---|---|---|---|
| A | -1 | 0.0 | reproduces today's implicit defaults exactly (LightGBM default -1 / 0.0). ✔ |
| B | 4 | 0.1 | depth 4 ⇒ up to 16 leaves, matching `num_leaves=15` (≈log2 15≈3.9). ✔ proportionate |
| C | 3 | 0.5 | depth 3 (≤8 leaves) caps below num_leaves=15 → highest underfit risk. ✔ acknowledged |

Correct caveats are preserved in the proposal: **no historical experiment exists**, LightGBM is leaf-wise
(so `max_depth` is a secondary control to `num_leaves`), and each is a **design recommendation**, not a measured
result. **No fabricated backtest.** Reasonable as starting points for an experiment sweep.

---

## Criterion 4 — Is every human-approval decision clearly marked?

**Verdict: YES.** Three separate decision points, each explicit:

1. **Timing contract** — 6 `NEW_DESIGN` fields must be signed (`governance.REQUIRED_TIMING_DECISIONS`).
2. **Walk-forward** — must be exactly `R1|R2|R3` (`governance` validates).
3. **Experiment candidate** — must be exactly `A|B|C`, and `production_freeze` **must not be true**
   (governance rejects `true`).

Mechanism: `config/governance/prep001_ratification.TEMPLATE.json` (all `<FILL_ME>`), validated by
`nexora_audit/governance.py`; signing is the **only** path that flips gates
(`tests/test_governance_ratification.py` 10 passed). Until signed → gates stay BLOCKED. **Clearly marked.**

---

## Criterion 5 — Does sign-off open readiness for PREP-001 ONLY, and not accidentally activate all 37 jobs?

**Verdict: PARTIALLY — this is the one real risk, and it is NOT in sign-off; it is in the runner.** Verified:

### 5a. Sign-off / readiness / audit — SAFE (cannot activate any job)
`grep` shows the **entire `nexora_audit/` package never references** `batch_retraining_plan.csv` or
`batch_execution_log.csv`. The readiness CLI builds only: proposal, frozen manifest, timing contract,
and two isolated SQLite probes. Signing `prep001_ratification.json` changes **gate status strings only** — it
does **not** touch the plan, the execution log, or any job row, and does **not** set PLANNED→QUEUED.
Therefore **sign-off cannot start any job (1 or 37).** ✔

### 5b. The runner — REAL RISK (would run the whole batch if executed)
`reports/retraining/batch_retraining_plan.csv` contains **37 Batch-1 jobs (PREP-001…PREP-037)** plus 10 Batch-3
global jobs. `batch1_execution_runner.py`:
- loads **all** rows of the selected `--batch` from the log (`load_batch_rows`), no job-id filter;
- the only narrowing flag is `--limit N` (by plan `order`), **not** a specific `execution_id`;
- with `--execute` it would transition **every** queued row in the batch.

So **the runner is not scoped to PREP-001.** It does not fire on sign-off, but *if* someone runs
`--execute` after approving, it operates on the whole batch unless limited. This gap must be closed before any
execution is authorised.

### 5c. Recommended guard (NOT applied — pending your approval)
Add an explicit target filter, e.g. `--execution-id PREP-001` (or reuse `--limit 1` *plus* an assertion that the
selected row is PREP-001), so execution is provably single-job. I can implement this as a **read-only change**
in a follow-up if you approve; it is outside the current audit's no-code-change-to-runner boundary.

**Net:** your worry is well-founded but belongs to the runner, not to sign-off. Sign-off is safe; the runner
needs a PREP-001 scope guard before `--execute` is ever considered.

---

## Summary of the five criteria

| # | Criterion | Result |
|---|---|---|
| 1 | Timing recommendation matches implementation | ✔ verified; PROVEN fields hold, 6 correctly flagged as design |
| 2 | R1/R2/R3 consequences correct | ✔ verified; R1/R2 neutral, only R3 changes purge 2→24 |
| 3 | LightGBM A/B/C sensible as experiments | ✔ grounded; no fabricated backtest; leaf-wise caveat noted |
| 4 | Human-approval decisions clearly marked | ✔ 3 decisions + template + governance validation |
| 5 | Sign-off opens PREP-001 only, not 37 jobs | ⚠ **sign-off safe** (never touches jobs); **runner is whole-batch** → needs `--execution-id` guard |

---

## What still needs YOUR explicit decision (unchanged)

1. Ratify timing (6 fields) — recommendation uses current code behaviour (`bar_t_close` / `bar_t+1_open` /
   feature-only spread / no slippage / gross costs).
2. Pick R1 / R2 / R3.
3. Approve A / B / C **as experiment only** (not production freeze).
4. Decide whether I should add the **PREP-001 runner scope guard** (`--execution-id`) — recommended before any
   `--execute`.

No training will run; PLANNED stays PLANNED; no production freeze; dataset/DB/model/backup untouched.
