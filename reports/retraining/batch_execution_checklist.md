# NEXORA Batch Execution Checklist (Safe Resume Mode)

Dokumen ini memastikan eksekusi retraining berjalan aman, bisa di-resume, dan terverifikasi tanpa menimpa model valid secara prematur.

## 1) Pre-Execution Safety Gate (Wajib sebelum mulai)

- [ ] Konfirmasi plan sumber: `reports/retraining/batch_retraining_plan.csv`
- [ ] Konfirmasi scope run (Batch 1 / Batch 2 / Batch 3) dan checkpoint group (`batch::timeframe`).
- [ ] Konfirmasi tidak ada perubahan kode/config sejak audit terakhir.
- [ ] Buat folder backup timestamp, contoh:
  - `backups/pre_run_YYYYMMDD_HHMM/`
- [ ] Backup artefak aktif:
  - [models/](D:/NEXORA_AI_v2/models)
  - [reports/](D:/NEXORA_AI_v2/reports)
  - [signals/](D:/NEXORA_AI_v2/signals)
- [ ] Simpan checksum/manifest backup (daftar file + ukuran + modified time).

## 2) Anti-Overwrite Rule (Model lama tidak boleh tertimpa)

- [ ] Jalankan training ke **staging output** terlebih dahulu (workspace terpisah), bukan langsung replace artefak aktif.
- [ ] Untuk setiap kombinasi run `(scope, symbol, timeframe, horizon)`:
  - [ ] Simpan output sementara sebagai candidate (`candidate_model`, `candidate_report`, `candidate_signals`).
  - [ ] Validasi candidate lengkap sebelum promote.
- [ ] Promote ke artefak aktif hanya jika semua validasi lulus.
- [ ] Jika validasi gagal, pertahankan artefak lama (rollback by design).

## 3) Run-Level Checkpointing (setiap run wajib punya checkpoint)

Status checkpoint per run (satu baris per kombinasi):

1. `QUEUED`
2. `STARTED`
3. `TRAIN_DONE`
4. `ARTIFACT_WRITTEN`
5. `VALIDATED`
6. `PROMOTED`
7. `RECORDED`

- [ ] Tulis status checkpoint ke log setelah setiap tahap.
- [ ] Sertakan timestamp, batch, timeframe, horizon, dan hash/versi artefak.
- [ ] Jangan lanjut ke run berikutnya sebelum status minimal `VALIDATED` untuk run saat ini.

## 4) Resume Rule (jika proses terhenti)

- [ ] Saat restart, baca log checkpoint terakhir.
- [ ] Untuk setiap run:
  - Jika status `PROMOTED` + validasi sinkron => **SKIP** (jangan ulang).
  - Jika status sampai `TRAIN_DONE` tapi belum validasi => lanjut dari validasi/artifact check.
  - Jika status tidak konsisten/korup => tandai `INVESTIGATE`, jangan auto-overwrite.
- [ ] Lanjutkan berdasarkan urutan `batch::timeframe` dari plan.

## 5) Sinkronisasi Report ↔ Model ↔ Metadata (wajib pass)

Untuk setiap run candidate maupun promoted:

- [ ] `report.json` ada dan parseable.
- [ ] `model.joblib` ada dan loadable.
- [ ] Metadata cocok:
  - `symbol`
  - `timeframe`
  - `horizon`
  - `kind/scope`
  - `engine`
- [ ] Jumlah row split masuk akal (`train_rows`, `validation_rows`, `test_rows` > 0 sesuai rule).
- [ ] Path dan key run cocok dengan plan (`scope,symbol,timeframe,horizon`).
- [ ] Tidak ada duplikasi key run baru.

## 6) Batch Completion Gate (wajib sebelum pindah batch)

- [ ] Semua run target batch berstatus `PROMOTED` atau `SKIPPED_VALID`.
- [ ] Tidak ada run `INVALID`/`INCOMPLETE` yang belum diinvestigasi.
- [ ] Rekap batch disimpan:
  - total target
  - sukses
  - skip
  - gagal
  - investigasi
- [ ] Update laporan ringkas batch di:
  - `reports/retraining/batch_execution_log.csv`
  - `reports/retraining/batch_execution_summary.md`

## 7) Post-Execution Validation (akhir seluruh batch)

- [ ] Jalankan ulang audit coverage matrix (tanpa retrain) untuk memastikan gap tertutup.
- [ ] Verifikasi persamaan coverage terbaru.
- [ ] Verifikasi tidak ada orphan artifact baru.
- [ ] Verifikasi tidak ada mismatch report-model-metadata.
- [ ] Buat snapshot final dan changelog eksekusi.

## 8) Stop Conditions (harus berhenti otomatis)

Hentikan eksekusi jika salah satu terjadi:

- [ ] Metadata mismatch pada candidate.
- [ ] Model/report tidak bisa dibaca.
- [ ] Key run bentrok/duplikat.
- [ ] Output candidate menimpa artefak aktif sebelum validasi.
- [ ] Kegagalan berulang pada checkpoint yang sama >= 3 kali.

---

## Template keputusan per run

- `SKIPPED_VALID`: run sudah ada, valid, sinkron.
- `TRAINED_NEW_VALID`: run baru lulus validasi dan dipromote.
- `FAILED_RETRYABLE`: gagal sementara, bisa ulang.
- `FAILED_INVESTIGATE`: gagal struktural, perlu investigasi manual.

Gunakan template log CSV: `reports/retraining/batch_execution_log.csv`.
