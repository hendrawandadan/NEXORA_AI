# SQLite Legacy CSV Migration Simulation Report

Tanggal: 2026-11-07  
Hasil: **BLOCKED** — import dihentikan sebelum INSERT karena status legacy dan pemetaan dataset tidak dapat diterjemahkan ke schema aktual tanpa asumsi.

## 1. Executive summary

Database produksi disalin ke database simulasi menggunakan SQLite Backup API. Clone valid dan identik dalam schema terhadap sumber. Analisis CSV menemukan **47 tuple job unik** pada union kedua file: 37 job muncul pada kedua CSV, 10 hanya pada plan, dan 0 hanya pada execution log. Tidak ada tuple duplikat di masing-masing file dan tidak ada perbedaan pada field bersama yang dapat dibandingkan.

Import tidak dimulai. CSV menggambarkan rencana/persiapan: plan berisi `current_status=MISSING` dan `plan_action=TRAIN`; execution log berisi `run_status=PENDING`, ID `PREP-*`, semua waktu mulai/selesai kosong, dan catatan “Pre-filled from batch_retraining_plan”. Schema SQLite tidak memiliki job status `PLANNED` atau `PENDING`; `MISSING` juga bukan status job. Selain itu, CSV tidak menyertakan path sumber dataset yang wajib untuk membuat baris `datasets`. Mengubah status menjadi `QUEUED`, atau mengarang path/dataset/run, akan melanggar aturan tanpa asumsi. Karena ambiguitas ini ditemukan sebelum INSERT, import, idempotency test, dan rollback-import test tidak dijalankan.

Database produksi dan kedua CSV tetap byte-identik dengan baseline yang direkam. Tidak ada training yang dijalankan.

## 2. Preflight audit

### Database produksi

| Pemeriksaan | Hasil aktual |
|---|---|
| Path | `D:\NEXORA_AI_v2\database\nexora_state.db` |
| Ukuran file utama | 139.264 byte |
| SHA-256 sebelum simulasi | `E314244ED46099ABD0025E982640B9BE7711F608AC9A75FF5B44E4D43286D6C6` |
| Schema version | 2 |
| `PRAGMA integrity_check` | `ok` |
| `PRAGMA foreign_key_check` | 0 violation |
| Journal mode | `wal` |
| WAL sidecar saat preflight | Ada, 0 byte |
| SHM sidecar saat preflight | Ada, 32.768 byte |
| Tabel data | 11 tabel; seluruh tabel data kosong, `schema_migrations` berisi 2 versi |
| Indeks | 18 total (10 indeks bernama dan 8 autoindex SQLite) |

### CSV legacy

| File | Baris | Kolom | Kolom/baris kosong | SHA-256 awal |
|---|---:|---:|---|---|
| `reports/retraining/batch_retraining_plan.csv` | 47 | 15 | Tidak ada sel kosong | `1BBEA13995BDECBE9A37C2481EE0EEE74E520C8E241A4F8779258EBDA5F7F1F0` |
| `reports/retraining/batch_execution_log.csv` | 37 | 38 | Kolom waktu, metrik training, konfigurasi, artifact, report, metadata, dan error yang terinci di bawah kosong pada semua 37 baris | `D73F196D5A313D1AB3FC878EA354B944AECAF8D074E94BC5DDA42900E0BF2DD8` |

Validasi format aktual: `order`, `horizon`, `dataset_rows`, dan `retry_count` berformat integer; `compute_weight_full` numerik; `dataset_usable` berisi string `True`. Nilai `scope` pada plan adalah `individual`/`global`; execution log seluruhnya `individual`. Kedua CSV tidak memiliki kolom `job_key`.

Kolom execution log yang kosong pada semua baris: `start_time`, `end_time`, `checkpoint_updated_at`, `train_rows`, `validation_rows`, `test_rows`, `training_config`, `config_match`, `temp_model_path`, `temp_report_path`, `temp_signals_path`, `temp_metadata_path`, `final_model_path`, `final_report_path`, `final_signals_path`, `final_metadata_path`, `report_path`, `model_path`, `signals_path`, `metadata_match`, `artifact_sync`, dan `error_message`.

