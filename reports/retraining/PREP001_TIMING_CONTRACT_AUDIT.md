# NEXORA AI — PREP-001 EXECUTION TIMING CONTRACT AUDIT

Audit date: 2026-11-08
Role: Senior Quantitative Research Engineer / ML Engineer / MQL5 Trading-System Architect
Scope: PREP-001 only — EURUSD M30, horizon h = 2, target `Close[t+h]/Close[t] - 1`,
trailing features, prediction after candle `t` closes, proposed entry `Open[t+1]`.
Mode: **READ-ONLY AUDIT.** No code, config, database, execution log, dataset, model,
or status was changed. No training. No dispatch. No sign-off created. No promotion.
Numeric checks used a read-only load of the existing CSV (no writes).

Code under audit (verified against the repository, not prior reports):
`nexora_learning/pipeline.py`, `nexora_vision/features.py`, `nexora_evaluator/metrics.py`,
`nexora_evaluator/trading.py`, `nexora_intelligence/model.py`, `nexora_datahub/loader.py`,
`batch1_execution_runner.py`, `nexora_audit/timing_contract.py`, `nexora_audit/readiness.py`,
`nexora_audit/configuration_freeze.py`, `nexora_audit/authorization.py`, `config/research.json`.

---

## Executive Summary

1. **The label is Close-to-Close (T1).** Verified in code
   (`pipeline.py:17`: `fwd[:-horizon]=close[horizon:]/close[:-horizon]-1`) and numerically
   (`fwd[100] = close[102]/close[100]-1 = 0.0103667599`). This is a **statistical/gross
   directional target**, NOT a realizable trading return when entry is `Open[t+1]`.

2. **Entry at `Open[t+1]` is incompatible with an exit at `Close[t+h]`.** If you enter
   `Open[t+1]` and hold "2 bars" you exit at `Open[t+h+1]` (= `Open[103]` for t=100,h=2),
   because the h-bar interval must span the SAME price type at both ends. Mixing
   `Open[t+1]` entry with `Close[t+h]` exit is a **mismatched interval** (h=2 bars entered but
   the close-to-close window `[t, t+h]` measures a different holding span relative to entry).

3. **CRITICAL FACTUAL CORRECTION to prior reports.** `execution_timing_contract.md` states
   "PREP-001 dataset has no spread column → cost impact unmodeled." **This is wrong.** The
   CSV header contains `<SPREAD>` and the loader parses it (`d.columns` includes `spread`).
   However the value is **mostly 0 (62,775 / 70,694 = 88.8% zeros)** with discrete non-zero
   values (50, 15, 30, …) — i.e. an intermittent/sparse broker spread field, **units = points
   (integer)**, not a continuous per-bar quote. So spread data *exists* but is not usable
   as-is for a per-bar cost model without a units/interpretation decision.

4. **The current evaluation is GROSS directional ML**, not an execution backtest.
   `metrics.py` computes accuracy/AUC/brier/logloss only. `trading.py:86` can apply a
   **single constant** `round_trip_cost_bps` (default `0.0`) but this path is **not wired
   into `train_one`**; the shipped `report.json`/`signals.csv` contain gross
   `realized_forward_return`. So: **evaluation is BEFORE transaction costs.**

5. **TIMING_READY is UNRESOLVED** (contract `ratified:false`; 6 NEW_DESIGN fields). The
   no-future-information part is PROVEN, but the execution clock / price / cost model are
   deliberate design decisions that no one has ratified.

6. **Recommendation (for owner decision, not final):** T3 — enter `Open[t+1]`, exit
   `Open[t+h+1]` — as the most defensible execution-consistent contract, with T2 (enter
   `Open[t+1]`, exit `Close[t+h]`) explicitly rejected as an interval mismatch. T1 remains
   valid only as a statistical target. This is a **recommendation**, pending your approval.

---

## 1. Kondisi Implementasi Saat Ini

