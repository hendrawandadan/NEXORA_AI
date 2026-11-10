# ECONOMIC OPPORTUNITY DISCOVERY v1.0 — Master Plan

**Status:** STAGE 0 complete (project & data inspection). **No code written, no data modified,
no models trained.** This document is the implementation plan awaiting authorization.

**Scope lock:** Read-only discovery. No production SQLite writes, no model retraining, no
ATR/R1/PREP-001 artifact changes, no deletion/overwrite of official reports. New outputs
only under `reports/economic_opportunity_discovery/` and a new isolated research package.

---

## 1. Mission (restated)

Determine whether a genuine, cost-surviving market opportunity exists for NEXORA **before**
building any model. Find the opportunity first; acquire information second; train only when
evidence justifies it. Never overclaim profitability.

The prior stage established (and we treat as locked, not re-litigated):
EURUSD M30 / h≈2 binary-direction is **economically infeasible** — best feature edge
≈0.097 pip/sd vs ≈3.2-pip round-trip cost (~3% of required). Root cause is economic
(signal magnitude ≪ cost), not architectural.

---

## 2. STAGE 0 — Inspection results (measured facts)

### 2.1 Files inspected
- `nexora_datahub/loader.py` — CSV reader, timeframe parsing, bar loader (handles tab/semicolon/comma, `<DATE>/<TIME>` MT5 export, dedup by timestamp, OHLC-NaN guard).
- `nexora_datahub/audit.py` — per-file data-quality auditor (duplicates, gaps, interval check, `<SPREAD>` points summary) + writes `*_normalized.csv` to `data/processed/`.
- `nexora_laboratory/cost_engine.py` — component-separated cost model (spread/slippage/commission/swap), two application modes (EXECUTABLE vs FLAT), explicit status labels.
- `nexora_laboratory/break_even.py` — symmetric + barrier break-even accuracy, `realized_move_sizes`, `feasibility_table`, `any_feasible`.
- `nexora_laboratory/feature_power.py` — OOS Spearman IC + block bootstrap + MI (from prior audit).
- `tools/run_signal_quality_audit.py` — prior read-only runner; documents the point→pip conversion convention (`points/10` on 5-digit EURUSD).
- `reports/fase2a/signal_quality_audit.json` — prior audit artifact (baseline real spread = 3.0 pips).

### 2.2 Data sources found (ground truth, actual files present)

| Symbol | Format | Coverage | Notes |
|---|---|---|---|
| EURUSD | MT5 bar export (tab, `<SPREAD>` in points) | 2020-01-02 → 2026-11-06 | All TF M1..MN1 present (raw + `processed/`). 5-digit → **10 pts = 1 pip**. Median-nonzero spread = 30 pts = **3.0 pips** (verified from prior audit). |
| GBPUSDm | **Exness tick (Bid/Ask)** per year | 2020 → 2025 | `data/raw/Exness_GBPUSDm_YYYY.csv`, ~13.9M rows/yr. Suffix `m` = Exness mini/raw account. **This is real bidirectional spread ground truth.** |
| USDJPYm | **Exness tick (Bid/Ask)** per year | 2020 → 2025 | Same schema; 3-digit quote → **point/pip factor differs from EURUSD**. |
| XAUUSD | Bar export (OHLCV + spread) | 2020 → 2026 | `data/raw/XAUUSD_*.csv` (22 TF) + `data/raw/XAUUSD/Exness_XAUUSDm_YYYY.zip` (tick zips). 2-digit price (0.01). |
| AUDUSD, USDCAD, USDCHF | **NOT FOUND** | — | No files on disk. → `DATA_UNAVAILABLE` unless we can obtain them (decision pending). |

