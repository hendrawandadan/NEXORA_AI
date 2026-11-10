# NEXORA — Handoff Notes: Economic Opportunity Discovery v1.0

> ⚠️ **GOVERNANCE: PRICE-DERIVED RESEARCH LANE = SUSPENDED (NEXORA-GOV-PRD-001, 2026-11-09).**
> Lihat `GOVERNANCE_DECISION_PRD_001.md` + `config/governance/price_derived_lane_suspension.json`.
> Tidak ada training/tuning/promosi/live/auto-reopen pada kandidat gagal. Penegakan kode:
> `nexora_laboratory/governance/lane_suspension.py` (`assert_can("train")` → raise).

**Dibuat:** akhir sesi (STAGE 1 selesai) — untuk dilanjutkan besok.
**Tujuan dokumen:** titik masuk cepat agar sesi berikutnya bisa langsung lanjut tanpa
mengulang konteks.

---

## 0. Ringkasan status

| Stage | Status | Deliverable |
|---|---|---|
| STAGE 0 — Project & data inspection | ✅ SELESAI | `ECONOMIC_OPPORTUNITY_DISCOVERY_PLAN.md` |
| STAGE 1 — Horizon Discovery (EURUSD) | ✅ SELESAI | `HORIZON_DISCOVERY_REPORT.md` + `horizon_discovery.json` + `horizon_discovery_manifest.json` |
| STAGE 2 — Instrument Discovery | ✅ SELESAI | `INSTRUMENT_DISCOVERY_REPORT.md` + `instrument_discovery.json` + manifest |
| STAGE 3 — Transaction Cost Analysis | ✅ SELESAI | `TRANSACTION_COST_ANALYSIS.md` + `transaction_cost_analysis.json` + manifest |
| STAGE 4 — Data Availability & Quality | ✅ SELESAI | `DATA_AVAILABILITY_REPORT.md` + `data_availability.json` + manifest |
| STAGE 5 — New Information Assessment | ✅ SELESAI | `NEW_INFORMATION_ASSESSMENT.md` + `new_information_assessment.json` + manifest |
| STAGE 6 — Economic Opportunity Assessment | ✅ SELESAI | `ECONOMIC_OPPORTUNITY_FINAL_REPORT.md` (bagian skoring) + `opportunity_assessment.json` + manifest |
| STAGE 7 — Final Research Report | ✅ SELESAI | `FINAL_RESEARCH_REPORT.md` + `FINAL_RESEARCH_DECISION.md` + `final_research_report.json` + `final_research_manifest.json` |
| STAGE 7b (post) — Walk-Forward Validation | ✅ SELESAI | `WALKFORWARD_VALIDATION_REPORT.md` + `walkforward_validation.json` + manifest |
| Governance — Lane Suspension (GOV-PRD-001) | ✅ DITEGAKKAN | `GOVERNANCE_DECISION_PRD_001.md` + `config/governance/price_derived_lane_suspension.json` + guard |
| Autonomous Arch — Tahap D (Control Loop) | ✅ SELESAI | `STAGE_D_CONTROL_LOOP_REPORT.md` + `nexora_research/control_loop.py` + `tests/test_control_loop.py` |
| Autonomous Arch — Tahap E (Strategy Evolution) | ✅ SELESAI | `STAGE_E_STRATEGY_EVOLUTION_REPORT.md` + `nexora_research/strategy_evolution.py` + `tests/test_strategy_evolution.py` |

**Tes:** **Full suite: 534 passed** (STAGE 0-7 + walk-forward + governance + Tahap D/E; tidak ada regresi). Detail per-stage di bagian 3/3b/3c/3d/3e/3f/3g/3h/3i/3j.

**FINAL VERDICT (STAGE 7): `READY_WITH_CONDITIONS`** — lanjut riset bersyarat (walk-forward
+ net-of-cost), **BUKAN** training/live. Edge prediktif: **NOT ESTABLISHED**.

**WALK-FORWARD (STAGE 7b): kondisi TIDAK terpenuhi → rekomendasi TUTUP JALUR.** 0/20
feature×horizon stabil robust. Kandidat top XAUUSD D1 GAGAL (0/8). Survivor tunggal
EURUSD `rng_60` h12 rapuh terhadap jumlah fold + biaya estimasi. Lihat bagian 3h.