| Area | Implementation | Status |
|---|---|---|
| Bar timestamp semantics | `loader.load_bars` keeps `<DATE> <TIME>` as `ts`. Values are **bar-open** labels (00:00, 00:30, …), 30-min spacing on M30 (67,033/70,694). | VERIFIED |
| Target label | `pipeline.py:16-17`: `fwd[:-h]=close[h:]/close[:-h]-1`; `y=(fwd>0)` mask finite. | VERIFIED |
| Features | `features.py:3`: only `.shift(k)`, `.rolling(n)`, `.ewm(...)` — trailing only. 29 columns incl. `spread_relative`. | VERIFIED |
| `spread_relative` | `features.py:29-33`: if `spread` present → `sp/rolling100_median`; else `1.0`; inf→NaN→fillna(1.0). | VERIFIED |
| Split | `pipeline.py:22-29`: 0.6/0.2 chronological + embargo `max(h,24)` between segments. | VERIFIED |
| Walk-forward | `pipeline.py:32-53`: expanding, folds=3, `purge=horizon` default; R3 passes `max(h,24)` (`:38`). | VERIFIED |
| Direction band | `pipeline.py:74`: `+1 if p≥.5+margin`, `-1 if p≤.5-margin`, else `0`; `margin=.03`. | VERIFIED |
| Realized return stored | `pipeline.py:76`: `realized_forward_return = fwd[te]` (close-to-close). | VERIFIED |
| Metrics | `metrics.py`: accuracy/balanced/brier/logloss/AUC only. No PnL. | VERIFIED |
| Cost-aware evaluator | `trading.py:67-89`: `evaluate_signals_frame(round_trip_cost_bps=0.0)`; subtracts constant cost (`:86`). **Not called by `train_one`.** | VERIFIED (dead path for training reports) |
| Runner dispatch | `batch1_execution_runner.py`: `--execution-id` scope; `guard_execution_authorized()` before STARTED/train; fail-closed. | VERIFIED |
| Authorization gate | `nexora_audit/authorization.py`: job-scoped, HMAC-verified sign-off required. | VERIFIED |
| Readiness | `readiness.py`: TIMING_READY requires ratified timing contract. | VERIFIED |
| Dataset spread | `<SPREAD>` column parsed; 88.8% zeros; integer points. | VERIFIED (data exists) / UNRESOLVED (usable cost) |

Note on timestamps: because `ts` is the **bar-open** label, "bar `t` close" = `ts[t] + 30min`.
The audit below uses index `t` per the task's convention (t=100, h=2) and treats each
`Candle t` row as the bar whose OPEN is `Open[t]` and CLOSE is `Close[t]`.

---

## 2. Timeline contoh t = 100, h = 2

Index convention: `Candle t` is the bar starting at `ts[t]`; `Open[t]`/`Close[t]` are that
bar's open/close. With h=2 the label spans closes `Close[100] → Close[102]`.

| Index | Candle | Open | High/Low | Close | Information available |
|---|---|---|---|---|---|
| 100 | Candle t | Open[100] | … | Close[100] | After candle 100 **closes** (bar-open ts = 100, close ts = 100+30m) |
| 101 | Candle t+1 | Open[101] | … | Close[101] | At start of bar 101; `Open[101]` known the instant bar 101 begins |
| 102 | Candle t+2 | Open[102] | … | Close[102] | After candle 102 **closes** (= first close where a 2-bar-close label resolves) |
| 103 | Candle t+3 | Open[103] | … | Close[103] | After candle 103 **closes** |

Key timing instants (relative to bar-open labels):
- `feature_availability` and `prediction` for bar t: at `Close[100]` (= ts 100 + 30m).
- decision using P(up) from bar t: at/after `Close[100]`.
- earliest executable: `Open[101]` (start of bar t+1), the first tradable price after the decision.
- a "hold h=2 bars from Open[101]" exit: `Open[103]` (start of bar 103 = t+h+1).
- a "close-to-close h=2" exit: `Close[102]` (t+h close).

Numeric confirmation (read-only, real CSV):
```
t=100, h=2
Close[102]/Close[100] - 1 = 0.010367   <-- current label (T1)
Close[102]/Open[101]  - 1 = 0.010376   <-- entry Open[t+1], exit Close[t+h] (T2, mismatched span)
Open[103] /Open[101]  - 1 = 0.010367   <-- entry Open[t+1], exit Open[t+h+1] (T3, matched h=2 bars)
Close[102]/Close[101] - 1 = 0.006205   <-- Close[t+1]->Close[t+h] (only 1 close-interval; WRONG span)
```

