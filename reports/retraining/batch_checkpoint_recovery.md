# NEXORA Batch 1 Checkpoint Recovery Guide

Dokumen ini menjelaskan cara melanjutkan eksekusi Batch 1 tanpa mengulang run yang sudah valid, dengan jaminan model lama tidak tertimpa sebelum model baru lulus validasi.

## 1) Status & Arti

- `QUEUED`: run belum dimulai.
- `STARTED`: proses training run dimulai, `start_time` wajib terisi.
- `TRAIN_DONE`: proses train selesai, artefak kandidat sudah ada di staging.
- `VALIDATED`: metadata kandidat cocok (`scope/symbol/timeframe/horizon/training_config`).
- `PROMOTED`: artefak kandidat dipindah atomik ke lokasi final, run selesai.
- `FAILED`: run gagal pada checkpoint saat ini, `error_message` terisi.
- `RETRY_PENDING`: run dijadwalkan retry, menunggu transisi ulang ke `STARTED`.

## 2) Aturan Resume Otomatis

1. Baca [batch_execution_log.csv](./batch_execution_log.csv) saat startup.
2. Lewati semua run `checkpoint_status=PROMOTED`.
3. Lanjutkan run non-terminal sesuai urutan `execution_id`/planner.
4. Jangan downgrade status `PROMOTED` ke status lain.
5. Jika status `FAILED`, pindah ke `RETRY_PENDING`, lalu lanjut ke `STARTED`.

## 3) Anti-Overwrite Guarantee

- Output training wajib ditulis dulu ke path `temp_*`.
- Validasi metadata wajib `PASS` sebelum `PROMOTED`.
- Promosi menggunakan rename atomik (`Path.replace`) dari `temp_*` ke `final_*`.
- Jika path final sudah ada, promosi ditolak (`FileExistsError`) agar model lama tetap aman.

## 4) Kolom Kritis di Log

Kolom berikut wajib sinkron setiap transisi:

- Identitas run: `execution_id`, `run_id`, `batch`, `scope`, `symbol`, `timeframe`, `horizon`
- Status: `run_status`, `checkpoint_status`, `last_checkpoint`, `checkpoint_updated_at`
- Waktu: `start_time`, `end_time`
- Artefak kandidat: `temp_model_path`, `temp_report_path`, `temp_signals_path`, `temp_metadata_path`
- Artefak final: `final_model_path`, `final_report_path`, `final_signals_path`, `final_metadata_path`
- Validasi: `metadata_match`, `config_match`, `artifact_sync`, `error_message`, `retry_count`

## 5) Prosedur Operasional Aman

1. Jalankan validasi duplikasi key run.
2. Ambil daftar run resumable (non-promoted).
3. Jalankan setiap run dari checkpoint terakhirnya.
4. Setelah tiap transisi, tulis log langsung ke disk.
5. Stop jika mismatch metadata/config atau artefak kandidat hilang.

## 6) Command Referensi

```powershell
.venv\Scripts\python.exe batch_checkpoint_manager.py init-schema --log reports/retraining/batch_execution_log.csv
.venv\Scripts\python.exe batch_checkpoint_manager.py validate --log reports/retraining/batch_execution_log.csv
.venv\Scripts\python.exe batch_checkpoint_manager.py next --log reports/retraining/batch_execution_log.csv --batch "Batch 1" --limit 20
```

## 7) Batasan Keamanan

- Dokumen ini tidak menjalankan training.
- Tidak mengubah source code training/model produksi.
- Tidak menghapus backup yang sudah diverifikasi.
- Tidak menimpa model lama sebelum validasi berhasil.
