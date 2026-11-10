# STAGE 1 — HORIZON DISCOVERY REPORT (EURUSD)

**Status:** Read-only. No training, no config/model/DB writes. Analysis on the
homogeneous intraday segment of each MT5 export.
**Artifact:** `horizon_discovery.json` (+ `horizon_discovery_manifest.json`, SHA256).
**Runner:** `tools/run_horizon_discovery.py`.

> Convention legend used everywhere below. **Move** = `|open[t+h]-open[t]|` (price),
> shown in pips (EURUSD 1 pip = 0.0001 = 10 broker points). **Cost** = round-trip
> (spread + slippage), in pips. **Ratio** = median move / round-trip cost.
> Move is a *realized, descriptive* quantity — it proves how large a move is
> available per horizon; it does **not** prove the direction is predictable.

---

## 0. Data-integrity findings (must precede any horizon claim)

1. **Daily-granularity prefix.** All EURUSD MT5 exports begin with a daily-bar
   prefix (2020) before true intraday bars appear. Horizon statistics therefore run
   **only on the homogeneous intraday segment**; the prefix is excluded and reported.

   | TF | Intraday segment starts | Daily-prefix rows excluded | Segment rows |
   |---|---|---|---|
   | M30 | 2021-06-14 11:00 | 3,302 | 67,392 |
   | H1 | 2020-12-18 14:00 | 302 | 36,733 |
   | H4 | 2020-12-18 12:00 | 302 | 9,555 |

   (The earlier suspicion that H4 was "daily" was the 2020 prefix; H4 is genuinely
   240-minute after 2020-12-18.)

2. **`<SPREAD>` column is sparsely populated — 88.8% zeros** over full history. A
   per-segment median is unreliable (M30 segment shows 1.5 pips, H1/H4 show 5.0
   pips, purely from which bars happen to carry a nonzero value). We therefore use a
   **single, documented EURUSD baseline** = full-history median-nonzero = **3.0 pips**
   (identical to the prior signal-quality audit), applied consistently to all TFs.

3. **No tick Bid/Ask exists for EURUSD** in this dataset (tick data is available only
   for GBPUSDm / USDJPYm / XAUUSDm). So EURUSD spread here is an **ESTIMATE**, not
   per-bar truth. STAGE 2 covers true-spread instruments.

---

## 1. Cost scenarios (explicit; baseline grounded in data)

| Scenario | Spread (pips) | Slippage (pips) | Round-trip (pips) | Basis |
|---|---|---|---|---|
| Optimistic | 1.5 | 0.2 | **1.7** | spread halved (floor 0.5) |
| **Baseline** | **3.0** | **0.2** | **3.2** | full-history median-nonzero `<SPREAD>` |
| Stress | 4.8 | 0.5 | **5.3** | ~p90 spread + higher slippage |

Slippage is an **ASSUMPTION** (not present in data). Commission omitted (EURUSD `m`
account type unknown → treated `NOT_AVAILABLE`, see STAGE 3). All figures are
**round-trip**.

---

## 2. Horizon economics (baseline = 3.2-pip round trip)

### EURUSD M30 (segment 2021-06-14 → 2026-11-06)
| h (bars) | hold | median move | move/cost | req. acc (sym) | req. acc (barrier) |
|---|---|---|---|---|---|
| 8  | 4h  | 9.3 pip  | 2.91 | 67.2% | 53.8% |
| 16 | 8h  | 14.2 pip | 4.44 | 61.3% | 49.0% |
| 24 | 12h | 18.4 pip | 5.75 | 58.7% | 47.0% |
| 48 | 24h | 27.9 pip | 8.72 | 55.7% | 44.6% |

### EURUSD H1 (segment 2020-12-18 → 2026-11-06)
| h | hold | median move | move/cost | req. acc (sym) | req. acc (barrier) |
|---|---|---|---|---|---|
| 4  | 4h  | 9.3 pip  | 2.91 | 67.2% | 53.8% |
| 8  | 8h  | 14.2 pip | 4.44 | 61.3% | 49.0% |
| 12 | 12h | 18.4 pip | 5.75 | 58.7% | 47.0% |
| 24 | 24h | 28.0 pip | 8.75 | 55.7% | 44.6% |

### EURUSD H4 (segment 2020-12-18 → 2026-11-06)
| h | hold | median move | move/cost | req. acc (sym) | req. acc (barrier) |
|---|---|---|---|---|---|
| 2  | 8h  | 13.4 pip | 4.19  | 61.9% | 49.6% |
| 4  | 16h | 21.3 pip | 6.66  | 57.5% | 46.0% |
| 8  | 32h | 31.9 pip | 9.97  | 55.0% | 44.0% |
| 12 | 48h | 39.4 pip | 12.31 | **54.1%** | 43.3% |

**Validation:** equal wall-clock horizons agree across timeframes (4h ≈ 9.3 pip;
8h ≈ 14.2; 12h ≈ 18.4; 24h ≈ 28) — the data is internally coherent.

