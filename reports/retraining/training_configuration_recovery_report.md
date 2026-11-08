# NEXORA AI v2 — Training Configuration Recovery Report

Tanggal audit: 2026-11-07  
Mode: static/read-only audit. Tidak ada training, train_one(), runner --execute, atau perubahan database/CSV/config/dataset/model/backup.

## Kesimpulan

**BLOCKED untuk training PREP-001 yang dapat direproduksi.**

Konfigurasi aktif di config/research.json menyatakan max_iter=300 dan runner memeriksa nilai tersebut. Ini membuktikan nilai yang direncanakan oleh kode saat ini, tetapi bukan konfigurasi historis eksekusi PREP-001. batch_execution_log.csv memiliki 37 placeholder; training_config, start_time, dan end_time kosong pada semua baris. Tidak ditemukan artefak individual EURUSD/M30/H2 yang dapat membuktikan run historis.

Konfigurasi umum dapat direkonstruksi dari source, namun pilihan engine masih auto, beberapa parameter memakai default library yang tidak dipin, dan tidak ada config snapshot per run. Untuk menjamin reproduksibilitas, perlu freeze konfigurasi lengkap sebelum runner integration.

## 1. Sumber dan bukti

| Sumber | Temuan | Lokasi bukti |
|---|---|---|
| Config aktif | max_iter 300; seed 42; horizons [1,2,4,8,12,24]; train 0.6; validation 0.2; embargo 24; min_bars 5000; walk-forward folds 3 | config/research.json:12–34 |
| Config loader | Path ditentukan dari module root proyek | nexora_core/config.py:3–5 |
| Runner config | engine auto; max_iter/seed/fractions/embargo diambil dari config; default values juga disediakan bila key hilang | batch1_execution_runner.py:167–178 |
| Runner gate | Full training ditolak jika max_iter bukan 300 | batch1_execution_runner.py:636–637 |
| Pipeline | Label horizon, split, walk-forward, fit dan output | nexora_learning/pipeline.py:11–75 |
| Features | Feature engineering aktual dibangun oleh kode; tidak ada feature-set version string per job | nexora_vision/features.py:3–33 |
| Model factory | LightGBM atau fallback sklearn dipilih dengan engine=auto | nexora_intelligence/model.py:1–12 |
| Dataset loader | Timestamp parse, sorting, duplicate removal; volume default 0 bila kolom tidak ada | nexora_datahub/loader.py:35–44 |
| Dependency | requirements.txt menyatakan lightgbm>=4.0, bukan versi exact | requirements.txt:1–7 |
| Log legacy | 37 baris; training_config kosong 37/37; start/end kosong 37/37 | reports/retraining/batch_execution_log.csv |
| Git history | Direktori .git tidak tersedia di D:\NEXORA_AI_v2; tidak dapat memulihkan commit history | filesystem check |
| Target output PREP-001 | model/report/signals/metadata di path output yang diharapkan tidak ada | models/reports/signals/retraining paths |

Laporan lama pre_execution_validation.md dan batch1_runner_usage.md menyatakan max_iter 300 sebagai konfigurasi full-training yang diharapkan. Ini mendukung nilai target konfigurasi, bukan bukti bahwa PREP-001 pernah dilatih.

Artefak reports/retraining/simulations/batch1_checkpoint_v2 menyebut PREP-001 dan max_iter=1200/dummy_engine/sim-v1, tetapi simulation_result.json menyatakan baris itu disimulasikan. Nilai tersebut bukan konfigurasi historis aktual dan tidak digunakan sebagai sumber training. Tidak ada konflik antara dua run aktual yang terbukti; ada perbedaan antara dokumentasi konfigurasi full-train 300 dan metadata dummy simulasi 1200.

## 2. Matriks konfigurasi 37 job

Legacy tidak menyimpan job_key. Key pada tabel adalah key deterministik yang sudah diberikan pada simulasi SQLite v3 dari tuple scope/symbol/timeframe/horizon; bukan ID legacy historis. Semua baris berstatus legacy MISSING / TRAIN / PENDING dan berbagi profil source saat ini, tetapi tidak memiliki config snapshot per run.

