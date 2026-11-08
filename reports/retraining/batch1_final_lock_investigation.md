# Batch 1 Final Lock Investigation (Windows)

## Scope & Guardrails

- Investigasi dilakukan di `D:/NEXORA_AI_v2`.
- Tidak menjalankan training (`--execute` tidak dipakai).
- Tidak mengubah model/dataset.
- Tidak mengubah `reports/retraining/batch_execution_log.csv`.
- Tidak menghapus backup.

## Ringkasan Temuan

Error nyata tetap terjadi pada transisi STARTED:

- `PREP-001: STARTED_LOG_PERMISSION_FAILED`
- `ABORTED: Execution log update failed before training dispatch`

Berdasarkan audit kode + diagnostik runtime, kegagalan berada pada fase atomic replace (`os.replace`) saat update CSV, bukan pada dispatch training.

## 1) Audit Pembukaan File `batch_execution_log.csv`

### Jalur baca/tulis utama

- `read_csv_rows(...)` di `batch_checkpoint_manager.py` membuka file dengan context manager (`with`) dan menutup handle otomatis.
- `write_csv_rows(...)` membuat temp file dengan `NamedTemporaryFile(..., delete=False, dir=same_dir)` dan handle ditutup sebelum `os.replace(...)`.
- `update_log_row(...)` dan `transition_status(...)` di `batch1_execution_runner.py` melakukan read-modify-write di dalam `acquire_execution_log_lock(...)`.
- `apply_update(...)` di `batch_checkpoint_manager.py` juga di dalam lock yang sama.

### Hasil audit handle lifecycle

- Tidak ditemukan handle leak eksplisit di jalur normal.
- Exception path tetap menutup handle lock file melalui `finally` di `acquire_execution_log_lock(...)`.
- Exception path `write_csv_rows(...)` juga membersihkan temp file bila aman.

Status: **PASS** (tidak ada bukti handle tidak tertutup dari kode sendiri).

## 2) Diagnostik Tambahan sebelum `os.replace()` gagal

Perubahan diagnostik ditambahkan di `batch_checkpoint_manager.py`:

- `list_locking_processes_windows(...)` memakai Windows Restart Manager API.
- `diagnose_log_write_failure(...)` sekarang mencatat:
  - `reason`, `details`, `errno`, `winerror`
  - path target/temp
  - status writer-lock internal
  - daftar proses lock-holder (jika terdeteksi)
- Snapshot kegagalan ditulis ke JSON:
  - `reports/retraining/**/diagnostics/csv_replace_failure_*.json`

Klasifikasi error dibedakan:

- `sharing_violation` (umumnya `winerror=32`)
- `acl_denied`
- `locked_by_runner`
- `locked_by_external_process`
- `antivirus_interference`
- `access_denied`
- `permission_unknown`

Status: **PASS**.

## 3) Bukti Diagnostik Runtime

### A. Snapshot lock untuk CSV produksi (read-only)

File bukti:

- `reports/retraining/diagnostics/production_lock_snapshot.json`

Hasil snapshot:

- `target_exists=true`
- `target_writable=true`
- `writer_lock_held=false`
- `locking_processes=[]`
- `relevant_processes=[]`

Interpretasi:

- Saat snapshot diambil, tidak ada lock-holder yang terdeteksi pada CSV produksi.
- Ini konsisten dengan lock yang bersifat intermiten/transient.

Status: **WARNING** (snapshot tunggal tidak membuktikan kondisi saat kegagalan real berlangsung).

### B. Bukti kegagalan replace dengan diagnostik detail

File bukti:

- `reports/retraining/simulations/batch1_runner_validation/diagnostics/csv_replace_failure_20261107_130436.json`

Isi penting:

- `winerror=5`, `errno=13`
- `reason=access_denied`
- `writer_lock_held=false`
- `locking_processes=[]`

Interpretasi:

- Access denied dapat terjadi walau lock-holder tidak tertangkap oleh Restart Manager (contoh: lock sangat singkat, filter driver, atau mekanisme non-file-handle klasik).

Status: **PASS** untuk kualitas bukti diagnostik; **WARNING** untuk atribusi proses spesifik.

## 4) Verifikasi Proses Gagal Tetap Aman

Self-test runner terbaru menunjukkan:

- `integration_started_log_failure_blocks_training=true`
- `integration_started_failure_status_unchanged=true`
- `training_executed=false`

Artinya:

- Jika logging STARTED gagal, training tidak dipanggil.
- Status PREP tidak berubah ambigu.

Status: **PASS**.

## 5) Proses yang perlu diawasi

Berdasarkan requirement, investigasi mengawasi potensi:

- Codex / Python / VS Code
- Dropbox sync
- Antivirus (mis. Defender `MsMpEng.exe`)

Pada snapshot yang terekam, tidak ada proses relevan yang sedang memegang target. Ini tidak menutup kemungkinan proses-proses tersebut memegang file secara sesaat pada waktu berbeda.

Status: **WARNING** (butuh capture saat failure real-time untuk identifikasi PID definitif).

## 6) Evaluasi desain: CSV RMW vs SQLite transaksi

### Risiko model CSV read-modify-write (saat ini)

- Rentan race/transient lock pada replace, terutama di Windows.
- Sulit menjamin konsistensi bila ada tool eksternal (editor/indexer/AV/sync).
- Diagnostik bisa kaya, tetapi recovery tetap berbasis file-level replace.

### Rekomendasi

Pertimbangkan migrasi state eksekusi ke SQLite (WAL mode) untuk jalur transaksi utama, dengan CSV dipertahankan sebagai export/report.

### Rencana kompatibilitas (tanpa migrasi langsung sekarang)

1. Tambah storage abstraction (`ExecutionStateStore`) dengan backend CSV (eksisting) + SQLite (baru).
2. Jalankan dual-write fase transisi (opsional, feature-flag).
3. Validasi parity data (`row_count`, checksum per run-id, status monotonic).
4. Jadikan SQLite sebagai source of truth setelah parity stabil.
5. CSV menjadi output sink periodik/read-only export.

### Risiko migrasi

- Perlu migrasi schema + tooling audit baru.
- Perlu fallback plan jika DB file korup (backup/PRAGMA integrity_check).
- Perlu update SOP operasional dan observability.

Kesimpulan desain: **READY FOR DESIGN PHASE**, belum untuk eksekusi migrasi langsung di langkah ini.

## Kesimpulan Akhir

- Penyebab fungsional tetap pada kegagalan `os.replace` saat update execution log di Windows.
- Tidak ditemukan bukti bahwa kode runner/checkpoint meninggalkan file handle terbuka.
- Lock/interference kemungkinan besar bersifat intermiten dan tidak selalu tertangkap snapshot manual.
- Guardrail berhasil: training tidak jalan jika STARTED gagal.

Status keseluruhan investigasi: **WARNING**

Alasan WARNING:

- Diagnostik sudah kuat dan aman, tetapi proses pengunci spesifik pada momen kegagalan real belum teridentifikasi secara deterministik.