**Key structural fact:** required **symmetric** accuracy falls toward ~50% as
horizon lengthens, reaching **54.1% at H4 h=12 (48h)** and **55.7% at 24h**. This is
the *structural* improvement over the retired M30 h=2 target (which needed ~86%).
It is **necessary but not sufficient** — no predictor is shown here to reach it.

---

## 3. Distribution shape (baseline, M30 & H4)

| TF/h | mean move | p90 move | MFE(long) | MAE(long) | frac_up | signed mean return |
|---|---|---|---|---|---|---|
| M30 h8  | 14.0 | 31.5  | 9.8  | 9.9  | 0.499 | −0.12 pip |
| M30 h48 | 37.1 | 80.8  | 28.2 | 29.6 | 0.485 | −0.67 pip |
| H4 h12  | 51.3 | 110.8 | 40.4 | 43.7 | 0.482 | −1.27 pip |

- **MFE ≈ MAE** at every horizon → no inherent long/short asymmetry in *excursions*.
- **`frac_up` ≈ 0.48–0.50** and **signed mean return slightly negative** at long
  horizons → a mild *downward drift* in EURUSD over this sample period. A long-only
  directional bet fights this drift; a short-only bet benefits but carries the same
  cost. This is a **sample characteristic**, not a guaranteed edge.
- p90 moves are large (e.g. 110 pips at H4 h=12) but the *median* is what sets the
  break-even requirement; tail size does not create directional edge.

---

## 4. Stability across periods (baseline ratio = median move / 3.2)

**Per-year move-to-cost ratio (selected), M30 & H4:**

- M30 h16: 2021 **6.5**, 2022 **11.9**, 2023 **8.7**, 2024 **6.6**, 2025 **9.4**, 2026 **7.4**.
- H4  h8:  2021 **16.0**, 2022 **25.6**, 2023 **21.5**, 2024 **15.3**, 2025 **20.9**, 2026 **15.5**.

Every year clears cost comfortably (ratio ≥ ~4 everywhere except partial 2020/2021
segments on H4). **The move-vs-cost relationship is stable and positive in all full
years** — there is no single regime that invalidates the opportunity *in magnitude*.
(H4 2020 is a 55-bar partial year; treat as non-representative.)

**Per-volatility regime (M30, all horizons):**

| Regime | h8 ratio | h16 ratio | h48 ratio |
|---|---|---|---|
| LOW  | 4.1 | 6.5 | 13.9 |
| MID  | 5.9 | 9.5 | 20.4 |
| HIGH | 8.4 | 13.0 | 27.1 |

Even the worst regime (LOW vol, short horizon) keeps move/cost ≈ 4×. A conditional
strategy targeting MID/HIGH regimes widens the ratio but shrinks the trade count.

---

## 5. What STAGE 1 PROVES and does NOT prove

**Measured facts.**
- Move magnitude grows ~linearly with horizon; cost is roughly constant (~3.2 pips).
- Move-to-cost ratio spans ~2.9× (4h) to ~12.3× (48h) and is stable across years/regimes.
- Required symmetric directional accuracy falls to **54.1% at 48h** (H4).

**Explicitly NOT proven.**
- That any model/feature achieves 54.1% (or even 51%). STAGE 1 measures *availability*
  of move, not *predictability* of direction.
- EURUSD spread truth (only a sparse-column estimate; no ticks).

**Unresolved.**
- The 54.1% bar at 48h is close to coin-flip, but the prior audit showed the technical
  feature set carries only a weak mean-reversion factor (edge ≈ 0.097 pip/sd). Whether
  that factor scales up at long horizons is an **open question for STAGE 6 /
  confirmatory experiment** — not answered here.

---

## 6. Preliminary verdict (horizon, EURUSD)

| Candidate | Move/cost (baseline) | Req. acc (sym) | Verdict |
|---|---|---|---|
| M30 h2 (retired) | ~1.4 | 85.6% | **ECONOMICALLY_INFEASIBLE** (prior) |
| M30 h8/h16 | 2.9 / 4.4 | 67% / 61% | **ECONOMICALLY_INFEASIBLE** (short) |
| M30 h48 | 8.7 | 55.7% | **RESEARCH_CANDIDATE** (weak) |
| H1 h24 | 8.75 | 55.7% | **RESEARCH_CANDIDATE** (weak) |
| H4 h8 | 10.0 | 55.0% | **RESEARCH_CANDIDATE** |
| **H4 h12 (48h)** | **12.3** | **54.1%** | **RESEARCH_CANDIDATE** (best magnitude) |

**Recommendation from STAGE 1:** the **H4 / 48-hour horizon** (and secondarily H1 h24
/ M30 h48) is the only region where move comfortably dominates cost *and* the
required accuracy is near coin-flip. It is a **research candidate**, NOT proven
profitable and NOT approved. It warrants the instrument comparison (STAGE 2, where
true tick spread on GBPUSDm/USDJPYm/XAUUSDm may flip the ranking) and a confirmatory
predictability test (STAGE 6) before any modeling.

**Do not model yet.** Next: STAGE 2 — Instrument Discovery (true-spread instruments).
