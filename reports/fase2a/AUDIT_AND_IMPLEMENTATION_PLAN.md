# FASE 2A — LAPORAN AUDIT & IMPLEMENTATION PLAN
## Meta-Labeling & Triple-Barrier Research — EURUSD M30

**Status dokumen:** AUDIT + RENCANA (belum ada training/eksperimen dijalankan)
**Tanggal:** 2026-11-08
**Prinsip:** tidak menghapus/mengubah hasil Fase 2; tidak mengarang hasil; tidak
menyatakan edge sebelum terbukti net-of-cost.

---

## 0. RINGKASAN EKSEKUTIF AUDIT

| Temuan | Dampak |
|---|---|
| **Kronos adalah model eksternal** (foundation model K-line, open-source, HuggingFace `NeoQuasar/Kronos-small`), **bukan** modul di repo ini | Desain harus mengintegrasikan dependency berat baru (torch + tokenizer), bukan memakai apa yang sudah ada |
| **Tidak ada torch / transformers / huggingface_hub terpasang**; **bertambah** ~2–3 GB dependency | Perlu keputusan instalasi & anggaran komputasi |
| **Tidak ada GPU** (hanya Intel UHD 620, CPU-only) | Inferensi Kronos-small (24.7M params, context 512) di CPU = **lambat**; ~70k bar → perlu strategi (rolling inference / subsampling / batched) |
| **Tidak ada** triple-barrier, meta-labeling, cost-engine | Semua harus dibangun baru |
| **Sudah ada** pipa anti-leakage: split kronologis + embargo + purged walk-forward (`pipeline.py`, `tests/test_purge_boundary.py`, `test_r3_*`) | Bisa dipakai ulang — *jangan bangun ulang* |
| **Sudah ada** evaluator trading cost-aware (`nexora_evaluator/trading.py`) | Bisa dipakai ulang, perlu extension untuk metrik lanjutan |
| **Dataset punya kolom `<SPREAD>`** tapi **median 0, mean 3.39 points** | Spread historis **tidak dapat dipercaya** sebagai biaya nyata → harus skenario biaya (asumsi eksplisit) |
| **Data M1 tersedia** (114 MB) | Dapat dipakai untuk menyelesaikan ambiguitas urutan intrabar pada triple-barrier |
| `nexora_execution`, `nexora_laboratory`, `nexora_riskguard`, `nexora_scheduler` = **kosong** | Modul Fase 2A sebaiknya ditempatkan di sini (sesuai niat asli struktur) |

**Kesimpulan audit:** Fase 2A **layak dilanjutkan**, tetapi dengan **redefinisi jujur**:
"Kronos-small" = model eksternal yang di-*vendor*/di-install, dijalankan CPU-only,
dan **harus** divalidasi ulang bahwa ia benar-benar menghasilkan sinyal di EURUSD M30
sebelum dibangun meta-layer di atasnya. Risiko terbesar: menghabiskan effort membangun
meta-labeling di atas *primary model* yang ternyata juga tidak punya edge (seperti Fase 2).

---

## 1. AUDIT STRUKTUR PROYEK

### 1.1 Modul nyata (terverifikasi)
```
nexora_audit       governance, authorization, freeze, readiness, experiment_config  (LENGKAP)
nexora_core        config loader                                             (LENGKAP)
nexora_datahub     loader (CSV→bars), audit                                  (LENGKAP)
nexora_evaluator   metrics, trading (cost-aware), t3_evaluation              (LENGKAP)
nexora_intelligence model.py (create_model: LGBM/HGB)                        (LENGKAP, 16 baris)
nexora_learning    pipeline (prepare/split/walk_forward), targets, train_all (LENGKAP)
nexora_state_db    schema v5, repos, migrations, bootstrap                   (LENGKAP)
nexora_vision      features.py (29 fitur)                                    (LENGKAP)
nexora_dashboard   Streamlit read-only                                       (LENGKAP)
nexora_execution   (kosong)
nexora_laboratory  (kosong)
nexora_riskguard   (kosong)
nexora_scheduler   (kosong)
```