---

## 3. Analisis definisi holding period (multiple candidates)

For each candidate we record: decision ts, entry ts/price, exit ts/price, candles actually
held, time interval, return formula, when label is known, and whether it is usable in a
realistic backtest.

### Candidate T1 — Existing Close-to-Close target
- Decision ts: `Close[100]` (after bar t).
- Entry: `Close[100]` (conceptually).
- Exit: `Close[102]`.
- Candles held: 2 close-intervals (`t→t+h`).
- Time interval: 2 × 30m = 60 min.
- Formula: `Close[100+2]/Close[100]-1`.
- Label known: at `Close[102]`.
- Realistic backtest? **NO** as an execution return. It assumes you can transact at the
  exact close of bar t (same-bar close fill) and exit at the exact close of bar t+h. This is
  a **statistical directional target**, suitable for classification, not for realized PnL.

### Candidate T2 — Next-bar open entry, close exit
- Decision ts: `Close[100]`.
- Entry: `Open[101]` (next bar open).
- Exit: `Close[102]`.
- Candles held: enters at start of bar 101, exits at close of bar 102 → spans bar 101 and
  bar 102 = **2 bars of exposure**, but the return is `(Close102/Open101)-1`, which is an
  **asymmetric boundary** (open-to-close across 2 bars, not a clean h-close or h-open span).
- Time interval: from Open[101] (ts 101) to Close[102] (ts 102 + 30m) ≈ 60 min of price time,
  but offset by one bar phase vs T1.
- Formula: `Open[101] × (1+r) = Close[102]` ⇒ `r = Close[102]/Open[101]-1`.
- Label known: `Close[102]`.
- Realistic? **Partially** — entry is realistic (`Open[t+1]`), but the exit `Close[t+h]`
  mixes price types and does not correspond to "hold h bars and exit at open". It is
  **defensible but impure**: the entry and exit are at different intra-bar phases.

### Candidate T3 — Next-bar open entry, matched h-bar open exit
- Decision ts: `Close[100]`.
- Entry: `Open[101]`.
- Exit: `Open[103]` (= `Open[t+h+1]`).
- Candles held: exactly **2 full bars** (bars 101 and 102), consistent open-to-open.
- Time interval: `ts[103] - ts[101]` = 2 × 30m = 60 min (open-to-open).
- Formula: `Open[t+h+1]/Open[t+1]-1`.
- Label known: `Open[103]` (start of bar t+h+1).
- Realistic? **YES, best of the three** — entry and exit at the SAME price type (market
  open), spans exactly h bars, no same-bar-close fill assumption. The only caveat: it shifts
  the label by one extra open beyond T1/T2 and thus changes target values; requires
  regenerating `fwd`/`y` with a new `target_definition_version`.

### (Rejected) Candidate — `Close[t+h]/Close[t+1]`
- Span is only 1 close-interval; **wrong holding period** for h=2 (shown numerically:
  `0.006205 ≠ 0.010367`). Rejected as an inconsistent interval.

---

## 4. Bandingkan opsi kontrak (T1 / T2 / T3)

| Criterion | T1 (Close→Close) | T2 (Open→Close, mismatched) | T3 (Open→Open, matched) |
|---|---|---|---|
| Time consistency | Consistent closes, but assumes close fill | Entry/exit at different intra-bar phase | Fully consistent (open→open) |
| Look-ahead bias risk | Low for features; **entry assumption optimistic** | Low (entry next bar), exit phase inconsistent | **Lowest** — next-bar open, no same-bar fill |
| Label ↔ PnL alignment | Weak (statistical only) | Partial | **Strong** (realizable open→open) |
| Data availability | Immediate (uses close) | Needs open+close (both present) | Needs open only (present) |
| Backtest compatibility | Poor for execution; fine for classification | Medium | **Best** |
| Impact on dataset/training | None (current) | Must recompute `fwd`; changes `target_definition_version`; shifts split/embargo anchors by 1 bar | Must recompute `fwd` entirely (`Open` series); new target version; split anchors unchanged in *index* but semantics shift |
| Holding-period correctness | h closes | ~h bars but boundary-mismatched | exactly h bars, matched |