---

## 1. Kondisi environment (penting — bikin hemat waktu)

- **Python wajib pakai venv:** `.\.venv\Scripts\python.exe`
- **WAJIB set PYTHONPATH ke root repo** sebelum menjalankan runner/tes:
  ```powershell
  $env:PYTHONPATH="."
  ```
  (tanpa ini → `ModuleNotFoundError: No module named 'nexora_datahub'`)
- `pytest` TIDAK ada di python global; harus lewat `.venv`.
- Shell = **PowerShell (win32)**. `2>/dev/null` tidak jalan; pakai `2>$null`.
- File tick Exness sangat besar (GBPUSDm ~13.9jt baris/tahun) → **JANGAN** `Get-Content`
  per baris (timeout). Parse via Python chunked/aggregate.

Perintah cepat:
```powershell
$env:PYTHONPATH="."
.\.venv\Scripts\python.exe -m pytest tests/test_opportunity_discovery.py -q
.\.venv\Scripts\python.exe tools/run_horizon_discovery.py
```

---

## 2. Aturan proyek (LOCKED — jangan dilanggar)

- Read-only untuk `data/`, `database/`, `models/`, `reports/fase2a/`, `reports/t3/`.
- **Tidak boleh:** retrain model, ubah SQLite produksi, ubah config ATR/R1/PREP-001,
  hapus file, timpa report lama, ubah logika eksekusi.
- Output baru HANYA di: `reports/economic_opportunity_discovery/` dan package baru
  `nexora_laboratory/opportunity_discovery/`.
- Konvensi harga: **1 pip EURUSD = 0.0001 = 10 broker points**. Faktor pip
  **BERBEDA per instrumen** (USDJPY=0.01, XAUUSD=0.10) — lihat `pip_size_for()`.
- Satu-satunya perubahan git yang "kotor" sebelumnya = `.continue/agents/new-config.yaml`
  (config IDE, BUKAN proyek). Jangan disentuh.

---

## 3. Temuan kunci STAGE 1 (yang perlu diingat)

1. **Daily-granularity prefix**: semua export MT5 EURUSD diawali bar harian (2020)
   sebelum bar intraday asli. Horizon hanya dihitung pada segmen intraday homogen:
   - M30 mulai **2021-06-14**, H1 & H4 mulai **2020-12-18**.
2. **Kolom `<SPREAD>` = 88.8% nol** → tidak reliabel per-bar. Dipakai baseline tunggal
   EURUSD = **3.0 pips** (median-nonzero full-history, sama dgn audit sebelumnya).
3. **Tidak ada tick Bid/Ask untuk EURUSD** → spread = *estimasi*. Hanya GBPUSDm /
   USDJPYm / XAUUSDm yang punya tick asli.

**Skenario biaya (round-trip):** optimistic 1.7 / **baseline 3.2** / stress 5.3 pips.

**Hasil horizon (baseline):** move/cost ratio naik dari ~2.9 (4 jam) ke **12.3 (48 jam,
H4 h12)**; required symmetric accuracy turun ke **54.1%** di 48 jam. Stabil lintas tahun
& regime vol. **TAPI ini hanya "ketersediaan move", BUKAN bukti prediktabilitas.**

**Verdict sementara:** M30 h8/h16 = ECONOMICALLY_INFEASIBLE; **H4 h12 (48 jam) =
RESEARCH_CANDIDATE** (terbaik), plus H1 h24 & M30 h48. Belum untung, belum disetujui.

Catatan tambahan: ternyata ada **sedikit downward drift** EURUSD (frac_up ≈ 0.48–0.50,
signed mean return sedikit negatif di horizon panjang) — karakter sampel, bukan edge.
MFE ≈ MAE di semua horizon (tidak ada asimetri long/short bawaan).

---

## 3b. STAGE 2 — SELESAI (ringkasan untuk sesi berikutnya)

