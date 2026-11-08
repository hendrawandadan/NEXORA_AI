# NEXORA Batch 1 Runner Usage

Dokumen ini menjelaskan cara memakai template runner Batch 1 tanpa mengubah algoritma training produksi.

## 1) Entry Point Training Produksi

Runner menggunakan pipeline produksi yang sudah ada:

- `nexora_learning.pipeline.train_one(...)` untuk individual training.
- `config/research.json` sebagai sumber konfigurasi aktual.
- `training.max_iter=300` dipaksa sebagai syarat full training.

Runner **tidak** membuat ulang algoritma training; runner hanya mengorkestrasi dispatch checkpoint, validasi artefak, dan promosi aman.

## 2) Mode Eksekusi

- Default: **dry-run** (tanpa `--execute`, training tidak akan jalan).
- `--validate-only`: hanya validasi/promotion flow dari checkpoint yang sudah ada.
- `--resume`: skip `PROMOTED` permanen dan lanjut dari checkpoint terakhir.
- `--limit N`: batasi jumlah run.
- `--execute`: izin eksplisit menjalankan training sungguhan.
- `--log-lock-timeout-seconds`: batas tunggu lock writer log (default `15.0`).
- `--log-lock-poll-seconds`: interval polling lock log (default `0.15`).

### Aturan dry-run (READ-ONLY)

Tanpa `--execute`, runner selalu dry-run dan **tidak boleh**:

- mengubah `batch_execution_log.csv`,
- menambah kolom schema,
- mengubah checkpoint,
- membuat/promotion model,
- membuat manifest produksi.

Jika schema log belum sesuai, runner akan berhenti dengan error jelas dan meminta migrasi eksplisit:

```powershell
.venv\Scripts\python.exe batch_checkpoint_manager.py init-schema --log reports/retraining/batch_execution_log.csv
```

## 3) Dispatch Checkpoint

Status dispatch:

- `QUEUED` -> `STARTED` -> train (jika `--execute`) -> `TRAIN_DONE`
- `STARTED` -> cek artefak staging, lanjut `TRAIN_DONE` jika lengkap
- `TRAIN_DONE` -> validasi model/report/signals/metadata -> `VALIDATED`
- `VALIDATED` -> promosi atomik + rollback parsial -> `PROMOTED`
- `FAILED` -> stop, tidak auto retry
- `RETRY_PENDING` -> retry terkendali ke `STARTED` (hanya saat `--execute`)
- `PROMOTED` -> skip permanen

Jika update checkpoint `STARTED` gagal (lock/permission), runner abort sebelum dispatch training pipeline.

## 4) Single-Writer Lock dan Diagnostik

- Semua operasi read-modify-write ke execution log menggunakan writer lock sidecar: `batch_execution_log.csv.writer.lock`.
- Hanya satu proses runner yang dapat menulis log pada satu waktu.
- `transition_status(...)` dan `update_log_row(...)` memakai mekanisme lock yang sama.
- Diagnostik kegagalan write membedakan kategori utama:
  - `locked_or_busy`: file sedang dikunci proses lain/editor/eksternal scanner.
  - `acl_denied`: izin OS/ACL menolak write.
  - `external_interference`: `WinError 5` saat replace (indikasi gangguan handle eksternal).

## 5) Safety Rules

- Training output ditulis ke staging dahulu.
- Hash + manifest dibuat sebelum promosi.
- Metadata diverifikasi terhadap `symbol/timeframe/horizon/config`.
- Promosi menggunakan transaksi copy+replace per file dengan rollback jika gagal parsial.
- Backup lama dan model lama tidak dihapus oleh runner.
- Penulisan CSV menggunakan atomic write kompatibel Windows (retry terbatas saat file lock, tanpa menghapus file target).

## 6) Contoh Perintah

Preview 5 run pertama (aman, default dry-run):

```powershell
.venv\Scripts\python.exe batch1_execution_runner.py --resume --limit 5
```

Validasi-only 5 run pertama (tanpa training baru):

```powershell
.venv\Scripts\python.exe batch1_execution_runner.py --resume --validate-only --limit 5
```

Eksekusi nyata 5 run pertama (hanya saat siap production run):

```powershell
.venv\Scripts\python.exe batch1_execution_runner.py --execute --resume --limit 5 --log-lock-timeout-seconds 30 --log-lock-poll-seconds 0.2
```

## 7) Catatan Penting

- Jangan jalankan Batch 3 global dari runner ini.
- Runner ini fokus Batch 1 individual EURUSD.
- Pastikan backup Batch 1 yang sudah diverifikasi tetap tersedia sebelum `--execute`.