**Assessment:** T1 is only a statistical target. T2 fixes entry realism but leaves an
open→close boundary mismatch. T3 is the only option where entry price type == exit price type
and the holding span equals exactly h bars.

**Recommendation (owner decides):** adopt **T3** as the execution-consistent contract, keep
T1 available as an auxiliary *classification* target if desired (dual-label), and use T2 only
if the owner prefers a close-marked exit for MT5 "exit at bar close" semantics — but then
document it as open→close explicitly. No final decision is taken here.

---

## 5. Transaction Cost Audit

| Cost component | Implementation evidence | Current behavior | Status |
|---|---|---|---|
| Spread | CSV `<SPREAD>` parsed by `loader`; `features.py:29-33` makes `spread_relative`=sp/median or 1.0 | Used ONLY as a normalized **feature**, not as a cost. Spread column mostly 0 (88.8%), integer **points**; units ambiguous (no point-size metadata). | Data PRESENT, cost model **UNRESOLVED** |
| Slippage | none in code | Not modeled anywhere | **UNRESOLVED** |
| Commission | none in code | Not modeled | **UNRESOLVED** |
| Swap | none in code | Not modeled (h=2 M30 mostly intraday, but unmodeled) | **UNRESOLVED** |
| Bid/Ask | CSV has single OPEN/HIGH/LOW/CLOSE (no separate bid/ask columns) | No bid/ask split; OHLC likely bid | **UNRESOLVED** |
| Spread fallback 1.0 | `features.py:32,33`: when `spread` absent OR non-finite → `spread_relative=1.0` | Feature-level neutral; **does not add cost** | VERIFIED (as feature behavior) |
| Gross vs net | `metrics.py`: gross only. `trading.py:86`: `direction*realized_forward_return - round_trip_cost_bps/10000` but path unused by `train_one` | Shipped reports/signals are **GROSS** | VERIFIED |

**Does the evaluator compute before or after costs?** **BEFORE (gross).**
`train_one` → `report.json` uses `metrics()` (no cost). `signals.csv` stores gross
`realized_forward_return`. `evaluate_signals_frame` *can* subtract one constant
`round_trip_cost_bps`, but that is not invoked by training.

**Consequence for model evaluation:** reported accuracy/AUC/brier reflect directional skill
on a *gross* close-to-close basis. A positive AUC does **not** imply positive expectancy after
spread/slippage. With EURUSD spread ≈ 5 points typical (data shows 50 in points on 5-digit
broker = 0.5 pip, and a median of ~4.5 bps of price when non-zero), a large fraction of
2-bar M30 moves are within spread — so **gross→net may flip sign** for many trades.
This must be resolved before any profitability claim.

**Do NOT invent spread/slippage values.** The point-size (1e-5 vs 1e-6, i.e. 5-digit vs
4-digit broker) is not recorded in the repo/config and must be provided by the owner/broker
spec before a numeric cost model can be ratified. Marked UNRESOLVED.

---

## 6. Source Code Evidence (data flow raw → label → prediction → evaluation)

```
raw CSV (<SPREAD>, <DATE>, <TIME>, OHLCV)
  └─ loader.load_bars  ......... ts = DATE+TIME (bar-open labels); spread parsed; sorted/dup-removed
       └─ features.build_features  shift/rolling/ewm only (trailing) → 29 cols incl spread_relative
            └─ pipeline.prepare    fwd[:-h] = close[h:]/close[:-h]-1 ; y=(fwd>0) ; mask=finite&notna
                 ├─ pipeline.split_indices       0.6/0.2 + embargo max(h,24)
                 ├─ walk_forward_scores          expanding folds=3, purge=horizon (R3: max(h,24))
                 └─ pipeline.train_one           fit → predict_proba(va/te)
                       ├─ metrics(y,p)            accuracy/AUC/brier/logloss (GROSS)
                       └─ signals.csv             direction (margin .03) + realized_forward_return=fwd[te]
evaluation of shipped files:
  └─ evaluator.trading.evaluate_signals_frame   direction*fwd - constant_bps (NOT wired to train_one)
runner: batch1_execution_runner.process_run → guard_execution_authorized (gate) → train/validate/promote
```