Deliverable: `INSTRUMENT_DISCOVERY_REPORT.md`, `instrument_discovery.json`,
`instrument_discovery_manifest.json`. Runner: `tools/run_instrument_discovery.py`
(streaming tick zip; ~6 menit full). Modul baru: `opportunity_discovery/tick_spread.py`,
`bar_quality.py`. Tes: `tests/test_instrument_discovery.py` (11 lulus; full suite 375).

**Temuan kunci STAGE 2 (dipakai STAGE 3):**
- **Spread tick NYATA** (median pips): GBPUSDm **1.15**, USDJPYm **1.05**, XAUUSDm **2.05**
  (mean 1.33 / 1.26 / 2.36; p99 6.85 / 7.85 / 9.05). Sangat **stabil antar sesi utama**.
- **Sesi LATE (rollover ~21–24 UTC) mahal** (median GBPUSDm 1.55/USDJPY 1.85; mean 4+ pip)
  → hindari eksekusi LATE di riset lanjut.
- **Koreksi asumsi biaya**: asumsi bar overestimate spread (XAU 25→2.05 = 12×, GBP 3.0→1.15,
  JPY 2.0→1.05). Gunakan spread tick nyata ini di STAGE 3, **bukan** asumsi bar.
- **Kualitas data**: XAUUSD bar grade **A** (bersih, no prefix); EURUSD bar grade **C**
  (daily-prefix + kolom <SPREAD> 88% nol → tetap estimasi).
- **XAUUSD(emas) kandidat prioritas** (data A + move besar; spread tick 2.05 pip), EURUSD
  H4/h12 tetap kandidat (baseline estimasi). **Semua = ketersediaan move, BUKAN profit.**
- XAUUSDm tick coverage berhenti **2025-07-20** (bar ada s/d 2026; tick tidak). GBP/USDJPY
  tick 2020–2025 penuh.
- AUDUSD/USDCAD/USDCHF = **DATA_UNAVAILABLE** (tidak ada file).

**Untuk STAGE 3:** pakai `instrument_discovery.json` sebagai sumber spread nyata per-sesi;
bangun skenario biaya (optimistic/baseline/stress) dari median + p90/p99 tick, sertakan
komisi = NOT_AVAILABLE (Exness type tidak diketahui) + jalankan baseline 0-komisi & stress.

## 3c. STAGE 3 — SELESAI (ringkasan untuk sesi berikutnya)

Deliverable: `TRANSACTION_COST_ANALYSIS.md`, `transaction_cost_analysis.json`, manifest.
Runner: `tools/run_transaction_cost_analysis.py` (butuh STAGE 2 JSON). Modul baru:
`opportunity_discovery/cost_model.py`. Tes: `tests/test_cost_model.py` (16 lulus; full suite **391**).

**Model biaya:** `spread (terukur) + slippage (asumsi) + komisi (NOT_AVAILABLE=0)`.
Skenario dari spread terukur: optimistic=p50, **baseline=p90** (konservatif), stress=p99.

**Skenario round-trip (baseline komisi=0):**
| Instrumen | optimistic | **baseline** | stress |
|---|---|---|---|
| GBPUSDm | 1.35 | **1.75** | 7.35 |
| USDJPYm | 1.25 | **1.35** | 8.35 |
| XAUUSDm | 2.55 | **3.55** | 10.55 |
| EURUSD (est) | 3.2 | **5.0** | 9.5 |

**Temuan kunci STAGE 3 (dipakai STAGE 6 skoring):**
- **Emas termurah relatif**: cost drag baseline hanya **2–5%** dari move (H4:h12 drag 2.3%,
  move/cost 43.6). **Tidak ada crossover.**
- **EURUSD paling mahal relatif**: drag **13–27%** (M30:h24 27%, H4:h12 12.7%). Margin tipis.
- **Sesi LATE mahal untuk FX majors** (GBP LATE 1.75 vs 1.35; JPY 2.05 vs 1.25) → **hindari
  LATE**. **Emas spread datar antar sesi** → aturan LATE **tidak** berlaku untuk emas.
- **Komisi NOT_AVAILABLE** (band 0). Bila akun berkomisi → tambahkan (`--commission-pips`),
  arahnya selalu menaikkan biaya. Tidak ada angka komisi dikarang.