### 2.3 Data gaps / honesty flags
- **AUDUSD, USDCAD, USDCHF: no data on disk** → will be reported `DATA_UNAVAILABLE`, NOT substituted with another broker.
- **Bid/Ask tick exists only for GBPUSDm, USDJPYm (and XAUUSDm zips)** — for **EURUSD, H1/H4 bar spread column is 88.8% zero** (documented in `cost_engine.py`); the honest real spread comes from the tick files where available, and from `<SPREAD>` medians where they exist.
- **Point→pip factor is per-instrument** (EURUSD 10 pts/pip; USDJPY 100 pts/pip ≈ 0.01; XAUUSD 1 pt = 0.01 price). Must be documented per symbol, never assumed universal.
- **Timezone**: Exness tick timestamps are `...Z` (UTC); MT5 bar exports may be broker server time. Alignment convention must be stated per analysis (block bootstrap + chronological; no cross-TF leakage).
- **XAUUSD has two bar sources** (`data/raw/XAUUSD_*.csv` vs zips) — must pick one canonical source and document it; do not mix.

### 2.4 Reusable components (avoid reinventing)
- `load_bars`, `read_export_csv`, `timeframe_minutes`, `parse_time` (datahub).
- `CostComponents`, `components_for_scenario`, `total_cost_fraction` (cost_engine).
- `realized_move_sizes`, `break_even_accuracy_symmetric/barrier`, `feasibility_table` (break_even).
- `audit_file` (datahub.audit) for per-file integrity.
These give ~60% of Horizon Discovery for free; new code focuses on tick→spread extraction, per-instrument pip factors, regime/period slicing, and scoring.

### 2.5 Existing uncommitted change (safety note)
`git status` shows one modified file: `.continue/agents/new-config.yaml` (IDE config only,
not project code/data). We will **not** touch it. No project files are dirty.

---

## 3. Proposed analysis (stages 1–7) & expected outputs

All new code isolated under a new package `nexora_laboratory/opportunity_discovery/`
(small modules) + runners in `tools/`. All outputs under `reports/economic_opportunity_discovery/`.
**Nothing overwrites existing reports.**

### STAGE 1 — Horizon Discovery (EURUSD first)
- Candidates: **M30 {8,16,24,48}**, **H1 {4,8,12,24}**, **H4 {2,4,8,12}** bars.
- Per combo: median/mean/P25/P50/P75/P90/P95 **absolute forward move**; pos/neg move dist; directional return dist; **MFE/MAE**; spread dist; gross **movement-to-cost ratio**; **break-even accuracy** (symmetric + barrier); **net expectancy** under optimistic/baseline/stress; **by regime** (vol buckets, session); **stability by calendar period** (yearly).
- Reuse `realized_move_sizes` + extend with full percentiles, MFE/MAE, pos/neg split.
- **No look-ahead**: features/selection use only past bars; forward stats are descriptive sizing only.
- Output: `HORIZON_DISCOVERY_REPORT.md` + `horizon_discovery.json`.

### STAGE 2 — Instrument Discovery
- Instruments with data: EURUSD, GBPUSDm, USDJPYm, XAUUSD. Unavailable: AUDUSD, USDCAD, USDCHF (`DATA_UNAVAILABLE`).
- Per instrument: date range, TF, bar count, missing %, duplicate ts count, **spread dist** (median/p90, from real bid/ask where tick data exists), **session-dependent spread**, volatility dist, **movement-to-cost ratio**, **data-quality score**.
- Exness specs distinguished from generic; **no fabricated** spread/commission/contract/tick value.
- Output: `INSTRUMENT_DISCOVERY_REPORT.md`, `data_availability/` artifacts.

### STAGE 3 — Transaction Cost Analysis
- Component model (reuse `cost_engine`): spread (real where tick exists), slippage (assumption, labelled), commission (Exness raw/standard — document account type or mark `NOT_AVAILABLE`), swap (only if holding spans overnight → for ≥H4/long h, flag).
- 3 scenarios Optimistic/Baseline/Stress; **baseline grounded in actual broker data**.
- Preserve original `<SPREAD>` points; document pts→pips→price per symbol.
- Output: `TRANSACTION_COST_ANALYSIS.md` + JSON; explicit one-way vs round-trip vs half-spread labels everywhere.

