# Legacy Semantic Mapping & Dataset Provenance Audit

Tanggal audit: 2026-11-07  
Kesimpulan: **PARTIALLY_READY**

## 1. Executive summary

Bukti kode menjelaskan tiga nilai legacy dengan tingkat kepastian berbeda: `MISSING` adalah status coverage model/artifact pada laporan/plan, `TRAIN` adalah tindakan yang direncanakan, dan `PENDING` adalah proyeksi `checkpoint_status=QUEUED` ke `run_status` dalam lifecycle runner. Dua nilai pertama bukan status SQLite. Pada 37 baris execution log, `PREP-*`, catatan “Pre-filled from batch_retraining_plan”, dan waktu mulai/selesai kosong menunjukkan placeholder persiapan, bukan bukti run aktual; karena itu tidak ada dasar membuat `training_runs` atau checkpoint historis.

Untuk 37 job individual, file sumber raw EURUSD ditemukan dan diverifikasi terhadap jumlah baris plan, audit manifest, rentang waktu, struktur OHLC, dan hash file. Untuk 10 job global M1/M3, kedua file komponen EURUSD dan XAUUSD ditemukan dan lolos pemeriksaan masing-masing. Namun nilai `dataset_rows` pada plan global sama dengan jumlah baris file komponen yang lebih kecil, bukan jumlah pooled dua sumber; semantik angka itu tidak terdokumentasi di kode planner yang tersedia. Runner batch saat ini juga mengindeks file berdasarkan satu `(symbol,timeframe)` dan menjalankan pipeline individual, sehingga simbol komposit global belum dapat dijalankan lewat jalur itu.

Tidak ada database, CSV, dataset, model, atau backup yang diubah. Tidak ada training/import yang dijalankan. Job Key tidak tersedia pada CSV dan tidak dibuatkan oleh audit ini.

## 2. Status semantic audit

| Legacy Status | Sumber kode/bukti | Makna sebenarnya | Entitas terkait | Kandidat status SQLite | Keyakinan |
|---|---|---|---|---|---|
| `MISSING` | Muncul pada `reports/audit/training_coverage_report.md`, `reports/retraining/batch_retraining_plan.md`, dan `current_status` CSV. Tidak ditemukan generator status `MISSING` di source Python yang tersedia. Plan mendefinisikan 47 “to-train” sebagai `MISSING + usable`, sementara laporan coverage memisahkan `TRAINED`, `MISSING`, `INCOMPLETE`, `INVALID`. | Coverage model/artifact untuk kombinasi symbol/timeframe/horizon belum memiliki model terlatih yang diakui audit. Ini bukan status job atau dataset. Kesimpulan semantik bersandar pada laporan, bukan kode pembuat coverage yang tidak tersedia. | Model/artifact coverage | Tidak ada status langsung. Pertahankan `legacy_current_status="MISSING"` sebagai provenance/metadata; jangan masukkan ke `training_jobs.status`. | Sedang |
| `TRAIN` | Kolom `plan_action` pada plan; dokumen planner menyebut baris tersebut sebagai urutan eksekusi yang direkomendasikan. Runner `parse_plan()` membaca baris plan, tetapi lifecycle aktual dijalankan dari `checkpoint_status`; tidak ada pemetaan `plan_action` menjadi status database. | Perintah/intensi perencanaan untuk melatih kandidat. Bukan bukti bahwa job sudah diantrekan atau dijalankan. | Rencana job | Bukan status SQLite. Pertahankan `legacy_plan_action="TRAIN"` sebagai metadata rencana. Status `QUEUED` hanya boleh diberikan menurut kebijakan antrean eksplisit. | Tinggi |
| `PENDING` | `batch_checkpoint_manager.py::status_to_run_status()` dan `batch1_execution_runner.py::run_status_from_checkpoint()` memetakan `QUEUED → PENDING`. `transition_status()` mengubah status run ketika checkpoint berubah. Baris CSV saat ini berisi `run_status=PENDING`, `checkpoint_status=QUEUED`. | Proyeksi status checkpoint queued ke field status run pada execution log legacy. Dalam lifecycle kode, ini berarti belum mulai; transisi execute berikutnya adalah `STARTED`. Untuk 37 baris saat ini, `PREP-*`, catatan prefill, serta waktu kosong menunjukkan entri persiapan yang belum membuktikan run nyata. | Run (proyeksi dari checkpoint), tetapi entri sumber adalah placeholder antrean/persiapan | `training_runs.status='QUEUED'` hanya jika kemudian dikonfirmasi sebagai run sungguhan yang queued. Jangan buat run dari placeholder; simpan nilai asli `PENDING` dan `QUEUED` sebagai metadata sumber. | Tinggi untuk aturan kode; sedang untuk keadaan historis tiap baris |

