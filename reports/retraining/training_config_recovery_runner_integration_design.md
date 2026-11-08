# NEXORA AI v2 — Training Config Recovery & Runner Integration Design

Tanggal audit: 2026-11-07  
Hasil keseluruhan: **BLOCKED untuk training; runner integration belum siap.**

## 1. Executive summary

Audit source menemukan konfigurasi current code dan dataset PREP-001, tetapi tidak menemukan training_config historis di execution log atau artefak PREP-001 aktual. PREP-001 tetap placeholder. Nilai max_iter=300 terbukti sebagai source target saat ini, tidak sebagai hasil run historis.

Empat tes integrasi fixture baru lulus sebagai reference adapter harness; suite SQLite schema v3/Foundation/integration/bootstrap keseluruhan **41 passed**. Tes tidak memanggil train_one dan tidak menjalankan model fit. Pemeriksaan tambahan terhadap repository saat ini mengungkap:
- claim run kedua dapat berhasil untuk job yang sama saat job sudah RUNNING (dibuktikan dengan fixture baru);
- append_checkpoint memperbarui training_runs/checkpoints/audit, tetapi tidak menyinkronkan training_jobs;
- explicit queue dan pembuatan queued run adalah pemanggilan repository terpisah, bukan satu transaksi.

Dry-run PREP-001 read-only lulus semua pemeriksaan teknis yang diperbolehkan: job masih PLANNED, dataset hash cocok dengan record clone, schema 3/integrity/FK baik, output belum ada, clone hash sebelum/sesudah sama. Dry-run tidak membuktikan training config lengkap ataupun runner readiness.

Tidak ada perubahan pada runner produksi, database produksi, baseline simulation clone, CSV, dataset, model atau backup. Hanya test harness baru ditambahkan; tes menggunakan database temporary fixture dan dummy file.

## 2. Configuration recovery

Rincian parameter, status FOUND/PARTIAL/MISSING/CONFLICT, matriks semua 37 tuple, dan PREP-001 ada di reports/retraining/training_configuration_recovery_report.md.

Ringkasan:
- 37 job individual: semua tuple EURUSD/timeframe/horizon terkonfirmasi; seluruh run config legacy kosong.
- max_iter=300: FOUND sebagai nilai target config aktif (research.json:23), diperiksa runner (batch1_execution_runner.py:636–637), dan didukung dokumen pre-execution. Tidak ada bukti PREP-001 pernah berjalan pada 300.
- Effective model belum deterministik: engine auto; LightGBM 4.7.0 terpasang saat audit, tetapi requirements hanya lightgbm>=4.0 dan fallback sklearn memiliki semantics berbeda.
- Objective binary muncul dari default LightGBM runtime, bukan argumen explicit pada code. max_depth juga menggunakan library default. Konfigurasi ini belum dikunci per job.
- Artefak simulation PREP-001 memuat dummy_engine/max_iter 1200 dan jelas diberi status simulated; bukan bukti historis.

## 3. PREP-001 audit dan dry-run result

Tuple: EURUSD M30 H2, legacy ref PREP-001.

Dry-run memeriksa saja:
| Check | Hasil aktual |
|---|---|
| Legacy tuple plan/log match | PASS |
| Legacy start/end/config kosong, tidak salah dianggap run aktual | PASS |
| Dataset file exists | PASS |
| Recomputed SHA-256 versus clone dataset record | PASS |
| Bar count/date metadata | PASS — 70,694 bars, 2020-01-02 00:00:00 hingga 2026-11-06 21:30:00 |
| Dataset interval/structure manifest | PASS — interval PASS, quality error counts 0; 3,660 gaps dicatat |
| Job di clone | PASS — PLANNED |
| Clone schema/integrity/FK | PASS — v3, integrity ok, FK violations 0 |
| Config horizon/positive max_iter/fractions | PASS — horizon 2, max_iter 300, 0.6/0.2, embargo 24 |
| Output target paths | PASS untuk pemeriksaan dry-run — path dihitung, semuanya belum ada |
| Clone hash sebelum/sesudah dry-run | IDENTIK — 419e7c5a92b97160042f50c4d80e92a56fd00708688c290ba7c1dc14ca7e8a06 |