- **Biaya nyata jauh < asumsi bar STAGE 1** — kandidat yang tampak "infeasible" bisa berubah.
  Tetapi **murah ≠ edge**; IC OOS belum diuji (STAGE 5).

**Untuk STAGE 4 (Data Availability & Quality):** konsolidasi status ketersediaan per instrumen
(apa ada: bar/tick, cakupan tahun, grade kualitas) + tandai gap (XAUUSDm tick hanya s/d
2025-07-20; EURUSD tanpa tick; komisi tak diketahui; AUD/USD/CAD/CHF DATA_UNAVAILABLE).
Gunakan `instrument_discovery.json` + `transaction_cost_analysis.json` sebagai sumber.

## 3d. STAGE 4 — SELESAI (ringkasan untuk sesi berikutnya)

Deliverable: `DATA_AVAILABILITY_REPORT.md`, `data_availability.json`, manifest.
Runner: `tools/run_data_availability.py` (butuh STAGE 2 + 3 JSON). Modul baru:
`opportunity_discovery/availability.py`. Tes: `tests/test_availability.py` (13 lulus; full suite **404**).

**Readiness (transparan; bobot quality .35 / depth .30 / cost .20 / coverage .15):**
| Instrumen | Verdict | Readiness | Catatan |
|---|---|---|---|
| **XAUUSDm** | READY | 1.00 | bars+tick, grade A, 5.55 th, 41.8k bar |
| XAUUSD | READY | 0.98 | bars grade A + tick via sibling |
| EURUSD | READY | 0.777 | bars grade C, 6.84 th; spread **estimasi** |
| GBPUSDm | PARTIAL | 0.675 | **tick lengkap, TANPA bar OHLC** |
| USDJPYm | PARTIAL | 0.675 | **tick lengkap, TANPA bar OHLC** |
| AUDUSD/USDCAD/USDCHF | NOT_READY | 0.00 | DATA_UNAVAILABLE |

**Gap eksplisit:** komisi NOT_AVAILABLE (semua); spread estimasi (EURUSD); **GBPUSDm &
USDJPYm tak punya bar OHLC** (hanya tick zip — diverifikasi); XAUUSDm tick terpotong
(s/d 2025-07-20, bar s/d 2026); AUD/USD/CAD/CHF tidak ada file.

**Untuk STAGE 5 (New Information Assessment = IC OOS):**
1. **Prioritas: XAUUSD** (READY, grade A, histories H4 41k bar + tick biaya) → uji
   fitur → forward-return IC secara OOS (train/test split temporal).
2. **EURUSD** (READY 0.78, 6.8 th) cadangan, tapi cost estimasi → interpretasi hati-hati.
3. **GBPUSDm/USDJPYm**: prasyarat **bangun bar OHLC (M30/H1/H4) dari tick** dulu
   (streaming, hati-hati memori), baru bisa hitung move/fitur/IC.
4. AUD/USD/CAD/CHF: tetap DATA_UNAVAILABLE.
5. STAGE 5 harus jujur: IC OOS + uji signifikansi + koreksi multiple-comparison
   (reuse `horizon`/multiple-comparison ledger pattern). NO look-ahead, NO in-sample overfit.

## 3e. STAGE 5 — SELESAI (ringkasan untuk sesi berikutnya)

Deliverable: `NEW_INFORMATION_ASSESSMENT.md`, `new_information_assessment.json`, manifest.
Runner: `tools/run_new_information_assessment.py`. Modul baru: `opportunity_discovery/information.py`.
Tes: `tests/test_information.py` (12 lulus; full suite **416**).

**Metode (model-free, tanpa look-ahead):** fitur kausal (ret/zscore/vol/range/posrng/rsi,
k∈{5,20,60}) → forward return; **Spearman IC** pada split temporal TRAIN 70 / TEST 30;
**BH-FDR + Bonferroni**. XAUUSDm (utama, bar spot XAUUSD grade A) + EURUSD (cadangan).