### Siklus status berdasarkan kode

- `batch_checkpoint_manager.py` dan `batch1_execution_runner.py` mendefinisikan checkpoint `QUEUED → STARTED → TRAIN_DONE → VALIDATED → PROMOTED`, dengan cabang `FAILED → RETRY_PENDING → STARTED`.
- Projection `run_status` pada runner: `QUEUED → PENDING`; `STARTED`, `TRAIN_DONE`, `VALIDATED → RUNNING`; `PROMOTED → COMPLETED`; `FAILED → FAILED`; `RETRY_PENDING → RETRY_PENDING`.
- `process_run()` hanya memanggil pipeline setelah checkpoint `QUEUED`/`RETRY_PENDING` ditransisikan ke `STARTED`. Training terjadi di `STARTED`, lalu status `TRAIN_DONE`; validasi artefact baru mengarah ke `VALIDATED`; promosi dilakukan setelah validasi.
- `retry_count` bertambah saat checkpoint menjadi `FAILED`; retry memerlukan transisi eksplisit ke `RETRY_PENDING`, lalu kembali `STARTED`.
- Checkpoint `PROMOTED` bersifat terminal pada alur yang didokumentasikan. Artifact promotion memerlukan file staging dan metadata valid. CSV saat ini tidak mencatat path artifact/validation untuk 37 PREP entries.
- SQLite memisahkan `training_jobs`, `training_runs`, `checkpoints`, dan `model_artifacts`. `training_jobs.status` tidak memiliki `PLANNED` atau `MISSING`; `training_runs.status` tidak memiliki `PENDING`. `PROMOTED` adalah status lifecycle run, sedangkan lifecycle artifact terpisah.
- `create_dev_database`/SQLite repository belum terhubung ke runner; kode runner yang diaudit tetap membaca/menulis execution log CSV.

## 3. Dataset provenance

### Sumber dan verifikasi

`nexora_datahub/loader.py::discover_datasets()` menelusuri `data/raw` dan mengenali nama file sebagai kandidat symbol/timeframe. `batch1_execution_runner.py` juga membangun indeks dari `ROOT/data/raw`. Nama file tidak dipakai sebagai satu-satunya bukti: setiap file di tabel berikut dibaca untuk menghitung baris/tanggal, diperiksa header/kolom OHLC dan timestamp, di-hash penuh SHA-256, lalu dicocokkan dengan audit manifest per-file di `reports/audit/` (baris input/unik, duplikat, status, dan rentang waktu). Format yang ditemukan adalah CSV. Semua 11 file yang diperlukan berisi OHLC valid, 0 invalid timestamp, 0 missing OHLC, 0 nilai nonpositive, 0 invalid OHLC, 0 timestamp duplicate pada manifest, dan status `BASIC_CHECKS_PASS`; interval manifest `PASS`.

File raw tidak selalu tersusun monoton menurut timestamp. Loader mengurutkan bars berdasarkan `ts` sebelum deduplikasi; audit manifest menghitung jumlah unique setelah sort. Untuk M1/M2/M3/M4/M5/M6 dan XAU M1/M3, urutan sumber terdeteksi tidak monoton, tetapi timestamp valid dan jumlah unik manifest tetap sama dengan jumlah baris input. Gap count audit berada pada ribuan bar dan perlu ditafsirkan sebagai sesi/kalender instrumen, bukan bukti kelengkapan histori penuh.

`reports/data_inventory.json` mencatat 42 dataset raw untuk EURUSD/XAUUSD. Untuk job dalam plan, ditemukan 11 file unik yang relevan: 9 timeframe EURUSD dan 2 timeframe XAUUSD yang dibutuhkan job global. Tiap pasangan symbol/timeframe memiliki satu kandidat file di `data/raw`; tidak ditemukan duplikasi kandidat untuk kunci yang diperlukan. `data/processed` adalah salinan normalisasi dan bukan source path yang dipakai runner ini.