| job_key di clone | Symbol | TF | Horizon | Legacy ref | Konfigurasi historis per-run |
|---|---|---|---:|---|---|
| legacy-plan-v3\|individual\|EURUSD\|M30\|H2 | EURUSD | M30 | 2 | PREP-001 | MISSING |
| legacy-plan-v3\|individual\|EURUSD\|M30\|H4 | EURUSD | M30 | 4 | PREP-002 | MISSING |
| legacy-plan-v3\|individual\|EURUSD\|M30\|H8 | EURUSD | M30 | 8 | PREP-003 | MISSING |
| legacy-plan-v3\|individual\|EURUSD\|M30\|H12 | EURUSD | M30 | 12 | PREP-004 | MISSING |
| legacy-plan-v3\|individual\|EURUSD\|M30\|H24 | EURUSD | M30 | 24 | PREP-005 | MISSING |
| legacy-plan-v3\|individual\|EURUSD\|M20\|H2 | EURUSD | M20 | 2 | PREP-006 | MISSING |
| legacy-plan-v3\|individual\|EURUSD\|M20\|H4 | EURUSD | M20 | 4 | PREP-007 | MISSING |
| legacy-plan-v3\|individual\|EURUSD\|M20\|H8 | EURUSD | M20 | 8 | PREP-008 | MISSING |
| legacy-plan-v3\|individual\|EURUSD\|M20\|H12 | EURUSD | M20 | 12 | PREP-009 | MISSING |
| legacy-plan-v3\|individual\|EURUSD\|M20\|H24 | EURUSD | M20 | 24 | PREP-010 | MISSING |
| legacy-plan-v3\|individual\|EURUSD\|M15\|H12 | EURUSD | M15 | 12 | PREP-011 | MISSING |
| legacy-plan-v3\|individual\|EURUSD\|M15\|H24 | EURUSD | M15 | 24 | PREP-012 | MISSING |
| legacy-plan-v3\|individual\|EURUSD\|M6\|H2 | EURUSD | M6 | 2 | PREP-013 | MISSING |
| legacy-plan-v3\|individual\|EURUSD\|M6\|H4 | EURUSD | M6 | 4 | PREP-014 | MISSING |
| legacy-plan-v3\|individual\|EURUSD\|M6\|H8 | EURUSD | M6 | 8 | PREP-015 | MISSING |
| legacy-plan-v3\|individual\|EURUSD\|M6\|H12 | EURUSD | M6 | 12 | PREP-016 | MISSING |
| legacy-plan-v3\|individual\|EURUSD\|M6\|H24 | EURUSD | M6 | 24 | PREP-017 | MISSING |
| legacy-plan-v3\|individual\|EURUSD\|M5\|H2 | EURUSD | M5 | 2 | PREP-018 | MISSING |
| legacy-plan-v3\|individual\|EURUSD\|M5\|H4 | EURUSD | M5 | 4 | PREP-019 | MISSING |
| legacy-plan-v3\|individual\|EURUSD\|M5\|H8 | EURUSD | M5 | 8 | PREP-020 | MISSING |
| legacy-plan-v3\|individual\|EURUSD\|M5\|H12 | EURUSD | M5 | 12 | PREP-021 | MISSING |
| legacy-plan-v3\|individual\|EURUSD\|M5\|H24 | EURUSD | M5 | 24 | PREP-022 | MISSING |
| legacy-plan-v3\|individual\|EURUSD\|M4\|H2 | EURUSD | M4 | 2 | PREP-023 | MISSING |
| legacy-plan-v3\|individual\|EURUSD\|M4\|H4 | EURUSD | M4 | 4 | PREP-024 | MISSING |
| legacy-plan-v3\|individual\|EURUSD\|M4\|H8 | EURUSD | M4 | 8 | PREP-025 | MISSING |
| legacy-plan-v3\|individual\|EURUSD\|M4\|H12 | EURUSD | M4 | 12 | PREP-026 | MISSING |
| legacy-plan-v3\|individual\|EURUSD\|M4\|H24 | EURUSD | M4 | 24 | PREP-027 | MISSING |
| legacy-plan-v3\|individual\|EURUSD\|M3\|H2 | EURUSD | M3 | 2 | PREP-028 | MISSING |
| legacy-plan-v3\|individual\|EURUSD\|M3\|H4 | EURUSD | M3 | 4 | PREP-029 | MISSING |
| legacy-plan-v3\|individual\|EURUSD\|M3\|H8 | EURUSD | M3 | 8 | PREP-030 | MISSING |
| legacy-plan-v3\|individual\|EURUSD\|M3\|H12 | EURUSD | M3 | 12 | PREP-031 | MISSING |
| legacy-plan-v3\|individual\|EURUSD\|M3\|H24 | EURUSD | M3 | 24 | PREP-032 | MISSING |
| legacy-plan-v3\|individual\|EURUSD\|M2\|H2 | EURUSD | M2 | 2 | PREP-033 | MISSING |
| legacy-plan-v3\|individual\|EURUSD\|M2\|H4 | EURUSD | M2 | 4 | PREP-034 | MISSING |
| legacy-plan-v3\|individual\|EURUSD\|M2\|H8 | EURUSD | M2 | 8 | PREP-035 | MISSING |
| legacy-plan-v3\|individual\|EURUSD\|M2\|H12 | EURUSD | M2 | 12 | PREP-036 | MISSING |
| legacy-plan-v3\|individual\|EURUSD\|M2\|H24 | EURUSD | M2 | 24 | PREP-037 | MISSING |