### 1.2 Dependency map (Fase 2A)
| Komponen Fase 2A | Bergantung pada (sudah ada) | Baru |
|---|---|---|
| Data validation | `nexora_datahub.loader.load_bars` | checks: duplikat, gap, timestamp monotonic |
| Triple-barrier | `features` ATR, `loader` bars, **M1 bars** (intrabar) | `triple_barrier.py` |
| Primary model (Kronos) | — | **torch, Kronos code+weights**, tokenizer |
| Meta-labeling | `create_model` (LGBM/LogReg), `features` | `meta_labeling.py` |
| Cost engine | `spread` column (diragukan), contract spec (belum ada) | `cost_engine.py` + `config/instruments.json` |
| Walk-forward | `pipeline.split_indices`, `walk_forward_scores`, purge/embargo | adaptasi untuk overlapping triple-barrier |
| Evaluation | `evaluator/metrics.py`, `evaluator/trading.py` | bootstrap CI, significance, PR-AUC, calibration, regime breakdown |
| Persistence | `nexora_state_db` (repos, migrations) | tabel/atribut experiment baru (atau `experiments/` JSON) |

### 1.3 Dataset tersedia (terverifikasi)
- `data/raw/EURUSD/EURUSD_M30_202001020000_202611062130.csv` — **70.694 bar**, 2020-01-02 → 2026-11-06. Kolom: open/high/low/close/volume/vol/spread.
- `data/raw/EURUSD/EURUSD_M1_...csv` — **114 MB**, granular (untuk intrabar).
- Semua timeframe M1..H12, D1, W1 tersedia.

### 1.4 Output / persistence yang ada
- `reports/t3/.../report.json`, `signals/t3/...csv`, `models/t3/...joblib` (produksi Fase 2 — **JANGAN diubah**).
- `experiments/` (hasil sweep A/B/C, JSON).
- `database/nexora_state.db` schema v5 + dashboard.

### 1.5 Konfigurasi Fase 2 (yang harus dibaca/dipertahankan)
- `config/research.json`: train_frac 0.6, val 0.2, embargo 24, max_iter 300, seed 42, horizons [1,2,4,8,12,24], walk_forward folds 3, initial 0.5.
- `nexora_audit/experiment_config.py`: kandidat A/B/C (max_depth/reg_alpha) — **tidak diubah**.
- `nexora_audit/configuration_freeze.py`: freeze manifest.

---

## 2. AUDIT GAP TERHADAP PERSYARATAN FASE 2A

| Persyaratan prompt | Status di repo | Gap / Rencana |
|---|---|---|
| Kronos-small primary model | ❌ tidak ada | **Keputusan kritis** — lihat §3 |
| Triple-barrier ATR | ❌ tidak ada | Build baru |
| Meta-labeling (L1→L2) | ❌ tidak ada | Build baru di atas pipeline |
| Cost engine (spread/komisi/slippage/swap/contract) | ⚠️ hanya spread column (diragukan) | Build + config contract |
| Anti-leakage (chronological, purged, embargo) | ✅ ada | Reuse + extend untuk overlapping events |
| Evaluasi ML (PR-AUC, Brier, calibration) | ⚠️ sebagian (metrics punya brier/auc; PR-AUC/calibration belum) | Extend `evaluator` |
| Evaluasi trading + CI/bootstrap/significance | ⚠️ basic trading ada; CI/bootstrap belum | Extend |
| Regime breakdown | ❌ tidak ada | Build (ATR/vol regime) |
| Reproducibility (seed+config JSON) | ✅ pola sudah ada | Terapkan |
| Modul terpisah (data_validation, triple_barrier, ...) | ❌ belum | Buat di `nexora_laboratory/` |

---

## 3. TEMUAN KRITIS & KEPUTUSAN YANG DIBUTUHKAN (SEBELUM CODING)

Ini adalah **keputusan yang memblokir**—tidak boleh dilewati.

### 3.1 Kronos adalah dependency eksternal + CPU-only
- Kronos-small = 24.7M params, context 512, butuh `torch` + kode tokenizer + bobot HuggingFace (`NeoQuasar/Kronos-small`).
- Environment: **CPU-only** (Intel UHD 620). Inferensi autoregresif 70k bar akan **sangat lambat** di CPU.
- **Opsi (mohon pilih):**
  - **A. CPU, subsample + rolling inference** (lookback 512, stride mis. 24/48 bar) — realistis, lebih sedikit prediksi. Ini yang saya rekomendasikan untuk memulai.
  - **B. GPU cloud** (Colab/Kaggle) untuk inferensi Kronos, simpan prediksi ke CSV, lanjutkan meta-labeling lokal — lebih akurat, tapi butuh langkah manual/eksternal.
  - **C. Tidak pakai Kronos** — pakai LGBM existing sebagai "primary model" (bukan Kronos). **Ini mengubah premis prompt** — hanya jika Anda setuju.