| Dataset ID | Symbol | Timeframe | Path | Date Range | Rows | SHA-256 | Status |
|---|---|---|---|---|---:|---|---|
| Not assigned (no source ID) | EURUSD | M1 | `D:\NEXORA_AI_v2\data\raw\EURUSD\EURUSD_M1_202001020000_202611062158.csv` | 2020-01-02 00:00:00 → 2026-11-06 21:58:00 | 1,997,692 | `3e7c590ae30e7dffc852cac5667ac2cd2f8fa5f6b0b95245875c7ae57292f555` | VERIFIED; manifest unique rows match current file rows; 0 duplicate timestamps; BASIC_CHECKS_PASS |
| Not assigned (no source ID) | EURUSD | M15 | `D:\NEXORA_AI_v2\data\raw\EURUSD\EURUSD_M15_202001020000_202611062145.csv` | 2020-01-02 00:00:00 → 2026-11-06 21:45:00 | 137,995 | `7b72f6cd9ab14ffd8d8479e4647fb2688a4c228aa80ce8edcd3a8fe5c7399f7f` | VERIFIED; manifest unique rows match current file rows; 0 duplicate timestamps; BASIC_CHECKS_PASS |
| Not assigned (no source ID) | EURUSD | M2 | `D:\NEXORA_AI_v2\data\raw\EURUSD\EURUSD_M2_202001020000_202611062158.csv` | 2020-01-02 00:00:00 → 2026-11-06 21:58:00 | 1,008,234 | `13859e31793517bdada9b9697a06ddbdc95e6d9b9f262672151738e1c1fc86c6` | VERIFIED; manifest unique rows match current file rows; 0 duplicate timestamps; BASIC_CHECKS_PASS |
| Not assigned (no source ID) | EURUSD | M20 | `D:\NEXORA_AI_v2\data\raw\EURUSD\EURUSD_M20_202001020000_202611062140.csv` | 2020-01-02 00:00:00 → 2026-11-06 21:40:00 | 104,345 | `53c814ffc2606ee9beb39f1670bca1aa102401431b4022a4d4a80cf0adc88773` | VERIFIED; manifest unique rows match current file rows; 0 duplicate timestamps; BASIC_CHECKS_PASS |
| Not assigned (no source ID) | EURUSD | M3 | `D:\NEXORA_AI_v2\data\raw\EURUSD\EURUSD_M3_202001020000_202611062157.csv` | 2020-01-02 00:00:00 → 2026-11-06 21:57:00 | 674,812 | `d8f8d47e9c6f7eea5911a91c6cdbcd419aede035a6af3864e00d9151248d8659` | VERIFIED; manifest unique rows match current file rows; 0 duplicate timestamps; BASIC_CHECKS_PASS |
| Not assigned (no source ID) | EURUSD | M30 | `D:\NEXORA_AI_v2\data\raw\EURUSD\EURUSD_M30_202001020000_202611062130.csv` | 2020-01-02 00:00:00 → 2026-11-06 21:30:00 | 70,694 | `e6729c4596f872f503cc04c7611375419395ab9cc92f9d918121609cdb282945` | VERIFIED; manifest unique rows match current file rows; 0 duplicate timestamps; BASIC_CHECKS_PASS |
| Not assigned (no source ID) | EURUSD | M4 | `D:\NEXORA_AI_v2\data\raw\EURUSD\EURUSD_M4_202001020000_202611062156.csv` | 2020-01-02 00:00:00 → 2026-11-06 21:56:00 | 507,344 | `ad62a76d54b48a9f65e88919af0e11766cd0b330d0eed7b1f227a860e9ec7ee4` | VERIFIED; manifest unique rows match current file rows; 0 duplicate timestamps; BASIC_CHECKS_PASS |
| Not assigned (no source ID) | EURUSD | M5 | `D:\NEXORA_AI_v2\data\raw\EURUSD\EURUSD_M5_202001020000_202611062155.csv` | 2020-01-02 00:00:00 → 2026-11-06 21:55:00 | 406,686 | `394968386845468ada2374374f92d9563836163e1465d60257d91ca4a7fc9fd5` | VERIFIED; manifest unique rows match current file rows; 0 duplicate timestamps; BASIC_CHECKS_PASS |
| Not assigned (no source ID) | EURUSD | M6 | `D:\NEXORA_AI_v2\data\raw\EURUSD\EURUSD_M6_202001020000_202611062154.csv` | 2020-01-02 00:00:00 → 2026-11-06 21:54:00 | 339,724 | `aef53eb85629740fbd506a0cea5aeeb39c109ed0ff407da73b895b97630f2f36` | VERIFIED; manifest unique rows match current file rows; 0 duplicate timestamps; BASIC_CHECKS_PASS |
| Not assigned (no source ID) | XAUUSD | M1 | `D:\NEXORA_AI_v2\data\raw\XAUUSD_M1.csv` | 2020-01-02 01:00:00 → 2025-07-20 23:59:00 | 1,889,105 | `cd64c387f010f783d79148e99a49955a1fb26f0891278f1a3e33a1070d27444d` | VERIFIED; manifest unique rows match current file rows; 0 duplicate timestamps; BASIC_CHECKS_PASS |
| Not assigned (no source ID) | XAUUSD | M3 | `D:\NEXORA_AI_v2\data\raw\XAUUSD_M3.csv` | 2020-01-02 01:00:00 → 2025-07-20 23:57:00 | 631,040 | `c26e16821f591f086a136323fd152b4919eaece26bd8ad4378ea1c348cc88563` | VERIFIED; manifest unique rows match current file rows; 0 duplicate timestamps; BASIC_CHECKS_PASS |