## 3. Database clone verification

Clone dibuat pada `D:\NEXORA_AI_v2\database\simulation\migration_simulation.db` menggunakan `sqlite3.Connection.backup()` dari koneksi produksi read-only. Target belum ada sebelum proses; publikasi dilakukan sebagai file terpisah.

| Pemeriksaan clone | Hasil aktual |
|---|---|
| Ukuran | 139.264 byte |
| SHA-256 | `92E2AA546CD75A0697688670B901371462BCCC1FEB0B2E3A6A7D3D4E015EA701` |
| Schema version | 2 |
| Integrity | `ok` |
| Foreign-key violations | 0 |
| Tabel | 11; definisi sama dengan produksi |
| Indeks | 18; definisi sama dengan produksi |
| Isi awal | 0 job, 0 dataset, 0 link dataset, 0 run, 0 checkpoint, 0 artifact, 0 validation, 0 audit, 0 legacy import; 2 baris schema migration |

## 4. CSV schema mapping analysis

Unique tuple yang dipakai schema/migration adalah:

```sql
UNIQUE (scope, ifnull(symbol, ''), timeframe, horizon)
```

Pencocokan menggunakan nilai CSV mentah untuk scope, symbol, timeframe, dan horizon integer; string simbol kosong dipetakan ke `''`, sejalan dengan `ifnull`. Tidak ada trimming, perubahan case, atau penggabungan simbol. `job_key` tidak tersedia di kedua sumber.

| CSV source / column | SQLite target candidate | Transformasi/hasil audit |
|---|---|---|
| Plan: `scope`, `symbol`, `timeframe`, `horizon` | `training_jobs.scope`, `.symbol`, `.timeframe`, `.horizon` | Tuple cocok langsung. `horizon` di-parse sebagai integer. Untuk global, simbol literal `EURUSD+XAUUSD`; tidak dipecah tanpa aturan yang disepakati. |
| Plan: `batch`, `order`, `priority_reason`, `compute_weight_full`, `compute_tier`, `checkpoint_group` | Tidak ada kolom khusus; kemungkinan metadata `config_json` | Tidak ditransformasikan karena kontrak metadata/config belum ditentukan. `order` adalah urutan plan, bukan primary key. |
| Plan: `dataset_rows` | Kandidat `datasets.bars_count` | Tidak cukup untuk membuat dataset: `source_path` wajib tetapi tidak ada di CSV; tidak tersedia dataset ID/hash/time-range. Untuk global, satu baris merepresentasikan dua simbol. |
| Plan: `dataset_status`, `dataset_usable` | Kandidat `datasets.status` | Tidak kompatibel langsung: `BASIC_CHECKS_PASS` (termasuk nilai gabungan `BASIC_CHECKS_PASS;BASIC_CHECKS_PASS`) bukan enum DB (`usable`, `insufficient`, `invalid`, `archived`). String `True` tidak cukup untuk menetapkan path atau status dataset. |
| Plan: `current_status` | Tidak ada pemetaan job yang aman | Semua nilai `MISSING`; bukan status `training_jobs`. Tampaknya menjelaskan kondisi artifact/model saat ini, bukan status eksekusi job. |
| Plan: `plan_action` | Tidak ada status DB yang setara | Semua `TRAIN`; aksi yang direncanakan, bukan status job (`QUEUED`, `RUNNING`, dst.). |
| Log: `scope`, `symbol`, `timeframe`, `horizon` | Identitas `training_jobs` | Seluruh 37 tuple cocok dengan plan. |
| Log: `execution_id`, `run_id` | Kandidat `training_runs.run_uid` | Nilai `PREP-001`…`PREP-037` dan catatan pre-filled menunjukkan ID persiapan; tidak diperlakukan sebagai run yang benar-benar terjadi. |
| Log: `batch`, `checkpoint_group`, `planned_action`, `engine`, `training_config`, `config_match`, `retry_count`, `notes` | Metadata konfigurasi/audit | Tidak ada kontrak transformasi. `training_config` dan `config_match` kosong di semua baris; nilai lain tidak membuktikan run telah terjadi. |
| Log: `run_status` | Kandidat `training_runs.status` | `PENDING` pada 37 baris; nilai ini tidak termasuk enum schema run dan tidak boleh otomatis diubah menjadi `QUEUED`. |
| Log: `checkpoint_status`, `last_checkpoint` | Kandidat `checkpoints.checkpoint_status` | Nilai `QUEUED` valid secara enum, tetapi tidak ada run nyata untuk direferensikan dan tidak ada timestamp transisi. Tidak dibuat checkpoint. |
| Log: `start_time`, `end_time` | `training_runs.started_at`, `.ended_at` | Kosong pada semua baris; tidak menunjukkan run dimulai/selesai. |
| Log: `checkpoint_updated_at` | `checkpoints.changed_at` | Kosong pada semua baris; tidak ada waktu event checkpoint. |
| Log: `dataset_rows` | Kandidat `datasets.bars_count` | Tidak ada `source_path`, hash, atau pemetaan dataset per job; tidak dapat membuat dataset/link dengan benar. |
| Log: `train_rows`, `validation_rows`, `test_rows` | Run/validation metadata | Kosong pada semua baris; tidak membuat `training_runs` atau `validation_results`. |
| Log: `temp_model_path`, `temp_report_path`, `temp_signals_path`, `temp_metadata_path`, `final_model_path`, `final_report_path`, `final_signals_path`, `final_metadata_path`, `report_path`, `model_path`, `signals_path` | Kandidat `model_artifacts` | Kosong pada semua baris; tidak ada artifact untuk dicatat. |
| Log: `metadata_match`, `artifact_sync`, `error_message` | Audit/error metadata | Kosong pada semua baris; tidak ada hasil verifikasi atau error aktual untuk direkam. |
| Kedua CSV: — | `training_job_datasets` | Tidak ada source path/dataset ID/role yang cukup untuk membuat hubungan job-dataset. |
| Kedua CSV: — | `audit_logs` | Tidak ada event transisi nyata; tidak mengarang audit transition. |
| Kedua CSV: — | `legacy_imports` | Tidak ada import dimulai; tidak menulis catatan yang mengesankan import berhasil. |