Dry-run tidak membuka runner execute, tidak mengubah status, tidak membuat file output, dan tidak memanggil trainer. Result status **PASS untuk pemeriksaan dry-run read-only**, bukan clearance untuk training.

PREP-001 masih BLOCKED: tidak memiliki frozen effective config, engine/objective/max_depth belum explicit, dan keputusan waktu eksekusi relatif terhadap candle close serta leakage validation belum diformalisasi.

## 4. Runner integration architecture

Runner saat ini (batch1_execution_runner.py) membaca plan/log CSV, memakai transition_status/write_log_rows, memanggil run_production_pipeline_to_staging -> train_one, lalu promotion ke filesystem; SQLite belum menjadi source of truth. Jangan hubungkan runner lama ke 37 job PLANNED secara langsung.

Desain adapter:
1. **Queue:** API explicit queue(actor, job_id, frozen_config_hash) dalam satu BEGIN IMMEDIATE: validasi PLANNED + dataset association/hash, buat run QUEUED, ubah job QUEUED, tulis audit. Rollback semua jika satu langkah gagal.
2. **Claim:** pilih hanya job QUEUED/RETRY_PENDING tanpa active run. Satu transaksi: run STARTED, checkpoint STARTED, audit claim, job RUNNING. Commit sebelum menjalankan proses training.
3. **Train:** panggil trainer hanya setelah commit, di staging root terisolasi; koneksi/transaction DB tidak ditahan selama kerja panjang.
4. **Transition:** satu operasi adapter atomik memperbarui run + job + checkpoint + audit. Map run STARTED→job RUNNING, TRAIN_DONE→TRAIN_DONE, VALIDATED→VALIDATED, PROMOTED→PROMOTED, FAILED→FAILED, RETRY_PENDING→RETRY_PENDING.
5. **Retry:** jangan jalankan dua attempt serentak. Tambah run_index baru dan simpan retry lineage (kolom retry_of_run_id di schema berikut atau audit payload) sebelum claim ulang.
6. **Terminal:** database triggers/repository menolak PROMOTED→PROMOTED maupun downgrade.
7. **Idempotency:** identitas queue/job unik; retry dan recovery punya key/attempt yang eksplisit.

Lifecycle:

| Job | Run/checkpoint | Keterangan |
|---|---|---|
| PLANNED | — | Non-runnable, tidak dapat diklaim |
| QUEUED | QUEUED | Hanya explicit queue dengan audit |
| RUNNING | STARTED | Atomic claim; training setelah transaksi selesai |
| TRAIN_DONE | TRAIN_DONE | Outputs staging terdaftar |
| VALIDATED | VALIDATED | Validation results harus lolos |
| PROMOTED | PROMOTED | Terminal |
| FAILED | FAILED | Audit error dan failure reason |
| RETRY_PENDING | RETRY_PENDING | Riwayat attempt lama dipertahankan; retry run baru |

Current repository findings:
- queue_planned_job() menulis audit dan mengubah job, sementara create_run() dipanggil terpisah; belum atomic queue+run.
- claim_next_queued_run() memakai BEGIN IMMEDIATE dan berhasil menghindari claim ganda pada satu run yang sama. Namun query saat ini hanya filter training_runs.status=QUEUED, bukan status job atau active run.
- Fixture probe: dua runs QUEUED pada satu job; claim pertama mengembalikan run 1, job RUNNING; claim kedua tetap mengembalikan run 2 dan menghasilkan dua runs STARTED. Ini melanggar one-active-attempt-per-job.
- SQLiteCheckpointRepository.append_checkpoint() mengubah run/checkpoint/audit tetapi tidak mengubah job status. Contoh: run berubah TRAIN_DONE sementara job dapat tetap RUNNING.
- Transaction helper menggunakan BEGIN IMMEDIATE, commit/rollback; adapter dapat menggunakannya, tetapi runner belum memakai.

Tidak ada runner/repository production integration yang diimplementasikan pada tahap ini. Tes reference harness bukan bukti bahwa batch runner lama sudah terintegrasi.

## 5. Artifact lifecycle design