Specific citations:
- `pipeline.py:11-19` `prepare()`; **:16-17** label; :19 mask.
- `pipeline.py:22-29` `split_indices()`; **:26** validation start `+embargo`; :28 embargo on test.
- `pipeline.py:32-53` `walk_forward_scores()`; **:38** purge (`max(purge,horizon)`); :45-46 train/test slices.
- `pipeline.py:55-90` `train_one()`; **:58** split embargo `max(h,embargo)`; **:66** wf_purge; **:74** direction band; **:76** realized_forward_return.
- `features.py:3-40` `build_features()`; **:29-33** spread_relative.
- `metrics.py:1-16` `metrics()` — no cost.
- `trading.py:67-89` `evaluate_signals_frame()`; **:85-86** constant cost; **:89** records bps. Not called by training.
- `model.py:1-12` engine selection (lightgbm default, sklearn fallback).
- `loader.py:load_bars` — ts semantics + spread parsing.
- `batch1_execution_runner.py` — `guard_execution_authorized()` before dispatch.
- `authorization.py` — job-scoped fail-closed gate + HMAC sign-off verification.
- `timing_contract.py:build_timing_contract` — 11 fields, 6 NEW_DESIGN.
- `readiness.py:check_timing_ready` — UNRESOLVED unless ratified.

---

## 7. Six Timing Fields — Status

Legend: VERIFIED = proven by implementation; INFERRED = follows from code path/library
default; UNRESOLVED = no evidence/decision; CONFLICT = sources disagree.

| Field | Found in code | Proposed value | Status | Evidence |
|---|---|---|---|---|
| decision_timestamp | Not encoded; only a margin band at eval | `bar_t_close` (use P(up) from bar t) | **UNRESOLVED** (NEW_DESIGN) | `pipeline.py:74` direction band; no clock anywhere |
| earliest_executable_timestamp | Not encoded | `bar_t+1_open` | **UNRESOLVED** (NEW_DESIGN) | no venue/clock rule in repo |
| execution_price_model | Not encoded | `Open[t+1]` (T3 recommends open→open) | **UNRESOLVED** (NEW_DESIGN) | no execution sim; `trading.py` unused for cost |
| spread_usage | `spread_relative` feature only | feature + candidate cost (needs point-size) | **CONFLICT/UNRESOLVED**: prior report said "no spread column" — **FALSE**; column exists but sparse/points | `features.py:29-33`; CSV `<SPREAD>` |
| slippage_usage | none | none until defined | **UNRESOLVED** (NEW_DESIGN) | absent |
| cost_usage | only optional constant in unused path | define spread+slippage+commission; gross→net | **UNRESOLVED** (NEW_DESIGN) | `trading.py:85-86` unused by `train_one` |

Additional verified/other fields from `timing_contract.py`: `candle_close_timestamp`,
`feature_availability_timestamp`, `prediction_timestamp`, `prediction_horizon`,
`no_future_information_rule` = **PROVEN**.

No field is upgraded to VERIFIED without code evidence; the six design fields remain
UNRESOLVED/NEW_DESIGN until a human signs off.

---

## 8. Look-Ahead Bias Assessment

- **Features (predictions): SAFE.** `features.py` uses only trailing `.shift/.rolling/.ewm`;
  `test_features_have_no_future_dependency` (existing suite) proves tail perturbation never
  changes earlier rows. Prediction for bar t depends only on bars ≤ t.
- **Label: future-only, masked.** `fwd` uses future closes; `mask` excludes the last h rows;
  labels never enter features.
- **Split/purge: safe.** Chronological split + embargo `max(h,24)`; walk-forward folds purged
  by ≥ horizon; R3 uses `max(h,24)`. Training row t's `[t,t+h]` label never overlaps a
  test/validation row inside the gap.
- **Entry-price assumption is the only look-ahead risk axis.** T1 (close fill) is optimistic;
  T3 (next-bar open) removes same-bar-close fill. This is an *execution* concern, not a
  feature leakage.
- **Result:** Look-Ahead Safety for features/labels/splits = **PASS**; execution-entry
  optimality depends on the contract choice (owner decision).

---

## 9. Dampak terhadap Dataset dan Training