`Dataset ID` tidak tersedia pada CSV, manifest, maupun tabel SQLite yang kosong; kolom tersebut sengaja tidak dibuatkan ID buatan.

### Job global

Plan secara eksplisit menyebut `EURUSD+XAUUSD` dan “strict … pooled set”. Kode `nexora_learning/train_all.py` membentuk grup dataset yang usable per timeframe dan `nexora_learning/global_train.py::train_global_group()` menggabungkan feature rows dari dua simbol; ini mendukung model global berbasis dua sumber.

- M1: EURUSD 1.997.692 rows + XAUUSD 1.889.105 rows = **3.886.797 component rows**. `dataset_rows` plan untuk keenam job M1 adalah **1.889.105**, sama dengan komponen yang lebih kecil.
- M3: EURUSD 674.812 + XAUUSD 631.040 = **1.305.852 component rows**. `dataset_rows` plan untuk keempat job M3 adalah **631.040**, juga sama dengan komponen yang lebih kecil.
- Ini mengindikasikan `dataset_rows` global mungkin merepresentasikan batas/minimum common dataset rows, tetapi generator planner tidak ditemukan dan tidak ada dokumentasi definisi field yang memastikan interpretasi tersebut. Maka nilai aggregate job global diberi `METADATA_MISMATCH`, walaupun kedua file komponentnya masing-masing terverifikasi.
- Rentang XAUUSD M1/M3 berakhir pada 2025-07-20, sedangkan EURUSD berlanjut sampai 2026-11-06. Pooled model dapat menerima rentang berbeda menurut kode, tetapi tidak ada aturan provenance yang menjelaskan apakah rentang historis harus disejajarkan.
- Batch runner yang terpasang belum mendukung global composite secara benar: `process_run()` mencari satu indeks `(row.symbol,row.timeframe)` sehingga `EURUSD+XAUUSD` tidak cocok dengan dua key file terpisah; `run_production_pipeline_to_staging()` memanggil `train_one(..., kind="individual")`. Fungsi global di `train_all.py/global_train.py` adalah jalur berbeda, tidak terhubung ke log `PREP-*` ini.

## 4. Job-to-dataset reconciliation

`job_key` tidak ada dalam kedua CSV, sehingga kolom di bawah memakai `— (not supplied)` dan tidak membuat identifier baru. Tuple yang dipakai: `(scope, ifnull(symbol,''), timeframe, horizon)`. Semua 37 job individual memiliki satu file dan jumlah bars plan cocok. Sepuluh job global menggunakan dua file yang sama per timeframe; statusnya mencerminkan ketidakjelasan arti aggregate `dataset_rows`.