**HASIL — PENTING & JUJUR (jangan di-overclaim):**
- Banyak fitur "signifikan OOS" (XAUUSD H1 15/36 BH; EURUSD H4 22/54) **TAPI**:
  - **IC TRAIN ≈ 0** untuk hampir semua survivor → informasi hanya muncul di test.
  - **Tanda IC berbalik train vs test** (XAUUSD `rng_20` h24: train +0.020 → test −0.083).
  - **IC terkonsentrasi 1 tahun** (XAUUSD 2023 −0.26; EURUSD `vol_60` 2025 +0.167 → 2026
    +0.002 **hilang**).
  - Magnitudo kecil (|IC| ~0.05–0.17).
- **Kesimpulan: BELUM ada informasi forward yang STABIL.** Yang terlihat = **regime-specific
  artifact**, bukan edge. Ini temuan negatif yang sah.

**Kandidat HIPOTESIS (belum tervalidasi) untuk STAGE 6:** XAUUSD H1/H4 `rng/vol` (IC
**negatif**: range/vol tinggi → forward return bawah). Butuh **walk-forward** (bukan 1 split)
+ **net-of-cost** (STAGE 3) sebelum boleh naik skor.

**Untuk STAGE 6 (Economic Opportunity Assessment = skoring):**
- Skor peluang harus **rendah** kecuali walk-forward membuktikan stabilitas (belum ada).
- JANGAN menaikkan skor hanya karena "lolos BH" — cek tanda & stabilitas per-tahun
  MEMBATALKANNYA.
- Gabungkan: ketersediaan move (STAGE 1/2) + biaya nyata (STAGE 3) + kesiapan data (STAGE 4)
  + IC OOS (STAGE 5) → verdict per instrumen/horizon. Sertakan rekomendasi walk-forward
  sebagai langkah lanjut yang jujur.

## 3f. STAGE 6 — SELESAI (ringkasan untuk sesi berikutnya)

Deliverable: `ECONOMIC_OPPORTUNITY_FINAL_REPORT.md` (bagian skoring), `opportunity_assessment.json`,
manifest. Runner: `tools/run_opportunity_assessment.py`. Modul baru: `opportunity_discovery/scoring.py`.
Tes: `tests/test_scoring.py` (17 lulus; full suite **433**).

**Model skor:** `0.25·economics + 0.20·cost_burden + 0.20·data_readiness + 0.35·signal_quality`.
Movement-to-cost & cost-drag pakai **biaya NYATA STAGE 3**. Signal quality **STRICT** (base·train·sign;
train≈0 atau sign-flip → ~0). **Verdict gating:** signal <0.10 → WATCH_ECONOMICS_ONLY; <0.30 → WATCH;
≥0.30 & score≥0.65 → RESEARCH_CANDIDATE. Economics/data **tak bisa** sendiri jadikan kandidat.

**Hasil (cost=baseline):**
- **RESEARCH_CANDIDATE (3):** XAUUSD **D1 h2** (0.824, sig .52, `ret_5` searah, **n_test≈497 tipis**),
  XAUUSD **D1 h1** (0.769, n≈498), EURUSD **H4 h12** (0.692, sig .47, **n≈2854**, tapi cost estimasi).
- **WATCH (8):** XAUUSD H1 h24/H4 h12/h8/h4, EURUSD H4 h8, H1 h24/h12, H4 h4 (fitur tanda berbalik
  atau sinyal lemah → sengaja TIDAK jadi kandidat).
- **WATCH_ECONOMICS_ONLY (1):** XAUUSD H1 h12 (ekonomi bagus, sinyal tak stabil).

**Kesimpulan jujur:** 3 kandidat = **hipotesis**, belum peluang nyata. XAUUSD D1 skor tertinggi tapi
sampel tipis; EURUSD H4 h12 sampel tebal tapi biaya estimasi. **Tidak ada klaim profit/backtest/signal.**

**Untuk STAGE 7 (Final Research Report):** rangkum STAGES 0–6 jadi satu laporan riset final,
sertakan rekomendasi eksplisit: **walk-forward multi-split** (XAUUSD `ret_5` D1/H4, EURUSD `ret_60`
H4 h12) + **net-of-cost** + konfirmasi komisi; bila walk-forward tak stabil → tutup jalur. Tegaskan
tidak ada klaim profit.