## 5. Job identity reconciliation

| Ukuran | Hasil |
|---|---:|
| Baris plan | 47 |
| Tuple unik plan | 47 |
| Baris execution log | 37 |
| Tuple unik execution log | 37 |
| Tuple sama pada kedua file | 37 |
| Hanya di plan | 10 |
| Hanya di execution log | 0 |
| Tuple unik pada union | 47 (bukan 84) |
| Duplikat internal plan / log | 0 / 0 |
| Konflik pada field bersama yang sebanding | 0 |

Keempat field identitas sama untuk semua 37 pasangan. `batch`, `checkpoint_group`, `dataset_rows`, dan `plan_action`/`planned_action` juga sama pada semua pasangan. Plan terdiri dari 37 baris `Batch 1` dan 10 baris `Batch 3`; log mencakup 37 baris `Batch 1`.

Sepuluh tuple yang hanya muncul di plan:

| Scope | Symbol | Timeframe | Horizon | Order |
|---|---|---:|---:|---:|
| global | EURUSD+XAUUSD | M1 | 1 | 5 |
| global | EURUSD+XAUUSD | M1 | 2 | 6 |
| global | EURUSD+XAUUSD | M1 | 4 | 7 |
| global | EURUSD+XAUUSD | M1 | 8 | 8 |
| global | EURUSD+XAUUSD | M1 | 12 | 9 |
| global | EURUSD+XAUUSD | M1 | 24 | 10 |
| global | EURUSD+XAUUSD | M3 | 4 | 1 |
| global | EURUSD+XAUUSD | M3 | 8 | 2 |
| global | EURUSD+XAUUSD | M3 | 12 | 3 |
| global | EURUSD+XAUUSD | M3 | 24 | 4 |

Pada pasangan yang sama, `current_status=MISSING` (ketersediaan model) dan `run_status=PENDING` (status log persiapan) bukan field dengan makna yang sama; tidak dihitung sebagai konflik nilai status yang sebanding. Namun keduanya juga bukan status job yang dapat dimasukkan langsung ke schema.