### 3.2 Spread historis tidak dapat dipercaya sebagai biaya
- Kolom `spread` M30: **median 0**, mean 3.39 points, max 300. Banyak 0 → bukan bid/ask nyata.
- Tidak ada config broker (pip value, komisi, swap, contract size, min lot, stop level).
- **Rencana:** cost engine memakai **skenario biaya eksplisit** (mis. 1.0 / 1.5 / 2.0 pip round-trip + slippage), ditandai **ASUMSI**, bukan diklaim sebagai spread historis. Data `spread` hanya dipakai sebagai *proxy relatif* (sudah dipakai di fitur `spread_relative`). **Mohon konfirmasi skenario biaya yang disetujui.**

### 3.3 Risiko utama: primary model mungkin tidak punya edge
- Fase 2 membuktikan model LGBM/LR tidak punya edge di EURUSD M30 (ceiling AUC ~0.53).
- **Risiko Fase 2A:** membangun meta-labeling di atas Kronos yang **juga** tidak punya edge → hasil NO-GO lagi.
- **Mitigasi wajib:** **Gate 0** — sebelum meta-labeling, ukur dulu *standalone* apakah **forecast Kronos** punya edge directional/cost-aware. Jika tidak, hentikan lebih awal (hemat effort), laporkan sebagai temuan.

### 3.4 Definisi "meta-label" harus ekonomis, bukan hanya arah
- Meta-label = 1 jika sinyal primary menghasilkan **net profit > 0** setelah biaya & barrier, terlepas dari benar/salah arah.
- Ini menuntut **triple-barrier net-of-cost** sebagai ground truth label, bukan `sign(return)`.

---

## 4. IMPLEMENTATION PLAN (RENCANA — BELUM DIJALANKAN)

### Tahap 1 — Data Validation (read-only)
- **File baru:** `nexora_laboratory/data_validation.py`
- Cek: monotonic timestamp, duplikat, gap, OHLC sanity, spread quality, overlap M1↔M30.
- Output: `reports/fase2a/dataset_audit.md` + JSON.
- **Gate:** tidak ada gap kritis/duplikat → lanjut.

### Tahap 2 — Triple-Barrier Labeling
- **File baru:** `nexora_laboratory/triple_barrier.py`
- Barrier ATR dinamis: upper `k_up*ATR`, lower `k_dn*ATR`, vertical `V` bar.
- Menentukan label `{+1,-1,0}` (hit upper/lower/vertical), plus **net return** setelah biaya.
- Resolusi urutan intrabar: pakai **M1 bars** untuk cek mana yang kena lebih dulu; jika ambigu → tandai `ambiguous` (bukan dipaksakan).
- Anti-leakage: barrier dihitung hanya dari info ≤ t; ATR trailing.
- **Gate:** buktikan tidak ada look-ahead (unit test waktu label > waktu fitur).

### Tahap 3 — Primary Model Integration (Kronos)
- **Keputusan §3.1 wajib dulu.**
- **File baru:** `nexora_laboratory/kronos_predictor.py` (wrapper) — hanya jika opsi A/B.
- Keluaran fitur meta: forecast return, arah, dispersi (dari `sample_count`), confidence.
- **Gate 0:** evaluasi standalone Kronos (AUC + cost-aware). Jika edge ~0 → STOP, laporkan.

### Tahap 4 — Meta-Labeling
- **File baru:** `nexora_laboratory/meta_labeling.py`
- Fitur: forecast dir/return/dispersion + ATR/vol/spread/candle/momentum/regime/session/cost.
- Model: **B=Logistic Regression, C=Gradient Boosting**, **D** hanya jika ada justifikasi statistik.
- Fit hanya pada training fold; kalibrasi probabilitas (Platt/isotonic pada validation).

### Tahap 5 — Cost Engine
- **File baru:** `nexora_laboratory/cost_engine.py` + `config/instruments.json`
- Biaya skenario eksplisit (ASUMSI), Net = Gross − cost. Konsisten satuan pip/points.

### Tahap 6 — Walk-Forward & Anti-Leakage
- **File baru:** `nexora_laboratory/walk_forward.py` (atau extend `pipeline`)
- Purged walk-forward + embargo ≥ vertical barrier; pastikan event windows tidak overlap lintas split.