| Job Key | Scope | Symbol | Timeframe | Horizon | Dataset | Verification |
| — (not in CSV) | individual | EURUSD | M30 | 2 | data/raw/EURUSD/EURUSD_M30_202001020000_202611062130.csv | VERIFIED — raw rows, unique rows, and plan rows agree (70694) |
| — (not in CSV) | individual | EURUSD | M30 | 4 | data/raw/EURUSD/EURUSD_M30_202001020000_202611062130.csv | VERIFIED — raw rows, unique rows, and plan rows agree (70694) |
| — (not in CSV) | individual | EURUSD | M30 | 8 | data/raw/EURUSD/EURUSD_M30_202001020000_202611062130.csv | VERIFIED — raw rows, unique rows, and plan rows agree (70694) |
| — (not in CSV) | individual | EURUSD | M30 | 12 | data/raw/EURUSD/EURUSD_M30_202001020000_202611062130.csv | VERIFIED — raw rows, unique rows, and plan rows agree (70694) |
| — (not in CSV) | individual | EURUSD | M30 | 24 | data/raw/EURUSD/EURUSD_M30_202001020000_202611062130.csv | VERIFIED — raw rows, unique rows, and plan rows agree (70694) |
| — (not in CSV) | individual | EURUSD | M20 | 2 | data/raw/EURUSD/EURUSD_M20_202001020000_202611062140.csv | VERIFIED — raw rows, unique rows, and plan rows agree (104345) |
| — (not in CSV) | individual | EURUSD | M20 | 4 | data/raw/EURUSD/EURUSD_M20_202001020000_202611062140.csv | VERIFIED — raw rows, unique rows, and plan rows agree (104345) |
| — (not in CSV) | individual | EURUSD | M20 | 8 | data/raw/EURUSD/EURUSD_M20_202001020000_202611062140.csv | VERIFIED — raw rows, unique rows, and plan rows agree (104345) |
| — (not in CSV) | individual | EURUSD | M20 | 12 | data/raw/EURUSD/EURUSD_M20_202001020000_202611062140.csv | VERIFIED — raw rows, unique rows, and plan rows agree (104345) |
| — (not in CSV) | individual | EURUSD | M20 | 24 | data/raw/EURUSD/EURUSD_M20_202001020000_202611062140.csv | VERIFIED — raw rows, unique rows, and plan rows agree (104345) |
| — (not in CSV) | individual | EURUSD | M15 | 12 | data/raw/EURUSD/EURUSD_M15_202001020000_202611062145.csv | VERIFIED — raw rows, unique rows, and plan rows agree (137995) |
| — (not in CSV) | individual | EURUSD | M15 | 24 | data/raw/EURUSD/EURUSD_M15_202001020000_202611062145.csv | VERIFIED — raw rows, unique rows, and plan rows agree (137995) |
| — (not in CSV) | individual | EURUSD | M6 | 2 | data/raw/EURUSD/EURUSD_M6_202001020000_202611062154.csv | VERIFIED — raw rows, unique rows, and plan rows agree (339724) |
| — (not in CSV) | individual | EURUSD | M6 | 4 | data/raw/EURUSD/EURUSD_M6_202001020000_202611062154.csv | VERIFIED — raw rows, unique rows, and plan rows agree (339724) |
| — (not in CSV) | individual | EURUSD | M6 | 8 | data/raw/EURUSD/EURUSD_M6_202001020000_202611062154.csv | VERIFIED — raw rows, unique rows, and plan rows agree (339724) |
| — (not in CSV) | individual | EURUSD | M6 | 12 | data/raw/EURUSD/EURUSD_M6_202001020000_202611062154.csv | VERIFIED — raw rows, unique rows, and plan rows agree (339724) |
| — (not in CSV) | individual | EURUSD | M6 | 24 | data/raw/EURUSD/EURUSD_M6_202001020000_202611062154.csv | VERIFIED — raw rows, unique rows, and plan rows agree (339724) |
| — (not in CSV) | individual | EURUSD | M5 | 2 | data/raw/EURUSD/EURUSD_M5_202001020000_202611062155.csv | VERIFIED — raw rows, unique rows, and plan rows agree (406686) |
| — (not in CSV) | individual | EURUSD | M5 | 4 | data/raw/EURUSD/EURUSD_M5_202001020000_202611062155.csv | VERIFIED — raw rows, unique rows, and plan rows agree (406686) |
| — (not in CSV) | individual | EURUSD | M5 | 8 | data/raw/EURUSD/EURUSD_M5_202001020000_202611062155.csv | VERIFIED — raw rows, unique rows, and plan rows agree (406686) |
| — (not in CSV) | individual | EURUSD | M5 | 12 | data/raw/EURUSD/EURUSD_M5_202001020000_202611062155.csv | VERIFIED — raw rows, unique rows, and plan rows agree (406686) |
| — (not in CSV) | individual | EURUSD | M5 | 24 | data/raw/EURUSD/EURUSD_M5_202001020000_202611062155.csv | VERIFIED — raw rows, unique rows, and plan rows agree (406686) |
| — (not in CSV) | individual | EURUSD | M4 | 2 | data/raw/EURUSD/EURUSD_M4_202001020000_202611062156.csv | VERIFIED — raw rows, unique rows, and plan rows agree (507344) |
| — (not in CSV) | individual | EURUSD | M4 | 4 | data/raw/EURUSD/EURUSD_M4_202001020000_202611062156.csv | VERIFIED — raw rows, unique rows, and plan rows agree (507344) |
| — (not in CSV) | individual | EURUSD | M4 | 8 | data/raw/EURUSD/EURUSD_M4_202001020000_202611062156.csv | VERIFIED — raw rows, unique rows, and plan rows agree (507344) |
| — (not in CSV) | individual | EURUSD | M4 | 12 | data/raw/EURUSD/EURUSD_M4_202001020000_202611062156.csv | VERIFIED — raw rows, unique rows, and plan rows agree (507344) |
| — (not in CSV) | individual | EURUSD | M4 | 24 | data/raw/EURUSD/EURUSD_M4_202001020000_202611062156.csv | VERIFIED — raw rows, unique rows, and plan rows agree (507344) |
| — (not in CSV) | individual | EURUSD | M3 | 2 | data/raw/EURUSD/EURUSD_M3_202001020000_202611062157.csv | VERIFIED — raw rows, unique rows, and plan rows agree (674812) |
| — (not in CSV) | individual | EURUSD | M3 | 4 | data/raw/EURUSD/EURUSD_M3_202001020000_202611062157.csv | VERIFIED — raw rows, unique rows, and plan rows agree (674812) |
| — (not in CSV) | individual | EURUSD | M3 | 8 | data/raw/EURUSD/EURUSD_M3_202001020000_202611062157.csv | VERIFIED — raw rows, unique rows, and plan rows agree (674812) |
| — (not in CSV) | individual | EURUSD | M3 | 12 | data/raw/EURUSD/EURUSD_M3_202001020000_202611062157.csv | VERIFIED — raw rows, unique rows, and plan rows agree (674812) |
| — (not in CSV) | individual | EURUSD | M3 | 24 | data/raw/EURUSD/EURUSD_M3_202001020000_202611062157.csv | VERIFIED — raw rows, unique rows, and plan rows agree (674812) |
| — (not in CSV) | individual | EURUSD | M2 | 2 | data/raw/EURUSD/EURUSD_M2_202001020000_202611062158.csv | VERIFIED — raw rows, unique rows, and plan rows agree (1008234) |
| — (not in CSV) | individual | EURUSD | M2 | 4 | data/raw/EURUSD/EURUSD_M2_202001020000_202611062158.csv | VERIFIED — raw rows, unique rows, and plan rows agree (1008234) |
| — (not in CSV) | individual | EURUSD | M2 | 8 | data/raw/EURUSD/EURUSD_M2_202001020000_202611062158.csv | VERIFIED — raw rows, unique rows, and plan rows agree (1008234) |
| — (not in CSV) | individual | EURUSD | M2 | 12 | data/raw/EURUSD/EURUSD_M2_202001020000_202611062158.csv | VERIFIED — raw rows, unique rows, and plan rows agree (1008234) |
| — (not in CSV) | individual | EURUSD | M2 | 24 | data/raw/EURUSD/EURUSD_M2_202001020000_202611062158.csv | VERIFIED — raw rows, unique rows, and plan rows agree (1008234) |
| — (not in CSV) | global | EURUSD+XAUUSD | M3 | 4 | D:\NEXORA_AI_v2\data\raw\EURUSD\EURUSD_M3_202001020000_202611062157.csv<br>D:\NEXORA_AI_v2\data\raw\XAUUSD_M3.csv | METADATA_MISMATCH — both files verified; pooled rows 1,305,852, plan dataset_rows 631,040 (equals smaller component) |
| — (not in CSV) | global | EURUSD+XAUUSD | M3 | 8 | D:\NEXORA_AI_v2\data\raw\EURUSD\EURUSD_M3_202001020000_202611062157.csv<br>D:\NEXORA_AI_v2\data\raw\XAUUSD_M3.csv | METADATA_MISMATCH — both files verified; pooled rows 1,305,852, plan dataset_rows 631,040 (equals smaller component) |
| — (not in CSV) | global | EURUSD+XAUUSD | M3 | 12 | D:\NEXORA_AI_v2\data\raw\EURUSD\EURUSD_M3_202001020000_202611062157.csv<br>D:\NEXORA_AI_v2\data\raw\XAUUSD_M3.csv | METADATA_MISMATCH — both files verified; pooled rows 1,305,852, plan dataset_rows 631,040 (equals smaller component) |
| — (not in CSV) | global | EURUSD+XAUUSD | M3 | 24 | D:\NEXORA_AI_v2\data\raw\EURUSD\EURUSD_M3_202001020000_202611062157.csv<br>D:\NEXORA_AI_v2\data\raw\XAUUSD_M3.csv | METADATA_MISMATCH — both files verified; pooled rows 1,305,852, plan dataset_rows 631,040 (equals smaller component) |
| — (not in CSV) | global | EURUSD+XAUUSD | M1 | 1 | D:\NEXORA_AI_v2\data\raw\EURUSD\EURUSD_M1_202001020000_202611062158.csv<br>D:\NEXORA_AI_v2\data\raw\XAUUSD_M1.csv | METADATA_MISMATCH — both files verified; pooled rows 3,886,797, plan dataset_rows 1,889,105 (equals smaller component) |
| — (not in CSV) | global | EURUSD+XAUUSD | M1 | 2 | D:\NEXORA_AI_v2\data\raw\EURUSD\EURUSD_M1_202001020000_202611062158.csv<br>D:\NEXORA_AI_v2\data\raw\XAUUSD_M1.csv | METADATA_MISMATCH — both files verified; pooled rows 3,886,797, plan dataset_rows 1,889,105 (equals smaller component) |
| — (not in CSV) | global | EURUSD+XAUUSD | M1 | 4 | D:\NEXORA_AI_v2\data\raw\EURUSD\EURUSD_M1_202001020000_202611062158.csv<br>D:\NEXORA_AI_v2\data\raw\XAUUSD_M1.csv | METADATA_MISMATCH — both files verified; pooled rows 3,886,797, plan dataset_rows 1,889,105 (equals smaller component) |
| — (not in CSV) | global | EURUSD+XAUUSD | M1 | 8 | D:\NEXORA_AI_v2\data\raw\EURUSD\EURUSD_M1_202001020000_202611062158.csv<br>D:\NEXORA_AI_v2\data\raw\XAUUSD_M1.csv | METADATA_MISMATCH — both files verified; pooled rows 3,886,797, plan dataset_rows 1,889,105 (equals smaller component) |
| — (not in CSV) | global | EURUSD+XAUUSD | M1 | 12 | D:\NEXORA_AI_v2\data\raw\EURUSD\EURUSD_M1_202001020000_202611062158.csv<br>D:\NEXORA_AI_v2\data\raw\XAUUSD_M1.csv | METADATA_MISMATCH — both files verified; pooled rows 3,886,797, plan dataset_rows 1,889,105 (equals smaller component) |
| — (not in CSV) | global | EURUSD+XAUUSD | M1 | 24 | D:\NEXORA_AI_v2\data\raw\EURUSD\EURUSD_M1_202001020000_202611062158.csv<br>D:\NEXORA_AI_v2\data\raw\XAUUSD_M1.csv | METADATA_MISMATCH — both files verified; pooled rows 3,886,797, plan dataset_rows 1,889,105 (equals smaller component) |