### STAGE 4 — Data Availability & Quality
- Consolidate STAGE 2 quality metrics into `DATA_AVAILABILITY_REPORT.md`; per-instrument quality score; explicit `DATA_UNAVAILABLE` list.

### STAGE 5 — New Information Assessment (design only, NO pipelines)
- Evaluate order flow, bid/ask volume, tick activity, microstructure, session liquidity, economic calendar, macro, news: for each — added information? why it explains price? historically available? timestamp-alignable? lookahead-safe? acquisition cost? OOS-validatable?
- Output: `NEW_INFORMATION_ASSESSMENT.md`.

### STAGE 6 — Economic Opportunity Assessment
- Transparent scoring: movement magnitude vs cost, cost stability, data quality, horizon stability, regime robustness, statistical uncertainty, execution feasibility.
- **No arbitrary weights to manufacture a winner**; every component explained; verdicts: `DATA_UNAVAILABLE | ECONOMICALLY_INFEASIBLE | RESEARCH_CANDIDATE | REQUIRES_NEW_INFORMATION | READY_FOR_CONFIRMATORY_EXPERIMENT`.

### STAGE 7 — Final Report + Decision Framework
- Answer the 7 questions in §13 of the instruction; **do not force positive**.
- Output: `ECONOMIC_OPPORTUNITY_FINAL_REPORT.md` + `reproducibility_manifest.json` (SHA256 of inputs+outputs) + `tests/` (calculations & data integrity).

---

## 4. Methodology guardrails (applied throughout)
Chronological order; no shuffle; no look-ahead; overlapping-horizon leakage prevented
(purge/embargo ≥ h); block bootstrap CIs; separate dev vs untouched validation; **record every
tested combination** (multiple-comparison ledger); never optimize on final test; label every
figure as measured / assumption / estimate / unresolved.

## 5. Safety boundaries (enforced)
Read-only on `data/`, `database/`, `models/`, `reports/fase2a/`, `reports/t3/`. Write only
under new `reports/economic_opportunity_discovery/` and new `nexora_laboratory/opportunity_discovery/`.
No production SQLite writes. No retraining. No ATR/R1/PREP-001 changes. No deletions.

## 6. Expected outputs (deliverables checklist)
- [x] ECONOMIC_OPPORTUNITY_DISCOVERY_PLAN.md (this file)
- [ ] HORIZON_DISCOVERY_REPORT.md
- [ ] INSTRUMENT_DISCOVERY_REPORT.md
- [ ] TRANSACTION_COST_ANALYSIS.md
- [ ] DATA_AVAILABILITY_REPORT.md
- [ ] NEW_INFORMATION_ASSESSMENT.md
- [ ] ECONOMIC_OPPORTUNITY_FINAL_REPORT.md
- [ ] *.json machine-readable artifacts
- [ ] reproducibility_manifest.json (SHA256)
- [ ] tests (calculation & data integrity)

---

## 7. Open questions requiring authorization (before STAGE 1 code)
1. **Instruments**: proceed with {EURUSD, GBPUSDm, USDJPYm, XAUUSD} and mark AUDUSD/USDCAD/USDCHF `DATA_UNAVAILABLE`? Or supply data for the missing three?
2. **XAUUSD canonical source**: `data/raw/XAUUSD_*.csv` bars (2020–2026) vs Exness tick zips (2020–2025)? Recommend bars for move stats + tick zips for spread; confirm.
3. **Slippage assumption**: keep `0.2 pip` baseline (as before) and stress `0.5 pip`? (Slippage is not in the data — it is an explicit assumption.)
4. **Commission**: Exness account type (raw/zero vs standard) for these `m`-suffix symbols? If unknown, mark `NOT_AVAILABLE` and run zero-commission baseline with a stressed-commission scenario.

**Awaiting authorization to proceed to STAGE 1 (Horizon Discovery) implementation.**
