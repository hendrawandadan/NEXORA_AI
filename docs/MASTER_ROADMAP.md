# NEXORA AI — Master Development Roadmap

**Autonomous Global Trading Intelligence**

> Dokumen ini adalah acuan pengembangan proyek. Perubahan besar pada arah, prioritas,
> atau fase harus diratifikasi di sini lebih dulu agar pekerjaan tidak melebar tanpa
> kontrol. Fokus pada **satu fase aktif** pada satu waktu.

---

## 1. Visi

Membangun platform kecerdasan trading global yang mampu mempelajari berbagai
instrumen keuangan, memahami kondisi pasar, membaca informasi multimodal,
menemukan strategi secara mandiri, melakukan eksperimen, belajar dari kegagalan,
serta mendukung pengambilan keputusan dan eksekusi trading.

Level target: **Level 3 — Autonomous Research Intelligence.**
Artinya AI dapat melakukan penelitian dan eksperimen mandiri, **tetapi** perubahan
model produksi dan transaksi live tetap memerlukan kontrol keselamatan dan otorisasi.

---

## 2. Delapan Kecerdasan Inti

| # | Kecerdasan | Fokus |
|---|------------|-------|
| 01 | Data Intelligence | Kumpulkan, bersihkan, validasi, kelola data historis & real-time |
| 02 | Multimodal Intelligence | Baca screenshot chart, gambar, OCR, PDF, berita, teks |
| 03 | Market Understanding Intelligence | Market regime, antar-instrumen, makroekonomi, sentimen |
| 04 | Learning Intelligence | Pola, ingatan eksperimen, concept drift, peningkatan model |
| 05 | Strategy Intelligence | Temukan, kembangkan, kombinasikan, optimalkan strategi |
| 06 | Validation & Risk Intelligence | Uji, ukur risiko, deteksi kegagalan, pastikan robustness |
| 07 | Autonomous Research Intelligence | Hipotesis, eksperimen, belajar berkelanjutan |
| 08 | Execution Intelligence | Keputusan trading, posisi, portofolio, integrasi MT5 |

---

## 3. Sepuluh Fase Pengembangan

Status: `DONE` / `ACTIVE` / `PARTIAL` / `PLANNED`. Pemetaan modul mencerminkan
kondisi repo saat dokumen ini dibuat (modul skeleton hanya berisi `__init__.py`).

### Fase 1 — Foundation & Data Intelligence — `DONE`
- Database & migration (`nexora_state_db/`, migrations 001–005)
- Dataset management (`nexora_datahub/loader.py`, `discover_datasets`)
- Data validation & audit (`nexora_datahub/audit.py`)
- Training runner (`batch1_execution_runner.py`)
- Execution safety & authorization (`nexora_audit/`, `batch_checkpoint_manager.py`)
- Finalisasi konfigurasi & timing PREP-001 (`nexora_audit/configuration_freeze.py`, `timing_contract.py`)

### Fase 2 — First AI Learning — `ACTIVE`
- Training pertama PREP-001 (EURUSD M30, horizon 2) — **T3 PROMOTED (lightgbm)**
- Eksperimen konfigurasi A/B/C — `PARTIAL` (A terikat; B/C belum dijalankan)
- Evaluasi performa — **belum** (`nexora_evaluator/` siap dipakai)
- Penyimpanan model & experiment history (`experiments/`, masih kosong)
- Exit criteria terukur: lihat **§8**.

### Fase 3 — Multi-Instrument Intelligence — `PLANNED`
- Model individual per instrumen, parameter adaptif, multi-timeframe, multi-pair.
- Modul: `nexora_learning/` (sudah generik lintas symbol/timeframe).

### Fase 4 — Global Market Intelligence — `PLANNED`
- DXY, Treasury Yield, indeks global, komoditas, Economic Calendar, Central Bank,
  sentimen, intermarket correlation, multimodal. (`nexora_vision/` sudah ada: `features.py`)

### Fase 5 — Market Understanding & Memory — `PLANNED`
- Market regime detection, historical similarity, market memory, cross-market,
  concept drift.

