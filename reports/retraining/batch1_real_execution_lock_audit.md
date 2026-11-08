# Batch 1 Real Execution Lock Audit

## Tujuan

Investigasi kegagalan eksekusi nyata Batch 1:

- Error: `PermissionError: [WinError 5] Atomic replace failed after 5 attempts`
- Lokasi: `reports/retraining/batch_execution_log.csv`
- Titik gagal: `process_run()` -> `transition_status("STARTED")` -> `update_log_row()` -> `write_csv_rows()`

Audit ini **tidak menjalankan training nyata** dan **tidak menjalankan Batch 1 produksi**.

## A. Hasil Audit Root Cause

### 1) Penyebab paling mungkin dari failure aktual

Kegagalan terjadi saat atomic replace file CSV di Windows (`os.replace`) ketika file sedang dipegang handle lain (runner lain, editor/spreadsheet viewer, AV/indexer, atau proses eksternal lain).

Dry-run berhasil karena mode dry-run tidak menulis execution log.

### 2) Risiko yang ditemukan sebelum perbaikan

- Potensi dua proses runner melakukan read-modify-write bersamaan.
- Retry replace saja tidak cukup jika lock tetap aktif.
- Diagnostik belum cukup eksplisit untuk membedakan penyebab lock vs permission.

## B. Perbaikan Mekanisme Lock dan Write

### 1) Single-writer coordination (Windows)

Di `batch_checkpoint_manager.py`:

- Ditambahkan `ExecutionLogLockError`.
- Ditambahkan `acquire_execution_log_lock(...)` berbasis `msvcrt.locking` dengan sidecar lock file `*.writer.lock`.
- `apply_update(...)` dibungkus lock write agar read-modify-write atomik antarpengguna.
- `init-schema` write path juga dibungkus lock agar migrasi tidak bentrok dengan runner aktif.

Di `batch1_execution_runner.py`:

- `transition_status(...)` dibungkus lock yang sama.
- `update_log_row(...)` dibungkus lock yang sama.
- Ditambahkan argumen CLI:
  - `--log-lock-timeout-seconds`
  - `--log-lock-poll-seconds`

### 2) Atomic write kompatibel Windows

`write_csv_rows(...)` sekarang:

- menulis temp file di direktori yang sama,
- menutup handle temp file sebelum replace,
- melakukan `os.replace` dengan retry terbatas,
- mengembalikan error terdiagnosis jika gagal,
- tidak menghapus file target,
- menjaga file CSV asli tetap utuh saat gagal.

### 3) Diagnostik kegagalan

`diagnose_log_write_failure(...)` membedakan kategori:

- `locked_or_busy`
- `acl_denied`
- `external_interference`
- `target_missing`
- `permission_unknown`

## C. Bukti Training Tidak Berjalan saat STARTED Logging Gagal

Dari self-test integrasi (`runner_self_test_result.json`):

- `integration_started_log_failure_blocks_training = true`
- `integration_started_failure_status_unchanged = true`
- `integration_started_result = PREP-001: STARTED_LOG_PERMISSION_FAILED (reason=locked_or_busy ...)`
- `training_executed = false`

Makna operasional:

1. Saat logging `STARTED` gagal, training pipeline tidak dipanggil.
2. Status checkpoint run tetap `QUEUED` (tidak ambigu/half-state).
3. Runner melakukan abort terkontrol sebelum dispatch training.

## D. Hasil Pengujian (PASS/FAIL)

1. Dry-run hash CSV tidak berubah -> **PASS**
2. Lock menghasilkan pesan error jelas -> **PASS**
3. Replace berhasil setelah lock dilepas -> **PASS**
4. Gagal replace tidak merusak CSV asli -> **PASS**
5. Resume tidak mengulang `PROMOTED` -> **PASS**
6. Logging `STARTED` gagal menghentikan training sebelum dispatch -> **PASS**
7. Status run tetap jelas setelah gagal logging -> **PASS**
8. Tidak ada perubahan model produksi saat pengujian -> **PASS**
9. Tidak ada training nyata dijalankan -> **PASS**

## E. Konsistensi Mekanisme antar Komponen

- `batch_checkpoint_manager.py` dan `batch1_execution_runner.py` sudah menggunakan mekanisme penulisan log yang konsisten:
  - lock coordination sama,
  - read-modify-write terproteksi,
  - atomic write path sama,
  - resume menghormati status `PROMOTED`.

## F. Rekomendasi Operasional

1. Pastikan hanya satu runner produksi aktif untuk satu execution log.
2. Hindari membuka `batch_execution_log.csv` di aplikasi spreadsheet/editor saat execute.
3. Jika muncul `locked_or_busy`, hentikan proses eksternal yang memegang file lalu ulangi run.
4. Jalankan execute bertahap (`--limit`) untuk observabilitas dan recovery yang lebih aman.

## Kesimpulan

Status audit: **PASS**

Kegagalan `WinError 5` pada update `STARTED` berhasil direproduksi dalam skenario lock dan sudah ditangani dengan guardrail yang mencegah training berjalan saat logging gagal. Integritas log dan model lama tetap aman.
