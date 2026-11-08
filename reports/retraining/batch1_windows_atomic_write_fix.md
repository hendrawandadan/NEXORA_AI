# NEXORA AI v2 — Windows Atomic Write Fix

## Ringkasan Masalah

Error aktual:

`PermissionError: [WinError 5] Access is denied`

Lokasi error: `batch_checkpoint_manager.py` pada atomic replace file CSV ketika `ensure_schema(log_path)` dipanggil.

## 1) Audit Akar Penyebab

### Temuan pada batch_checkpoint_manager.py

- Fungsi `ensure_schema()` sebelumnya selalu menulis ulang CSV meskipun hanya untuk operasi baca.
- Fungsi `write_csv_rows()` sebelumnya memakai `Path(temp_name).replace(csv_path)` tanpa retry khusus Windows lock.
- Jika file CSV sedang dibuka editor/proses lain, replace memicu `WinError 5`.

### Temuan pada batch1_execution_runner.py

- Mode dry-run memanggil jalur baca yang sebelumnya melewati `ensure_schema()` write-path.
- Akibatnya dry-run bisa memicu write tak sengaja ke log produksi.

### Temuan pada batch_execution_log.csv

- Log produksi sudah memiliki kolom checkpoint lengkap, jadi dry-run seharusnya cukup read-only.

## 2) Perbaikan yang Dilakukan

### A. `batch_checkpoint_manager.py`

1. **Atomic write Windows-safe**
   - `write_csv_rows()` kini:
     - membuat temp file di direktori yang sama,
     - menutup handle temp file sebelum replace,
     - memakai `os.replace(...)`,
     - retry terbatas (`max_retries`, `retry_delay_seconds`) untuk lock sementara,
     - memberi pesan error jelas jika lock berlanjut,
     - menjaga file CSV asli tetap utuh saat gagal,
     - membersihkan temp file secara aman (best effort).

2. **Schema migration tidak otomatis pada read path**
   - `ensure_schema()` ditambah parameter:
     - `write_if_changed` (default true)
     - `strict` (default false)
   - Dalam mode `strict=True`, jika schema tidak sinkron maka error eksplisit meminta migrasi manual.

3. **Pemanggilan internal disesuaikan**
   - Operasi update/validasi/resume memakai `ensure_schema(..., write_if_changed=False, strict=True)`.
   - Migrasi schema hanya lewat perintah eksplisit `init-schema`.

### B. `batch1_execution_runner.py`

1. **Dry-run benar-benar read-only**
   - Jalur baca log memverifikasi schema strict tanpa write.
   - Tanpa `--execute`, runner tidak melakukan perubahan checkpoint/log/artifact.

2. **Safety gate schema**
   - Jika schema belum sesuai, runner berhenti dengan pesan migrasi eksplisit:
   - `batch_checkpoint_manager.py init-schema --log <path>`

3. **Self-test diperluas untuk Windows lock scenario**
   - Uji lock file, retry setelah unlock, preservasi CSV saat gagal replace, dan no-training assertion.

## 3) Validasi Pengujian

Pengujian dijalankan tanpa training produksi, tanpa `--execute`, dan tanpa menjalankan Batch 1 nyata.

### Hasil per test

1. Dry-run tidak mengubah hash CSV produksi -> **PASS**
2. CSV terkunci menghasilkan pesan error jelas -> **PASS**
3. Replace berhasil saat lock dilepas -> **PASS**
4. Gagal replace tidak merusak CSV asli -> **PASS**
5. Resume tidak mengulang run `PROMOTED` -> **PASS**
6. Tidak ada perubahan model produksi -> **PASS**
7. Tidak ada training berjalan selama pengujian -> **PASS**

## 4) Dampak Operasional

- Error `WinError 5` pada operasi baca/dry-run sudah dimitigasi.
- Migrasi schema kini eksplisit dan terkontrol.
- Atomic write lebih aman terhadap lock transient di Windows.
- Integritas CSV produksi dipertahankan saat replace gagal.

## 5) Referensi Artefak

- Script manager: `batch_checkpoint_manager.py`
- Script runner: `batch1_execution_runner.py`
- Usage: `reports/retraining/batch1_runner_usage.md`
- Validation: `reports/retraining/batch1_runner_validation.md`
- Self-test output: `reports/retraining/simulations/batch1_runner_validation/runner_self_test_result.json`

## Kesimpulan

Status akhir perbaikan Windows atomic write: **PASS**.