### Fase 6 — Autonomous Strategy Laboratory — `PLANNED`
- Strategy discovery, Strategy DNA, genetic algorithms, optimization, AI debate,
  what-if. (`nexora_laboratory/` masih skeleton)

### Fase 7 — Learning & Failure Intelligence — `PLANNED`
- Belajar dari kegagalan, analisis drawdown, continuous learning, retraining,
  autonomous research scheduler. (`nexora_scheduler/` masih skeleton)

### Fase 8 — Advanced Validation & Risk — `PARTIAL` (tool dasar sudah ada)
- Walk-forward (`nexora_learning/pipeline.py: walk_forward_scores`), out-of-sample
  (`split_indices`), spread/komisi/slippage (`nexora_evaluator/trading.py`).
- Belum: Monte Carlo, stress testing, portfolio risk, explainable AI.

### Fase 9 — Trading Decision Engine & MT5 — `PLANNED`
- Signal generation, entry/SL/TP, position sizing, multi-pair, MT5
  (`nexora_execution/` masih skeleton; `nexora_evaluator/t3_evaluation.py` ada).

### Fase 10 — Autonomous Global Trading Intelligence — `PLANNED`
- Visi akhir: riset, eksperimen, evaluasi, adaptasi, pengelolaan mandiri dengan
  kontrol keselamatan.

---

## 4. Cakupan Pasar Global (target pengembangan)

| Kelompok | Instrumen target |
|----------|------------------|
| Major Forex | EURUSD, GBPUSD, USDJPY |
| Commodity Forex | AUDUSD, USDCAD, NZDUSD |
| Cross Forex | EURJPY, GBPJPY |
| Metals | XAUUSD, XAGUSD |
| Indices | US30, NAS100, SPX500 |
| Energy | USOIL, UKOIL |
| Crypto | BTCUSD, ETHUSD |
| Global Macro | DXY, Treasury Yield, suku bunga, inflasi |

Kesiapan dataset, kualitas data, dan kemampuan eksekusi **harus diperiksa
masing-masing** sebelum instrumen ditambahkan ke training.

---

## 5. Autonomous Research Cycle

`OBSERVE → UNDERSTAND → HYPOTHESIZE → EXPERIMENT → EVALUATE → LEARN → IMPROVE`

Strategi yang berhasil dalam backtest **belum otomatis** dianggap profitable.
Setiap kandidat harus diuji pada data yang belum dipelajari, dengan biaya transaksi
realistis, dan forward testing.

---

## 6. Fitur Tambahan (dipetakan ke fase relevan, tidak dibuat sekaligus)

| Fitur | Tujuan | Fase relevan |
|-------|--------|--------------|
| Market Regime Intelligence | Mengenali kondisi pasar | 5 |
| Trading Failure Intelligence | Belajar dari kegagalan | 7 |
| Market Memory | Mengingat kondisi historis | 5 |
| Strategy DNA | Mengembangkan generasi strategi | 6 |
| Global Economic Brain | Memahami ekonomi dunia | 4 |
| AI Trading Council | Menggabungkan beberapa spesialis AI | 6 |
| What-if Simulation | Menguji berbagai skenario | 6 |
| Adaptive Risk Intelligence | Menyesuaikan pengendalian risiko | 8 |
| Explainable AI | Menjelaskan alasan keputusan | 8 |
| Autonomous Scheduler | Menjadwalkan penelitian otomatis | 7 |

---

## 7. Prinsip Keselamatan (WAJIB)

1. Semua model & strategi harus melewati validasi realistis.
2. Perubahan model produksi, promosi strategi, dan transaksi live **memerlukan**
   otorisasi, audit, dan risk management (lihat `nexora_audit/`).
3. Jangan gunakan data masa depan dalam training/evaluasi (purge & embargo:
   `nexora_learning/pipeline.py: purge_bars`, `split_indices`).
4. Jangan menganggap hasil backtest sebagai jaminan profit.
5. Setiap eksperimen harus reproducible (config hash + seed + rentang data + metrik).
6. Jangan biarkan AI mengubah model produksi tanpa persetujuan manusia.

