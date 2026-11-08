# NEXORA AI v2 — Partial Migration Simulation v2

Tanggal: 2026-11-07. Audit read-only.

## Kesimpulan: PARTIALLY_READY

37 job individual telah dicocokkan dengan dataset. Simulasi belum aman karena schema operasional tidak menyediakan PLANNED, sementara QUEUED tidak boleh ditetapkan tanpa bukti antrean. Tidak ada INSERT, clone, migrasi, training, atau perubahan data. Sepuluh job global tidak dimigrasikan.

## 1. Schema lifecycle review

Database D:\NEXORA_AI_v2\database\nexora_state.db diperiksa read-only/query-only. Schema version 2; integrity_check=ok; foreign_key_check kosong; 11 tabel dan 18 indeks.

| Tabel | Status schema | Aturan |
|---|---|---|
| training_jobs | QUEUED, RUNNING, STARTED, TRAIN_DONE, VALIDATED, PROMOTED, FAILED, RETRY_PENDING | scope individual/global; job_key UNIQUE; unique tuple (scope, ifnull(symbol,''), timeframe, horizon) |
| training_runs | QUEUED, STARTED, TRAIN_DONE, VALIDATED, PROMOTED, FAILED, RETRY_PENDING | job_id FK ke training_jobs ON DELETE CASCADE; UNIQUE(job_id,run_index); run_uid UNIQUE |
| checkpoints | QUEUED, STARTED, TRAIN_DONE, VALIDATED, PROMOTED, FAILED, RETRY_PENDING | FK ke run |
| training_job_datasets | tanpa lifecycle | PK(job_id,dataset_id), FK job cascade, FK dataset restrict |

nexora_state_db/constants.py menetapkan QUEUED→STARTED/FAILED; STARTED→TRAIN_DONE/FAILED; TRAIN_DONE→VALIDATED/FAILED; VALIDATED→PROMOTED/FAILED; FAILED→RETRY_PENDING; RETRY_PENDING→STARTED; PROMOTED terminal. Run lifecycle terpisah dari job; claim menjalankan run STARTED dan job RUNNING.

Schema tidak menyediakan PLANNED atau tabel plan-only. config_json hanya metadata dan tidak menghilangkan status wajib. Status default QUEUED menyiratkan antrean tanpa bukti.

## 2. Status representation

| Legacy | Makna | Representasi aman |
|---|---|---|
| MISSING | Kekurangan coverage model/artifact, bukan status eksekusi | Legacy coverage metadata |
| TRAIN | Aksi rencana, bukan status job/run | Legacy plan-action metadata |
| PREP-* | Placeholder; tidak ada bukti waktu/config/artifact aktual | Legacy reference saja |
| PENDING | Proyeksi QUEUED di jalur runner; PREP pada log tidak membuktikan antrean | Legacy raw metadata, bukan QUEUED |

Ditelusuri: batch_checkpoint_manager.py, batch1_execution_runner.py, nexora_state_db/constants.py, laporan coverage dan plan/log legacy. Tidak dibuat run/checkpoint.

## 3–4. Verifikasi 37 individual jobs dan dataset

Sumber plan: reports/retraining/batch_retraining_plan.csv. Semua 37 baris individual adalah EURUSD. Horizon M15: 12,24; timeframe lain: 2,4,8,12,24. Semua baris bertanda dataset_usable=True, BASIC_CHECKS_PASS, MISSING, TRAIN.