- **T1 (current):** no change; target_definition_version `target-b9c8f231d7fb8dbe` covers
  close-to-close. But it does not represent realizable PnL.
- **T2:** requires recomputing `fwd` to `Close[t+h]/Open[t+1]-1`; new
  `target_definition_version`; labels shift; mask must exclude rows lacking `Open[t+1]`.
  Split indices themselves are unchanged (they index eligible rows) but the label meaning
  changes → must re-hash target version and re-ratify.
- **T3:** requires recomputing `fwd` to `Open[t+h+1]/Open[t+1]-1`; the last h+1 rows become
  unlabeled (need `Open[t+h+1]`); new `target_definition_version`; embargo/split anchors in
  *index* terms still valid but the terminal masking grows by 1. This is the most
  execution-faithful and is the recommended contract subject to approval.
- **Costs:** any net-return evaluation requires wiring `evaluate_signals_frame`-style cost
  into the label/eval (currently disconnected), plus a ratified spread/slippage/commission
  and a point-size decision. Until then, train on **gross directional** signal only and
  never interpret accuracy as profitability.
- **Existing config/freeze impact:** `decision_time_policy` remains REQUIRES_DECISION; CONFIG
  still incomplete (`max_depth`, `l1_regularization`, `decision_time_policy`). Adopting T3
  would add a new target-definition ratification requirement.

---

## 10. Open Issues

1. **Spread metadata missing:** units/point-size (5- vs 4-digit) and whether `<SPREAD>` is
   per-bar, tick-average, or point-in-time — **must be provided** to model cost. 88.8% zeros
   means naive averaging is wrong.
2. **No bid/ask separation:** OHLC appears bid-only; ask-side entry cost unmodeled.
3. **No slippage/commission/swap models** anywhere.
4. **Cost path disconnected:** `evaluate_signals_frame(round_trip_cost_bps)` exists but is
   never called by `train_one`; reports are gross.
5. **Execution price type mismatch** between entry (open) and current label exit (close).
6. **Timestamp phase:** `ts` is bar-open; any external consumer assuming bar-close will be
   off by one bar unless documented.
7. **Prior-report inaccuracy:** "dataset has no spread column" is false (see §5) — prior
   readiness reasoning relied on it.
8. **Decision clock** is not encoded; only a static margin band exists.

---

## 11. Keputusan yang Memerlukan Persetujuan Pemilik Proyek

1. **Pilih kontrak eksekusi:** T1 (statistik saja) / T2 (open→close, mismatched) /
   **T3 (open→open, direkomendasikan)** / UNRESOLVED. Jika T3, setujui regenerasi target
   dan `target_definition_version` baru.
2. **Definisikan biaya transaksi:** berikan **point-size/spread units** dan model
   spread+slippage+commission (nilai konkret). Tanpa ini, biaya tetap UNRESOLVED.
3. **Setujui apakah evaluasi harus gross→net** (wiring cost ke evaluator) sebelum klaim
   profitabilitas.
4. **Ratifikasi 6 field timing** (decision clock, earliest executable, execution price,
   spread, slippage, cost) dengan sign-off.
5. **Putuskan target ganda** (T1 sebagai klasifikasi + T3 sebagai eksekusi) atau satu saja.
6. **Putuskan dokumentasi phase timestamp** (bar-open) untuk semua konsumen downstream.

---

## FINAL DECISION BLOCK

- Recommended Contract: **T3** (enter `Open[t+1]`, exit `Open[t+h+1]`) — *recommendation only; requires owner approval.*
- TIMING_READY: **UNRESOLVED** (contract not ratified; 6 NEW_DESIGN fields).
- Label-PnL Alignment: **FAIL** (T1 close-to-close ≠ realizable PnL; entry/exit price types mismatched for T2).
- Transaction Cost Readiness: **UNRESOLVED** (no net cost path; spread units/point-size missing; slippage/commission/swap absent).
- Look-Ahead Safety: **PASS** (features/labels/splits proven leakage-free; entry-price optimism is an execution choice, not leakage).
- Training Authorization: **BLOCKED**.

*End of audit. No code, config, database, execution log, dataset, model, status, sign-off,
training, dispatch, or promotion was modified or executed during this audit.*