Ringkasan klasifikasi: **37 VERIFIED**, **10 METADATA_MISMATCH**, **0 DATASET_MISSING**, **0 DATASET_AMBIGUOUS**, **0 UNRESOLVED karena file tidak ditemukan**. Global rows tetap belum siap dikonversi ke dataset IDs sampai kebijakan `dataset_rows` dan model global disepakati.

## 5. Unresolved issues

1. Source code pembuat `MISSING`/`TRAIN` dan generator `batch_retraining_plan.csv` tidak ada pada repository yang diperiksa. Arti `MISSING` didukung report coverage/planner, bukan implementasi pembuat status.
2. Tidak ada aturan resmi apakah plan-only row adalah `PLANNED`, job `QUEUED`, atau hanya rekomendasi. Schema saat ini tidak menyimpan state `PLANNED`.
3. `PENDING` secara kode berarti checkpoint QUEUED, tetapi isi CSV menunjukkan PREP placeholder. Belum ada bukti bahwa 37 run benar-benar dibuat/queued sebagai eksekusi historis.
4. Tidak ada `job_key`, dataset ID, dataset source path pada CSV, atau schema sumber untuk mempertahankan identitas historis tersebut.
5. Untuk global, sumber file ditemukan, tetapi `dataset_rows` sama dengan jumlah komponen minimum, bukan total dua sumber; generator field hilang. Rentang tanggal kedua simbol juga berbeda.
6. Runner batch yang tersedia membangun satu file per symbol/timeframe dan menjalankan pipeline individual. Jalur global pooled ada di `train_all.py/global_train.py` tetapi belum terintegrasi dengan format run log yang diaudit.
7. Audit content read-only tidak membuktikan histori pasar lengkap. Gap counts tetap memerlukan interpretasi domain.