### Tahap 7 — Experiment Runner (A/B/C/D)
- **File baru:** `nexora_laboratory/experiment_runner.py`
- Reproducible: seed + config JSON dicatat. Test set tidak dipakai tuning.

### Tahap 8 — Evaluation & Reporting
- **File baru:** `nexora_laboratory/evaluation.py`, `reporting.py`
- ML: precision/recall/F1/ROC-AUC/PR-AUC/Brier/calibration/confusion.
- Trading: net profit, PF, win rate, expectancy, maxDD, Sharpe, Sortino, n_trades, holding time, cost/trade, gross vs net.
- **Bootstrap CI + significance**; cost sensitivity; per-regime.
- Output: `reports/fase2a/` (report md + CSV + config JSON + logs).

### Penempatan & kompatibilitas
- Modul baru di `nexora_laboratory/` (folder kosong, sesuai niat arsitektur).
- Reuse: `loader`, `features`, `pipeline.split/walk_forward`, `evaluator.trading/metrics`, `state_db`.
- **Tidak mengubah** `models/t3/`, `signals/t3/`, `reports/t3/`, `pipeline.py`, `model.py`, `experiment_config.py`.

---

## 5. EXPERIMENT DESIGN (RINGKAS — untuk persetujuan)

| Eksp | Primary | Meta-layer | Catatan |
|---|---|---|---|
| Baseline Fase 2 | LGBM (frozen) | — | pembanding resmi (tak diubah) |
| A | Kronos | — | Kronos saja (Gate 0) |
| B | Kronos | Logistic Regression | |
| C | Kronos | Gradient Boosting (LGBM) | |
| D | Kronos | (opsional, berjustifikasi) | hanya bila B/C menunjukkan arah jelas |

Split, biaya, aturan eksekusi **identik** di semua eksperimen. Test out-of-sample tidak disentuh sampai evaluasi akhir.

---

## 6. GO/NO-GO CRITERIA FASE 2A (diusulkan)

GO **hanya jika** semua terpenuhi:
1. **Gate 0 lolos**: Kronos standalone punya edge directional (di atas baseline) — jika tidak, Fase 2A = NO-GO lebih awal.
2. Meta-labeling **meningkatkan net-of-cost** secara konsisten vs primary saja **dan** vs baseline Fase 2.
3. Konsisten di **≥3 walk-forward folds**.
4. Jumlah trade memadai (bukan hasil dari sedikit trade).
5. Tidak ada leakage (dibuktikan test).
6. Tidak bergantung pada satu periode/regime.
7. Signifikansi statistik (bootstrap CI tidak melewati nol).
8. Drawdown & risiko dapat diterima.

Jika gagal → **NO-GO** dengan diagnosis (seperti Fase 2). Tidak memaksakan hasil.

---

## 7. RISIKO & ASUMSI

| Risiko | Mitigasi |
|---|---|
| CPU-only membuat Kronos lambat | subsample/rolling inference, atau GPU cloud |
| Kronos tidak edge di M30 | Gate 0 menghentikan lebih awal; laporkan jujur |
| Spread historis tidak valid | skenario biaya eksplisit, ditandai asumsi |
| Overlapping triple-barrier bocor | purged walk-forward + embargo ≥ vertical barrier + M1 intrabar |
| Dataset hanya satu simbol | kesimpulan dibatasi EURUSD M30 (seperti Fase 2) |
| "Kronos-small" ambigu (eksternal vs internal) | diklarifikasi §3.1; mohon konfirmasi |

---

## 8. YANG DIMINTA UNTUK PERSETUJUAN ANDA

1. **Konfirmasi Kronos eksternal** (HuggingFace `NeoQuasar/Kronos-small`) & pilih opsi **§3.1 A / B / C**.
2. **Setujui skenario biaya** (mis. 1.0/1.5/2.0 pip round-trip + slippage) — §3.2.
3. **Setujui Gate 0** (uji Kronos standalone dulu sebelum meta-labeling) — §3.3.
4. Konfirmasi penempatan modul di `nexora_laboratory/` & kebijakan "jangan sentuh artefak Fase 2".

Setelah persetujuan, saya mulai **Tahap 1 (Data Validation)** — belum training.

---

*Laporan ini adalah AUDIT + RENCANA. Tidak ada training, model, atau hasil eksperimen
yang dijalankan/dibuat. Tidak ada artefak Fase 2 yang diubah.*