| TF | Jobs | Rows plan/manifest | Path relatif | SHA-256 |
|---|---:|---:|---|---|
| M15 | 2 | 137995 | data/raw/EURUSD/EURUSD_M15_202001020000_202611062145.csv | 7b72f6cd9ab14ffd8d8479e4647fb2688a4c228aa80ce8edcd3a8fe5c7399f7f |
| M2 | 5 | 1008234 | data/raw/EURUSD/EURUSD_M2_202001020000_202611062158.csv | 13859e31793517bdada9b9697a06ddbdc95e6d9b9f262672151738e1c1fc86c6 |
| M20 | 5 | 104345 | data/raw/EURUSD/EURUSD_M20_202001020000_202611062140.csv | 53c814ffc2606ee9beb39f1670bca1aa102401431b4022a4d4a80cf0adc88773 |
| M3 | 5 | 674812 | data/raw/EURUSD/EURUSD_M3_202001020000_202611062157.csv | d8f8d47e9c6f7eea5911a91c6cdbcd419aede035a6af3864e00d9151248d8659 |
| M30 | 5 | 70694 | data/raw/EURUSD/EURUSD_M30_202001020000_202611062130.csv | e6729c4596f872f503cc04c7611375419395ab9cc92f9d918121609cdb282945 |
| M4 | 5 | 507344 | data/raw/EURUSD/EURUSD_M4_202001020000_202611062156.csv | ad62a76d54b48a9f65e88919af0e11766cd0b330d0eed7b1f227a860e9ec7ee4 |
| M5 | 5 | 406686 | data/raw/EURUSD/EURUSD_M5_202001020000_202611062155.csv | 394968386845468ada2374374f92d9563836163e1465d60257d91ca4a7fc9fd5 |
| M6 | 5 | 339724 | data/raw/EURUSD/EURUSD_M6_202001020000_202611062154.csv | aef53eb85629740fbd506a0cea5aeeb39c109ed0ff407da73b895b97630f2f36 |

Hash SHA-256 dihitung ulang dari setiap file; dataset_rows plan cocok dengan rows_valid_unique manifest untuk semua delapan timeframe. Manifest: schema valid, interval PASS, nol duplicate/invalid timestamp, OHLC kosong, harga nonpositive, dan OHLC invalid. Rentang mulai 2020-01-02 dan akhir sesuai filename/manifest. Gap dicatat, sehingga kelengkapan histori tidak disimpulkan. Dataset IDs tidak direka.

## 5. Global dataset_rows (10 job dikecualikan)

| TF | EURUSD rows | XAUUSD rows | plan scalar | pooled sum |
|---|---:|---:|---:|---:|
| M1 | 1997692 | 1889105 | 1889105 | 3886797 |
| M3 | 674812 | 631040 | 631040 | 1305852 |

Scalar plan sama dengan komponen kedua/XAUUSD, bukan jumlah pooled. nexora_learning/global_train.py::train_global_group() membangun block fitur per dataset lalu menggabungkan dengan pd.concat sebelum sort timestamp. Generator asli untuk scalar dataset_rows tidak ditemukan; artinya UNRESOLVED. Tidak ada job global dimigrasikan.

## 6–8. Mapping, schema, simulasi

Fakta: 37 tuple individual unik dan setiap tuple cocok ke satu file timeframe EURUSD. PREP-* bukan bukti run aktual.

Proposal: buat tabel training_job_plans terpisah berstatus PLANNED, unique tuple, dan provenance legacy (status, action, PREP reference, source file/row/key, source snapshot/hash). Plan tidak membuat training_runs/checkpoints atau antrekan job. Alternatif menambah PLANNED hanya setelah seluruh runner/claim/transition dipastikan non-runnable dan schema direview.

Idempotency: gunakan unique tuple guard dan key deterministik dari tuple canonical (scope, symbol, timeframe, horizon) plus source identity. Replay metadata identik = no-op; konflik = hard error. Simulasi berikut harus memakai clone baru dan menguji replay. Audit ini tidak membuat clone atau record.

Schema yang diperlukan sebelum simulasi: representasi PLANNED non-runnable/plan-only, provenance legacy, definisi key idempotensi. Tidak ada simulasi mutasi atau tes dijalankan.

## Risiko dan unresolved

- Global scalar dataset_rows belum terdefinisi karena generator tidak tersedia.
- Manifest dasar dan gap tidak membuktikan histori lengkap.
- Relasi dataset ID harus diverifikasi di clone.
- Jangan petakan MISSING/TRAIN/PREP menjadi lifecycle eksekusi.
- Replay di clone belum dites.

SHA-256 database: E314244ED46099ABD0025E982640B9BE7711F608AC9A75FF5B44E4D43286D6C6.

Database produksi, CSV, dataset, model, backup tidak dimodifikasi; tidak ada training, import, migrasi, run/checkpoint palsu.