Konfigurasi umum yang berlaku dari source bukan bukti bahwa setiap job pernah dieksekusi dengan nilai tersebut.

## 3. Parameter recovery matrix

Status menilai bukti yang tersedia pada source saat ini. “Historical run” dibedakan dari konfigurasi yang akan digunakan oleh source saat ini.

| Parameter | Nilai yang ditemukan | Status | Sumber dan keyakinan |
|---|---|---|---|
| Job key | Tidak ada di CSV; clone memakai legacy-plan-v3|scope|symbol|TF|Horizon | PARTIAL | Simulasi schema v3; key clone deterministik, bukan ID historis; tinggi |
| Symbol/timeframe/horizon | EURUSD, tuple plan masing-masing | FOUND | batch_retraining_plan.csv dan batch_execution_log.csv; tinggi |
| max_iter | 300 | FOUND untuk konfigurasi source; MISSING untuk eksekusi historis | research.json:23; runner guard :636–637; log tidak berisi config; tinggi untuk nilai target |
| Feature set | 29 fitur hasil build_features() | PARTIAL | features.py:3–33; implementation ditemukan, tetapi tidak ada version/hash feature set per run; tinggi |
| Target/label | y[t]=1 bila close[t+h]/close[t]-1 > 0; selain itu 0; tail horizon dimask | FOUND | pipeline.py:16–20; tinggi |
| LightGBM objective | Tidak di-set pada pemanggilan; LightGBM 4.7.0 yang terpasang menginfer binary untuk LGBMClassifier | PARTIAL | model.py:5–7; site-packages/lightgbm/sklearn.py:930–945; requirements hanya >=4.0; tinggi untuk runtime saat ini, rendah untuk historis |
| Learning rate | 0.03 | FOUND pada kedua engine path | model.py:5,11; tinggi |
| Num leaves | LightGBM 15; sklearn fallback max_leaf_nodes 15 | FOUND | model.py:5,11; tinggi |
| Max depth | Tidak diberikan; LightGBM default -1 pada runtime 4.7.0; sklearn fallback tidak menerima max_depth di constructor ini | PARTIAL | model.py:5–12 dan LightGBM sklearn.py:1570+; nilai historis tidak dipin |
| Feature fraction | LightGBM colsample_bytree=0.8; tidak ada padanan yang sama pada sklearn fallback | PARTIAL | model.py:6; bergantung engine |
| Bagging fraction/frequency | LightGBM subsample=0.8 dan subsample_freq=1; fallback berbeda | PARTIAL | model.py:6; bergantung engine |
| Min child samples | LightGBM min_child_samples=100; fallback min_samples_leaf=100 | FOUND pada jalur terpilih | model.py:6,12; tinggi |
| Regularisasi | LightGBM reg_lambda=5; HistGradientBoosting l2_regularization=5. L1 LightGBM tidak di-set eksplisit (default runtime 0) | PARTIAL | model.py:6,12 dan library default; tidak dibekukan per run |
| Seed | 42 | FOUND untuk source saat ini | research.json:24; runner.py:173; model.py:1,7,12; tinggi |
| Training/validation/test window | 0.6 train, 0.2 validation, sisanya test; embargo=max(horizon,24) eligible rows | FOUND pada implementation | research.json:20–22; pipeline.py:22–29,54; tinggi |
| Walk-forward | 3 folds; implementation memulai sekitar 50% data dan memberi purge horizon | PARTIAL | research.json:27–30; pipeline.py:32–47; min_train_fraction dari JSON tidak dibaca oleh pipeline individual |
| Preprocessing | Sort timestamp, hapus timestamp duplikat, parse numerik, volume hilang diisi 0; fitur rolling/ATR | FOUND pada implementation | loader.py:35–44; features.py:3–33; high confidence |
| Early stopping | HistGradientBoosting eksplisit false; LightGBM tidak diberi eval_set/callback early stopping | PARTIAL | model.py:5–12; pipeline.py:57; tidak ada setting per-run |
| Engine | auto; LightGBM 4.7.0 tersedia di venv, tetapi dependency tidak dipin tepat | PARTIAL | runner.py:174; requirements.txt; pip show; fallback sklearn dapat mengubah semantik |
| Model output | joblib ke models/individual/<symbol>/<tf>/h<h>/model.joblib; report.json dan individual_signals.csv; runner staging metadata/manifest | FOUND untuk path implementation | pipeline.py:64–75; runner.py:185–191, write_staging_metadata; bukan artefak PREP-001 yang ada |
| Frozen effective config per job | Tidak ada; training_config kosong di 37 log rows | MISSING | batch_execution_log.csv; tinggi |