File system dan SQLite bukan satu transaksi. Gunakan immutable/versioned artifact directory di staging dan manifest idempotent dengan phases:
1. STAGED: salin output ke staging; hitung SHA-256/size; catat artifact STAGED.
2. VALIDATED: verifikasi file/hash, schema, metadata tuple, report, dan validation_results passed; artifact tetap DB lifecycle STAGED karena schema v3 tidak punya status artifact VALIDATED.
3. PROMOTION_PREPARED: manifest menyimpan source/target paths, digest, run_id, artifact_id.
4. FILE_PROMOTED_DB_PENDING: atomic rename ke versioned path pada volume sama; manifest mencatat fase ini.
5. DB_COMMITTED: satu transaksi mengubah artifact ACTIVE, run/job/checkpoint PROMOTED, audit promotion.
6. PROMOTED: manifest difinalkan.
7. Recovery membaca manifest dan state DB, memverifikasi digest/path; lanjutkan DB commit jika file sudah berpindah, atau finalisasi manifest jika DB sudah commit. Konflik hash/path berhenti untuk rekonsiliasi manual; tidak overwrite model produksi.

Schema v3 saat ini memakai lifecycle STAGED/ACTIVE/RETIRED/DELETED; validation tersimpan dalam validation_results, bukan lifecycle_status=VALIDATED.

## 6. Isolated integration tests

File test baru: tests/test_sqlite_runner_integration_design.py. Tes memakai schema v3 fixture baru di tmp path, dummy trainer bytes dan temporary artifact; tidak mengimpor atau memanggil train_one.

Rangkaian SQLite terpilih yang dijalankan:
- test_sqlite_runner_integration_design.py
- test_sqlite_schema_v3.py
- test_sqlite_foundation.py
- test_sqlite_foundation_integration.py
- test_sqlite_production_bootstrap.py

Hasil final: **41 passed in 53.98s**.

Coverage fixture harness: explicit queue; PLANNED claim returns none; concurrent workers/no duplicate same run; checkpoint/audit/job state mapping; failure/retry history; dummy artifact staging and hash; validation gate; simulated crash after filesystem move and recovery before/after DB commit; PROMOTED terminal; audit failure rollback; DB reopen/integrity/FK. No test runs real training.

Caveat: four new tests exercise reference adapter logic in test harness, not production runner. Separate claim probe reproduced the two-active-runs bug in current repository; it remains unresolved.

## 7. Compatibility and safety

- batch_execution_runner.py and batch_checkpoint_manager.py tidak diubah.
- Production DB tetap v2; tidak ada bootstrap/migration production.
- Baseline simulation DB dibuka hanya read-only untuk dry-run; hash tetap sama.
- CSV/source config/dataset/model/backup tidak ditulis.
- Tidak ada runner --execute, train_one, model.fit, atau training dispatch.
- CSV runner saat ini tidak menggunakan PLANNED SQLite rows; setelah perubahan, integrasi harus adapter baru atau migrasi runner terpisah.

## 8. Risks and unresolved issues

- Historical run config 37 jobs tidak tersedia.
- Engine auto, LightGBM dependency unpinned, objective/max_depth implicit; current effective config belum reproducible.
- M30 dataset manifest mencatat 3,660 gaps; interpretasi sesi dan keterkaitan kalender harus disetujui.
- No formal split leakage test or decision-time contract; source inspection tidak menemukan direct target-as-feature leakage, tetapi timing/backtest safety belum terbukti.
- SQLite claim allows second run of an already RUNNING job; must fix before runner integration.
- Job status not updated by checkpoint repository transitions; adapter must synchronize it atomically.
- Queue and run creation are not currently one transaction.
- Artifact manifest/DB recovery code is only a design harness; production recovery implementation not present.

## 9. Recommended next action

1. Freeze a signed/hash-addressed config for PREP-001: explicit engine/version, objective, max_depth, all regularization, early stopping, feature/label/split versions.
2. Agree candle decision/execution timing and add deterministic leakage/purge tests plus cost-aware backtest requirements.
3. Close current repo gaps: active-run guard at claim; atomic queue+run create; run+job+checkpoint+audit synchronized transitions; retry lineage.
4. Implement and review a separate SQLite adapter; retain CSV runner unchanged until adapter passes end-to-end fixture tests.
5. Repeat dry-run against the frozen configuration, then wait for explicit approval before any training.