## 3g. STAGE 7 — SELESAI (konsolidasi & audit; READ-ONLY)

Deliverable: `FINAL_RESEARCH_REPORT.md` (A–J), `FINAL_RESEARCH_DECISION.md`,
`final_research_report.json`, `final_research_manifest.json`. Tes: `tests/test_final_research_report.py`
(35 lulus; full suite **468**). Tidak ada training/eksperimen baru; hanya audit bukti STAGE 0–6.

**FINAL VERDICT UTAMA:** `READY_WITH_CONDITIONS`.

**Lima status (terpisah, jangan disamakan):**
| Dimensi | Status |
|---|---|
| Technical Implementation | ✅ SUCCESS |
| Research Execution | ✅ SUCCESS |
| Predictive Edge Evidence | ❌ NOT ESTABLISHED |
| Training Readiness | ❌ NOT READY |
| Production / Live Readiness | ❌ NOT READY / NOT AUTHORIZED |

**Alasan verdict:** infrastruktur reproducible + kandidat ekonomi jelas ada (cukup untuk lanjut
riset), TAPI sinyal forward tidak stabil (artefak rezim), biaya EURUSD estimasi, komisi N/A,
XAU D1 sampel tipis → **bukan** izin training/live.

**KONDISI melanjutkan:** (1) walk-forward multi-split membuktikan IC searah & stabil lintas
split/rezim; (2) net-of-cost + komisi nyata masih bermargin; (3) sampel cukup. Bila gagal →
**tutup jalur**.

**Rekomendasi penelitian lanjut (butuh keputusan user terpisah):**
- Walk-forward validation: XAUUSD `ret_5`/`zclose_5` (D1/H4), EURUSD `ret_60` (H4 h12).
- Net-of-cost band STAGE 3 + konfirmasi komisi Exness.
- Perbaikan data: tick EURUSD; bangun OHLC dari tick untuk GBPUSDm/USDJPYm.

**Catatan handoff:** STAGE 0–7 **SELESAI**. STAGE 8 / Autonomous Research Architecture D/E /
training otomatis **TIDAK** dimulai — butuh keputusan terpisah. Master Development Roadmap
**tidak** diubah otomatis.

## 3h. Walk-Forward Multi-Split Validation — SELESAI (penelitian baru, bukan STAGE 8)

Deliverable: `WALKFORWARD_VALIDATION_REPORT.md`, `walkforward_validation.json`, manifest.
Runner: `tools/run_walkforward_validation.py` (`--folds N`). Modul baru:
`opportunity_discovery/walkforward.py`. Tes: `tests/test_walkforward.py` (13 lulus; full suite **481**).
Metode: expanding-window K-fold, **purging** di batas fold, **tanpa look-ahead**. Stabilitas
butuh: sign-consistency ≥0.80, signifikan ≥60% fold, non-dominance ≤0.60, |median IC| ≥0.02.

**HASIL — TIDAK STABIL (0/20 robust):**
- **XAUUSD D1 h1/h2 (kandidat top STAGE 6): GAGAL 0/8.** `ret_5` tanda berbalik (4/6);
  `zclose_5`/`rng_60` tanda konsisten 6/6 **tapi 0 fold signifikan** (|IC| ~0.03–0.04 lemah).
- **XAUUSD H4: GAGAL 0/8** (IC antar-fold berbalik ekstrem).
- **EURUSD H4 h12:** `rng_60` sempat STABLE di fold=5,6 **TAPI rapuh**: gagal di fold=4,7,8,10
  (alasan berbeda). Bukan stabilitas sejati + biaya estimasi → tak dipercaya.

**KESIMPULAN: kondisi STAGE 7 (walk-forward stabil) TIDAK terpenuhi → rekomendasi TUTUP JALUR**
untuk fitur momentum/price-derived pada data saat ini. Tidak ada klaim profit/edge.

**Yang bisa membuka jalur lagi (butuh keputusan user terpisah):** data baru (tick EURUSD,
bar OHLC dari tick GBP/USDJPY); hipotesis baru (bukan fitur yang sudah gagal) dengan protokol
walk-forward sama; net-of-cost hanya relevan bila ada sinyal stabil (saat ini tidak).