## 6. Proposed SQLite mapping

### Fakta

- Plan tuple dapat dicocokkan ke `training_jobs` dengan kolom `scope`, `symbol`, `timeframe`, `horizon`; 47 tuple tidak duplikat.
- `training_jobs.job_key` adalah `NOT NULL UNIQUE`, tetapi sumber tidak menyediakan job_key.
- Setiap job individual punya satu raw dataset yang terverifikasi; global M1/M3 punya dua raw component files yang terverifikasi.
- Execution CSV berisi status placeholder `PENDING/QUEUED`, bukan hasil training; tidak ada output artifact/validation.

### Proposal (belum dijalankan)

- **Jangan memetakan** `MISSING` atau `TRAIN` ke `training_jobs.status`. Simpan nilai asal sebagai metadata legacy yang eksplisit (misalnya JSON berversi dengan `legacy_current_status` dan `legacy_plan_action`) atau simpan pada tabel plan/provenance khusus.
- Tetapkan kebijakan/format `job_key` deterministik dari tuple sebelum import; jangan membuat key saat audit ini.
- Setelah sumber dataset dan global aggregation disetujui, buat dataset records berdasarkan file raw terverifikasi beserta source path, current file SHA-256, row count, date range, symbol, timeframe; buat `training_job_datasets` satu link untuk individual dan dua link untuk global.
- Perlakukan 37 pasangan plan+execution log sebagai satu calon job berdasarkan tuple, simpan kedua provenance sumber, dan jangan mengimpor dua job. Tetapi jangan membuat `training_runs`/`checkpoints` dari `PREP-*` sampai dipastikan status QUEUED merupakan event antrean aktual.
- Sepuluh plan-only rows semuanya global M1/M3. Pertahankan sebagai rencana; jangan menyebutnya run.
- Untuk jika kelak terbukti ada run queued sungguhan: kandidat semantik `PENDING` → SQLite run `QUEUED`, dengan nilai legacy `PENDING` tetap tersimpan. Catat checkpoint hanya bila ada event/status history yang bisa dibuktikan, bukan sekadar nilai prefill.
- Jangan membuat `model_artifacts`, `validation_results`, atau audit transition tanpa path/hash/result/event historis yang nyata.