Feature set implementation (29 kolom): ret_1/2/4/8/16/32/64; atr_pct; range_atr; body_atr; upper_wick; lower_wick; rsi14; dist_sma20/50/100/200; ema_slope20/50/100/200; vol20; vol_ratio; volume_z; hour_sin/cos; dow_sin/cos; spread_relative.

## 4. PREP-001 deep audit

Tuple: EURUSD / M30 / horizon 2; plan order pertama; reference PREP-001.

Dataset:
- Path: data/raw/EURUSD/EURUSD_M30_202001020000_202611062130.csv
- SHA-256 dihitung ulang: e6729c4596f872f503cc04c7611375419395ab9cc92f9d918121609cdb282945
- Clone dataset record dan hash cocok; 70,694 rows; rentang 2020-01-02 00:00:00 sampai 2026-11-06 21:30:00.
- Manifest: interval PASS, schema valid, zero invalid/duplicate timestamps dan OHLC issues; gap_count 3660 perlu dibaca sesuai kalender/sesi.

Konfigurasi:
- Horizon 2 ada di config horizon list; max_iter=300 adalah konfigurasi yang ditetapkan source dan dipaksa oleh runner.
- Log PREP-001 berstatus PENDING/QUEUED; start/end dan training_config kosong.
- Seed/window tersedia pada config source; engine/objective/max_depth tidak dibekukan pada per-job record.
- Tidak ada model, report, signals, atau PREP-001 metadata pada output path yang diharapkan.
- Hasil test/simulation PREP-001 dengan dummy_engine bukan training historis.

Leakage/timing:
- Kode membuat label dari close masa depan horizon h; fitur dibangun dari OHLC/time/volume/spread saat ini dan rolling window satu arah. Tidak terlihat penggunaan fwd/y sebagai feature.
- Split source bersifat kronologis dan memberi embargo 24 eligible rows untuk PREP-001 (lebih besar dari horizon 2).
- Namun tidak ada test yang membuktikan purge boundary atas timestamp dataset, tidak ada kontrak kapan sinyal boleh dieksekusi relatif terhadap bar M30 close, dan laporan pipeline menyatakan evaluasi bukan cost-aware backtest. Karena itu “tidak ada direct target feature leakage pada kode yang diperiksa” dapat dinyatakan, tetapi “leakage/timing telah terbukti tidak ada” tidak dapat diklaim.

**Keputusan PREP-001: BLOCKED.** Nilai max_iter target terverifikasi sebagai config source, namun histori run tidak ada; engine/defaults dan versi belum dipin, output tidak ada, serta timing/evaluasi belum disetujui.

## 5. Rekomendasi recovery config

1. Sebelum queue, bekukan effective config per job ke config_json dengan config hash dan identitas versi code/dependencies; jangan hanya menyimpan pointer ke research.json.
2. Tetapkan engine eksplisit, objective eksplisit, max_depth, regularisasi lengkap, early-stopping policy, serta dependency lock.
3. Simpan feature-set version/hash dan target/split policy version.
4. Tetapkan keputusan waktu prediksi/eksekusi (bar close atau next bar) dan audit leakage/purge boundaries.
5. Jangan menyalin dummy simulation config menjadi konfigurasi historis.