## 3i. Autonomous Research Architecture — Tahap D (Control Loop) — SELESAI

Deliverable: `STAGE_D_CONTROL_LOOP_REPORT.md`, `nexora_research/control_loop.py`, `tests/test_control_loop.py` (12 lulus; full suite **520**). Orkestrasi Tahap A/B/C jadi state machine ter-gate.

**State machine:** OBSERVE → HYPOTHESIZE → EXPERIMENT_SPEC → (per hipotesis) gate **feasibility** + gate **governance** → READY_FOR_CONFIRMATORY_EXPERIMENT / BLOCKED_GOVERNANCE / SKIPPED_INFEASIBLE / FAILURE_LEARNING → KNOWLEDGE_MEMORY (hanya non-dry-run).

**Guardrail ditegakkan:** (1) **governance** — kandidat price-derived tersuspensi → `BLOCKED_GOVERNANCE` (terbukti: XAUUSD D1 h2/H4 h12 & EURUSD H4 h12 diblokir); (2) max verdict = `READY_FOR_CONFIRMATORY_EXPERIMENT` (tidak pernah GO/LIVE/PROFIT); (3) **no production side-effects** (dry_run tak tulis apa pun; hanya DB riset terpisah); (4) **failure must teach**; (5) **no training** (Tahap F, out of scope).

**Smoke pada data nyata:** EURUSD → 10 READY + 1 BLOCKED (H4 h12); XAUUSD → semua BLOCKED. Tidak ada klaim profit.

**Belum:** training nyata (Tahap F, butuh izin), scheduler cadence. JANGAN auto-jalankan training / auto-reopen.

## 3j. Autonomous Research Architecture — Tahap E (Strategy Evolution) — SELESAI

Deliverable: `STAGE_E_STRATEGY_EVOLUTION_REPORT.md`, `nexora_research/strategy_evolution.py`, `tests/test_strategy_evolution.py` (14 lulus; full suite **534**). Generator usulan strategi berbasis **Knowledge Memory** — setiap usulan WAJIB `change_basis` (kondisi reopening), menolak pengulangan dead-end, deterministik, TIDAK melatih/registrasi sendiri (caller pakai `to_hypothesis()` + `pre_register`).

**3 aturan:** `R_EVOLVE_NEW_INFO_SOURCE` (NO_PREDICTIVE_POWER → akuisisi info baru, lane INFO_ACQUISITION), `R_EVOLVE_HORIZON_SHIFT` (EDGE_BELOW_COST/OVERFIT/REGIME → horizon 2×, lane PRICE_DERIVED), `R_EVOLVE_INSTRUMENT_TRANSFER` (GO → instrumen lain, lane PRICE_DERIVED).