### Rekomendasi

Selesaikan generator/definisi legacy statuses, aturan `job_key`, definisi global `dataset_rows`, dan wiring global runner sebelum migration simulation dilanjutkan. Setelah keputusan eksplisit, buat pemetaan yang merepresentasikan PLANNED terpisah dari QUEUED (melalui schema/plan provenance) dan baru lakukan simulasi pada clone baru.

## 7. Risiko migrasi

- Memetakan `TRAIN` atau `MISSING` ke `QUEUED` akan mengubah intent/coverage menjadi status eksekusi.
- Membuat run/checkpoint dari `PREP-*` dapat mengarang histori, mengganggu claim queue, dan membuat audit log menyesatkan.
- Menggunakan satu global `dataset_rows` sebagai pooled row total akan salah hitung; menjumlah tanpa definisi juga mungkin menggandakan asumsi per simbol.
- Path kandidat dari loader bisa bergeser jika ada lebih dari satu file per symbol/timeframe di masa depan; loader index saat ini meng-overwrite duplikat key berdasarkan iterasi.
- Global M1/M3 memiliki coverage date range berbeda antar simbol; status `BASIC_CHECKS_PASS` tidak menjamin rentang pooled seimbang atau bebas bias.
- Hash ini adalah hash file saat audit; database `datasets.content_sha256` sebaiknya merekam ulang tepat sebelum import jika suatu saat disetujui.

## 8. Rekomendasi tahap selanjutnya

1. Temukan/arsipkan script planner asli atau tetapkan spesifikasi generator `MISSING`, `TRAIN`, dan `dataset_rows`.
2. Konfirmasi `PENDING/QUEUED` pada log ini hanya placeholder atau benar-benar antrean run yang dibuat; bukti saat ini lebih mendukung placeholder.
3. Tetapkan format `job_key` dan apakah `legacy_current_status`/`legacy_plan_action` disimpan pada `config_json` atau tabel provenance.
4. Tegaskan global dataset contract: symbol component list, dua dataset links, pooled row count (sum vs min/common), dan rentang tanggal yang diizinkan.
5. Integrasikan global scope dengan queue/runner terpisah yang memanggil global training; jangan mengirim global tuple ke jalur individual.
6. Setelah itu ulangi mapping dan job-to-dataset reconciliation. Sampai semua isu ini selesai, jangan melakukan import/migrasi.

**Kesimpulan akhir: PARTIALLY_READY.** File sumber untuk 37 job individual dan empat komponen global tersedia dan kontennya terverifikasi; tetapi 10 job global memiliki konvensi jumlah baris yang belum jelas, status run masih placeholder, job_key tidak tersedia, serta runner global belum terhubung. Belum siap untuk import atau migrasi.