## 6. Duplicate analysis

Tidak ditemukan tuple duplikat dalam plan atau execution log, maupun antar file. Indeks SQLite akan memperlakukan `symbol=NULL` dan `symbol=''` sama melalui `ifnull`; kedua CSV tidak memiliki simbol kosong. SQLite melakukan perbandingan string sesuai nilai literal/collation default; analisis tidak menormalisasi huruf besar/kecil atau whitespace.

## 7. Import simulation results

**Import tidak dijalankan.** Tidak ada INSERT/UPDATE/DELETE pada clone. Jumlah imported=0 bukan hasil import sukses; itu menandakan tahap import tidak dimulai. `training_jobs`, `datasets`, `training_job_datasets`, dan seluruh tabel operasional lain tetap kosong. Tidak ada run, checkpoint, artifact, validation, audit import, atau status job yang dikarang.

Alasan berhenti sebelum INSERT:

1. Schema `training_jobs.status` tidak memiliki keadaan `PLANNED`; `MISSING` bukan status job. Menetapkan status `QUEUED` hanya dari `plan_action=TRAIN` akan mengubah rencana menjadi antrean tanpa kebijakan eksplisit.
2. `training_runs.status` tidak menerima `PENDING`, dan log hanya berisi PREP ID, tanpa waktu start/end, training config, metrik, artifact, atau bukti run dimulai. Tidak aman membuat run/checkpoint.
3. CSV tidak menyertakan `datasets.source_path`, yang wajib, sehingga dataset dan tautan job-dataset tidak dapat dibangun. Status `BASIC_CHECKS_PASS` juga bukan enum status dataset yang tersedia.
4. Metadata plan seperti `batch`, `order`, `compute_weight_full`, dan `priority_reason` tidak memiliki kontrak penyimpanan yang disepakati.

## 8. Idempotency test results

**NOT RUN** karena tidak ada import pertama yang aman untuk diulang. Tidak ada klaim bahwa import kedua berhasil atau idempotent. Clone tetap dalam kondisi pre-import dan semua tabel target tetap kosong.

## 9. Rollback test results

**NOT RUN** karena aturan mengharuskan berhenti ketika mapping ambigu, sebelum mutasi import. Tidak ada skenario exception/constraint yang dijalankan pada clone dan tidak ada transaksi import yang dicoba. Integrity clone tetap `ok` setelah pembuatan backup.

## 10. Data reconciliation

| Ukuran | Aktual setelah proses |
|---|---:|
| Baris plan / execution log | 47 / 37 |
| Job unik pada union | 47 |
| Match lintas file | 37 |
| Hanya plan / hanya log | 10 / 0 |
| Duplicate tuple / konflik tuple | 0 / 0 |
| Job diimpor / baris ditolak import | 0 / 0 (import tidak dimulai) |
| Konflik pemetaan yang belum diselesaikan | 1 blocker kebijakan/schema: status dan dataset mapping |
| Job pada clone | 0 |
| Dataset / job-dataset links pada clone | 0 / 0 |
| Runs / checkpoints pada clone | 0 / 0 |
| Audit logs / legacy imports pada clone | 0 / 0 |

## 11. Test results