**Hasil governance (penting):** lane SUSPENDED → `R_EVOLVE_NEW_INFO_SOURCE` **ALLOWED** (kondisi reopening #1, satu-satunya jalur maju jujur); semua usulan `R_EVOLVE_HORIZON_SHIFT`/`TRANSFER` (price-derived) **BLOCKED_GOVERNANCE** (butuh otorisasi reopening). Append-only `STRATEGY_LEAD`, no production side-effects.

**Loop kognitif LENGKAP (A→E).** Belum: training nyata (Tahap F, butuh izin), akuisisi data baru (tindakan pengguna), scheduler. JANGAN auto-jalankan / auto-reopen.

## 4. Yang harus dikerjakan besok → STAGE 2 (Instrument Discovery)

**Target instrumen & data yang ADA di disk:**
| Simbol | Format | Cakupan | Spread asli? |
|---|---|---|---|
| EURUSD | MT5 bar | 2020–2026 | ❌ (kolom jarang) |
| GBPUSDm | **Exness tick Bid/Ask** | 2020–2025 | ✅ `data/raw/Exness_GBPUSDm_YYYY.csv` |
| USDJPYm | **Exness tick Bid/Ask** | 2020–2025 | ✅ `data/raw/Exness_USDJPYm_YYYY.csv` |
| XAUUSD | bar `data/raw/XAUUSD_*.csv` + tick zip `data/raw/XAUUSD/Exness_XAUUSDm_YYYY.zip` | 2020–2026 | ✅ (zip) |
| AUDUSD, USDCAD, USDCHF | — | — | ❌ **DATA_UNAVAILABLE** |

**Langkah teknis untuk tick (hati-hati memori):**
- Baca tick CSV chunked (`pandas.read_csv(..., chunksize=...)`), kolom: `Timestamp,Bid,Ask`.
- Hitung spread `(Ask-Bid)` → konversi ke pips per instrumen (`pip_size_for`).
- Agregasi per-jam → distribusi spread (median/p90) **per sesi** (Asia/London/NY).
- Jangan simpan raw tick; simpan hanya agregat ke JSON.

**Field yang wajib dikumpulkan per instrumen:** rentang tanggal, timeframe tersedia,
jumlah bar, % missing, jumlah duplikat timestamp, distribusi spread, spread per sesi,
distribusi volatilitas, movement-to-cost ratio, skor kualitas data.

**Deliverable STAGE 2:** `INSTRUMENT_DISCOVERY_REPORT.md` + JSON + (idealnya) tes data
integrity. Pisahkan spesifikasi Exness dari asumsi generik; JANGAN mengarang
spread/commission/contract/tick value.

---

## 5. Pertanyaan terbuka yang masih perlu keputusan user

1. **Instrumen:** lanjut {EURUSD, GBPUSDm, USDJPYm, XAUUSD} + tandai AUDUSD/USDCAD/USDCHF
   `DATA_UNAVAILABLE`? (default: ya) atau sediakan data 3 pair itu?
2. **XAUUSD sumber kanonik:** bar (`data/raw/XAUUSD_*.csv`) untuk move + tick zip untuk
   spread? (default: ya)
3. **Slippage:** baseline 0.2 pip, stress 0.5 pip (asumsi eksplisit)? (default: ya)
4. **Commission:** tipe akun Exness (raw/standard) untuk simbol suffix `m`? Jika tidak
   diketahui → tanda `NOT_AVAILABLE` + jalankan baseline 0-komisi + skenario stress. (default: ya)

---

## 6. File yang dibuat di sesi ini (untuk referensi)

**Kode (isolated, baru):**
- `nexora_laboratory/opportunity_discovery/__init__.py`
- `nexora_laboratory/opportunity_discovery/granularity.py`
- `nexora_laboratory/opportunity_discovery/moves.py`
- `nexora_laboratory/opportunity_discovery/horizon.py`
- `tools/run_horizon_discovery.py`
- `tests/test_opportunity_discovery.py`

**Laporan (baru):**
- `reports/economic_opportunity_discovery/ECONOMIC_OPPORTUNITY_DISCOVERY_PLAN.md`
- `reports/economic_opportunity_discovery/HORIZON_DISCOVERY_REPORT.md`
- `reports/economic_opportunity_discovery/horizon_discovery.json`
- `reports/economic_opportunity_discovery/horizon_discovery_manifest.json`
- `reports/economic_opportunity_discovery/HANDOFF_NEXT_SESSION.md` (dokumen ini)

---

## 7. Cara memulai besok (copy-paste)

```
Lanjutkan NEXORA Economic Opportunity Discovery. Baca
reports/economic_opportunity_discovery/HANDOFF_NEXT_SESSION.md dulu.
STAGE 0-7 + Walk-Forward Validation SEMUA selesai (481 tes lulus). Final verdict STAGE 7 =
READY_WITH_CONDITIONS, TETAPI walk-forward (STAGE 7b) menunjukkan kondisi TIDAK terpenuhi:
0/20 fitur stabil robust, kandidat XAUUSD D1 GAGAL, survivor EURUSD rng_60 rapuh -> rekomendasi
TUTUP JALUR. Langkah berikutnya butuh KEPUTUSAN USER terpisah (data baru / hipotesis baru).
JANGAN mulai STAGE 8 / training otomatis. Lihat bagian 3g + 3h.
Gunakan .venv + set PYTHONPATH=".".
```