---

## 8. Fase 2 — Exit Criteria (definisi "SELESAI" yang terukur)

Fase 2 **belum** boleh ditutup sampai SEMUA kriteria berikut terpenuhi.

### 8.1 Evaluasi out-of-sample model T3 PREP-001 (wajib)
- [ ] Metrik klasifikasi pada **split out-of-sample/test** (bukan train):
  accuracy, AUC, precision/recall per kelas, dan confusion matrix.
  Gunakan `nexora_evaluator/metrics.py: metrics`.
- [ ] Bandingkan terhadap baseline naif (majority-class / always-up / random).
  Model harus **mengalahkan baseline**, bukan sekadar akurasi > 50%.
- [ ] Walk-forward validation (`nexora_learning/pipeline.py: walk_forward_scores`,
  folds sesuai `config/research.json` walk_forward.folds=3), laporkan mean & std.

### 8.2 Evaluasi trading realistis (wajib)
- [ ] Evaluasi sinyal dengan biaya transaksi realistis:
  `nexora_evaluator/trading.py: evaluate_signal_file(round_trip_cost_bps=...)`.
- [ ] Laporkan net return, hit rate, profit factor, dan **max drawdown** setelah biaya.
- [ ] Untuk T3 (execution-aligned): `nexora_evaluator/t3_evaluation.py:
  evaluate_t3_execution_gross`.

### 8.3 Eksperimen A/B/C (wajib sebelum melebar)
- [ ] Kandidat **B** dan **C** dijalankan dengan protokol & split identik.
- [ ] Ketiga kandidat diuji pada **split out-of-sample yang sama**.
- [ ] Perbandingan menghasilkan keputusan jelas: kandidat mana yang dipilih & mengapa.

### 8.4 Experiment history reproducible (wajib)
- [ ] Hasil tiap kandidat dicatat di `experiments/` dengan: config hash, seed,
  rentang data train/valid/test, target_type, metrik, dan path artifact.
- [ ] Dapat direproduksi ulang (deterministik dengan seed yang sama).

### 8.5 Governance & audit (wajib)
- [ ] `python -m nexora_audit all` (pakai `.venv`) → `decision: READY_FOR_TRAINING`,
  `blocking_gates: []`.
- [ ] Sign-off tervalidasi untuk kandidat & target yang benar (T1/T3 tidak tercampur).

### 8.6 Keputusan Go/No-Go (gate Fase 2 → Fase 3)
- [ ] **GO** hanya jika model T3 mengalahkan baseline secara konsisten pada
  out-of-sample **dan** tetap positif setelah biaya transaksi realistis.
- [ ] Jika **NO-GO**: dokumentasikan penyebab, revisi hipotesis/target/konfigurasi,
  ulangi Fase 2. **Jangan** memperluas ke Fase 3 dengan asumsi yang belum terbukti.

---

## 9. Aturan Utama Pengembangan

- Fokus pada **satu fase aktif**.
- Jangan menambah arsitektur yang belum diperlukan.
- Setiap eksperimen punya catatan & hasil yang bisa direproduksi.
- Jangan biarkan AI mengubah model produksi tanpa persetujuan.
- Jangan memakai data masa depan dalam training/evaluasi.
- Jangan menganggap backtest sebagai jaminan profit.
- Perluasan pair & Global Intelligence tetap tujuan utama — **tapi menunggu** fondasi
  Fase 2 terbukti.

---

## 10. Tujuan Akhir

NEXORA AI menjadi **Autonomous Global Trading Research & Intelligence Platform**,
bukan sekadar EA atau sistem prediksi harga. EURUSD PREP-001 adalah langkah pertama
untuk membuktikan fondasinya; multi-pair, Global Intelligence, Multimodal
Intelligence, dan Autonomous Research adalah arah besar proyek.

---

*Dokumen ini hidup (living document). Setiap perubahan fase/prioritas harus
diperbarui di sini lebih dulu, lalu diikuti implementasi bertahap sesuai kesiapan
data, model, dan infrastruktur.*