| Test | Expected | Actual | Status |
|---|---|---|---|
| Production DB ada, schema version, integritas dan FK | Ada; v2; `ok`; tanpa FK violation | Ada; v2; `ok`; 0 violation | PASS |
| File/sidecar preflight | Catat ukuran/hash/WAL/SHM | DB 139.264 byte; WAL 0 byte ada; SHM 32.768 byte ada | PASS |
| CSV file/header/row count/hash | Verifikasi kedua sumber | Plan 47 baris/15 kolom; log 37/38; hash dicatat | PASS |
| SQLite Backup API clone | Clone konsisten, berbeda path, schema/data sama | Clone dibuat; schema 2; tabel/indeks sama | PASS |
| Clone integrity/FK | `ok`, 0 FK violations | `ok`, 0 violation | PASS |
| Tuple duplikat dan lintas-source match | Laporkan semua match/selisih | 47 unique union; 37 overlap; 10 plan-only; 0 duplicates | PASS |
| CSV→SQLite mapping sebelum import | Semua kolom/status dapat dipetakan tanpa asumsi | Status job dan dataset tidak dapat dipetakan aman | BLOCKED |
| Import ke clone | Hanya setelah mapping disepakati | Tidak dimulai; 0 INSERT | BLOCKED (dihentikan sesuai guardrail) |
| Import ulang/idempotency | Tidak menggandakan job/checkpoint/audit | Tidak dijalankan karena tidak ada import awal | NOT RUN |
| Rollback skenario import | Seluruh perubahan gagal dibatalkan | Tidak dijalankan karena berhenti sebelum import | NOT RUN |
| Production DB hash sesudah simulasi | Sama dengan baseline | `E314244ED46099ABD0025E982640B9BE7711F608AC9A75FF5B44E4D43286D6C6`, sama | PASS |
| CSV hash sesudah simulasi | Sama dengan hash awal | Kedua hash sama (lihat bagian berikut) | PASS |
| Training / runner execute | Tidak dijalankan | Tidak dipanggil | PASS |

## 12. Production database hash verification

Hash database produksi setelah clone dan analisis tuple:

`E314244ED46099ABD0025E982640B9BE7711F608AC9A75FF5B44E4D43286D6C6`

Hash sama dengan baseline sebelum simulasi. Semua operasi pembuatan clone dilakukan pada `database/simulation/migration_simulation.db`; tidak ada penulisan data produksi.

## 13. CSV hash verification

| CSV | Hash awal | Hash akhir | Hasil |
|---|---|---|---|
| `batch_retraining_plan.csv` | `1BBEA13995BDECBE9A37C2481EE0EEE74E520C8E241A4F8779258EBDA5F7F1F0` | `1BBEA13995BDECBE9A37C2481EE0EEE74E520C8E241A4F8779258EBDA5F7F1F0` | Identik |
| `batch_execution_log.csv` | `D73F196D5A313D1AB3FC878EA354B944AECAF8D074E94BC5DDA42900E0BF2DD8` | `D73F196D5A313D1AB3FC878EA354B944AECAF8D074E94BC5DDA42900E0BF2DD8` | Identik |

## 14. Known limitations

- Tidak ada `job_key` di sumber; identitas hanya dapat direkonsiliasi lewat tuple.
- Schema tidak merepresentasikan status rencana (`PLANNED`) atau `PENDING`; status model `MISSING` tidak sama dengan status job.
- Sumber tidak menyediakan path/hash/time metadata dataset. `dataset_rows` dan `dataset_status` saja tidak cukup untuk membuat `datasets` yang valid dan dapat ditelusuri.
- Sumber log merupakan prefill (`PREP-*`), bukan bukti bahwa run/checkpoint telah dijalankan.
- Karena mapping belum disepakati, idempotency serta rollback import belum tervalidasi.

## 15. Recommended next steps

1. Tetapkan kebijakan eksplisit untuk memodelkan plan: tambahkan keadaan `PLANNED` melalui perubahan schema terpisah, atau putuskan secara tertulis kondisi apa yang boleh menjadi `QUEUED`. Jangan mengonversi `MISSING`/`PENDING` otomatis.
2. Tetapkan kebijakan untuk 10 job global, terutama apakah `EURUSD+XAUUSD` disimpan sebagai simbol komposit atau dipecah menjadi hubungan ke dua dataset.
3. Sediakan/konfirmasi path dataset persis dan format metadata yang dibutuhkan `datasets` serta `training_job_datasets`.
4. Tentukan kontrak penyimpanan untuk metadata plan (misalnya konfigurasi JSON berversi) dan makna `PREP-*`.
5. Setelah keputusan tersebut, ulangi mapping dan rekonsiliasi, lalu jalankan import/idempotency/rollback hanya pada clone baru.

**Keputusan tahap:** **BLOCKED**. Tidak siap untuk migrasi produksi. Proses berhenti sebelum INSERT, sesuai guardrail; tunggu keputusan pemetaan sebelum melanjutkan.
