# NEXORA AI v2 — SQLite Schema v3 Design Report

Tanggal: 2026-11-07

## Hasil akhir: PASS

Schema v3 migration dan lifecycle rules lulus pada database uji, termasuk upgrade dari schema v2 dengan data child tables, rollback fault-injection, checksum mismatch, idempotency, PLANNED queue guard, atomic claim, retry, dan terminal PROMOTED.

Database produksi tidak dimigrasikan. Read-only verification setelah tes:
- schema_migrations versions: 1, 2
- integrity_check: ok
- foreign_key_check: 0 pelanggaran
- SHA-256: E314244ED46099ABD0025E982640B9BE7711F608AC9A75FF5B44E4D43286D6C6

Tidak ada CSV, dataset, model, atau backup yang diubah. Tidak ada training atau job import.

## 1. Audit schema v2

Objek yang ditinjau: training_jobs, training_runs, checkpoints, audit_logs, training_job_datasets, model_artifacts, schema_migrations, migration SQL 001–002, constants.py, repositories.py, interfaces.py, bootstrap.py, production_bootstrap.py, batch_execution_runner.py, dan batch_checkpoint_manager.py.

Schema v2 memakai CHECK status pada job/run/checkpoint, foreign keys untuk job-run-checkpoint/artifact/dataset, serta checksum per migration di schema_migrations. Transition logic aplikasi ada di constants.py dan SQLiteCheckpointRepository.append_checkpoint; PROMOTED terminal pada repository. Claim run di SQLiteTrainingRunRepository mengubah run STARTED, menulis checkpoint/audit, lalu job RUNNING dalam satu BEGIN IMMEDIATE. Migration 002 merebuild training_jobs; migration v3 mengulang rebuild dengan perlindungan child rows yang eksplisit.

## 2. Schema v3 design dan migration SQL

Migration baru: nexora_state_db/migrations/003__planned_job_lifecycle.sql  
SHA-256 migration SQL: A4B0E80F6EC19195995D08A14AAEC365C2DA1140BB660FDE821DC0F09F387605

training_jobs menerima PLANNED selain status operasional yang ada. Kolom tambahan:
- legacy_status, legacy_action, legacy_reference, legacy_source
- migration_source_hash dengan CHECK 64 karakter saat tidak NULL
- queued_at, queued_by

Migration mempertahankan status STARTED yang mungkin sudah tersimpan dari v2 demi kompatibilitas data. STARTED job lama hanya boleh melanjutkan ke TRAIN_DONE atau FAILED; tidak menjadi status baru untuk rencana.

SQL inti migration:

    CREATE TABLE training_jobs_new (
      ...,
      status TEXT NOT NULL DEFAULT 'PLANNED'
        CHECK(status IN ('PLANNED','QUEUED','RUNNING','STARTED','TRAIN_DONE',
                         'VALIDATED','PROMOTED','FAILED','RETRY_PENDING')),
      ...,
      legacy_status TEXT, legacy_action TEXT, legacy_reference TEXT,
      legacy_source TEXT,
      migration_source_hash TEXT
        CHECK(migration_source_hash IS NULL OR length(migration_source_hash)=64),
      queued_at TEXT, queued_by TEXT
    );
    INSERT INTO training_jobs_new(...)
      SELECT ... FROM training_jobs;
    DROP TABLE training_jobs;
    ALTER TABLE training_jobs_new RENAME TO training_jobs;

    CREATE TRIGGER training_runs_reject_planned_job
      BEFORE INSERT ON training_runs
      WHEN (SELECT status FROM training_jobs WHERE id=NEW.job_id)='PLANNED'
      BEGIN SELECT RAISE(ABORT,'PLANNED job cannot have a training run'); END;

Migration utuh mencakup transition triggers pada job/run, trigger checkpoint, index tuple unik, trigger pencegah direct RUNNING insert, serta aturan audit eksplisit saat queue. SQL lengkap tercantum pada file migration di atas.

Parent table rebuild berisiko memicu ON DELETE CASCADE pada FK child. Migration ini ditandai opt-in foreign_keys_off untuk MigrationManager: FK enforcement dinonaktifkan sebelum BEGIN IMMEDIATE, seluruh DDL/data/version row dijalankan dalam satu transaksi, PRAGMA foreign_key_check dilakukan sebelum commit, lalu enforcement dipulihkan. Uji upgrade membuktikan rows training_runs, checkpoints, model_artifacts, training_job_datasets, dan audit_logs tetap ada. Jika migration gagal setelah rebuild, transaction rollback memulihkan schema v2 dan version row.

MigrationManager tetap menghitung SHA-256 SQL dan menolak versi terpasang dengan checksum yang berbeda; migration yang sudah cocok dilewati tanpa perubahan.

## 3. Lifecycle transition matrix

| Entitas | Dari | Ke yang diperbolehkan |
|---|---|---|
| training_jobs | PLANNED | QUEUED hanya dengan queue action/audit eksplisit |
| training_jobs | QUEUED | RUNNING, FAILED |
| training_jobs | RUNNING | TRAIN_DONE, FAILED |
| training_jobs | STARTED (legacy v2) | TRAIN_DONE, FAILED |
| training_jobs | TRAIN_DONE | VALIDATED, FAILED |
| training_jobs | VALIDATED | PROMOTED, FAILED |
| training_jobs | FAILED | RETRY_PENDING |
| training_jobs | RETRY_PENDING | RUNNING setelah run STARTED |
| training_jobs | PROMOTED | terminal, termasuk replay PROMOTED→PROMOTED |
| training_runs/checkpoints | QUEUED | STARTED, FAILED |
| training_runs/checkpoints | STARTED | TRAIN_DONE, FAILED |
| training_runs/checkpoints | TRAIN_DONE | VALIDATED, FAILED |
| training_runs/checkpoints | VALIDATED | PROMOTED, FAILED |
| training_runs/checkpoints | FAILED | RETRY_PENDING |
| training_runs/checkpoints | RETRY_PENDING | STARTED |
| training_runs/checkpoints | PROMOTED | terminal; tidak boleh diulang atau diturunkan |

PLANNED tidak muncul pada training_runs/checkpoints. PLANNED tidak bisa diklaim karena hanya queued runs yang dicari claim path dan database menolak pembuatan run untuk PLANNED job. PLANNED→QUEUED mensyaratkan status, queued_at/queued_by, dan audit_logs row yang cocok dalam satu transaksi queue_planned_job(actor). Queue action tidak membuat run. Job menjadi RUNNING hanya setelah run berstatus STARTED.

## 4. Perubahan aplikasi terkait

- repositories.py: create_job menyimpan legacy metadata; queue_planned_job melakukan explicit queue dan audit dalam transaksi; claim menerima RETRY_PENDING hanya saat run terkait berhasil diubah ke STARTED.
- interfaces.py: menambahkan queue_planned_job ke TrainingJobRepository.
- models.py: kolom legacy baru opsional pada TrainingJobCreate agar pemanggil v2 yang ada tetap kompatibel.
- migrations.py: migration khusus yang merebuild tabel dapat meminta FK enforcement OFF sebelum transaksi; jalankan foreign_key_check sebelum commit dan pulihkan pragma.
- Runner produksi dan checkpoint manager tidak diubah.
- bootstrap.py tetap menggunakan seluruh migration yang tersedia; memanggil production bootstrap pada database v2 akan mengaplikasikan v3. Itu tidak dilakukan pada audit ini.

## 5. Hasil tes aktual

Perintah hanya menjalankan tes SQLite v3/Foundation/integration/bootstrap dengan basetemp pada tests/_pytest_v3_temp, tanpa cache pytest.

    37 passed in 40.49s

Cakupan tes:
1. PLANNED dibuat tanpa dianggap QUEUED.
2. Claim atas PLANNED mengembalikan None; pembuatan run ditolak.
3. Direct PLANNED→QUEUED ditolak tanpa marker dan audit yang valid.
4. Queue eksplisit menulis audit; claim mengubah run STARTED dan job RUNNING.
5. RUNNING ditolak tanpa run STARTED.
6. PROMOTED terminal terhadap replay dan downgrade untuk job dan run.
7. Retry FAILED→RETRY_PENDING→RUNNING valid lewat run STARTED.
8. Upgrade fixture schema v2 mempertahankan seluruh child rows dan lolos foreign_key_check/integrity_check.
9. Migration v3 fault injection setelah table rebuild rollback ke schema/version v2 dan memulihkan foreign_keys=ON.
10. Migration idempotent dan checksum mismatch ditolak.
11. Regression tests Foundation v2, concurrent claim, run/checkpoint/audit atomicity, dan bootstrap lulus.

## 6. Compatibility risks

- Database produksi saat ini tetap v2. Production bootstrap akan menjalankan migration v3; jangan jalankan sampai langkah migrasi produksi disetujui dan dibackup sesuai prosedur.
- check_database_read_only membandingkan versi migration yang terpasang dengan seluruh migration yang tersedia. Karena itu DB v2 akan dilaporkan tidak kompatibel oleh checker versi source v3 sampai migrasi diterapkan. Perilaku ini mencegah aplikasi menyangka PLANNED tersedia.
- Runner/checkpoint manager lama tidak memahami PLANNED. Rencana harus tetap berada di repository/schema saja dan tidak dikirim ke runner sampai ada integrasi lifecycle yang ditinjau.
- Implementasi interface TrainingJobRepository lain perlu menyediakan queue_planned_job; hanya implementasi SQLite ditemukan di repository ini.
- Trigger PLANNED→QUEUED mengharuskan audit row yang cocok; pemanggilan langsung dari SQL tanpa audit ditolak. Aplikasi sebaiknya tetap memakai repository agar status dan audit selalu atomik.
- STARTED job dipertahankan sebagai nilai v2, sementara status job baru yang dianjurkan adalah RUNNING. Konsumen eksternal perlu menoleransi status legacy tersebut.
- MigrationManager marker foreign_keys_off harus dipakai hanya untuk migration table rebuild yang sudah diuji; pemeriksaan FK sebelum commit adalah bagian wajib keselamatan.

## 7. Rekomendasi berikutnya

1. Review migration v3 dan backup/restore procedure sebelum penerapan produksi.
2. Setelah persetujuan terpisah, jadwalkan penerapan pada salinan produksi dahulu dan bandingkan row counts/hash logical data sebelum mempertimbangkan production DB.
3. Jangan memigrasikan CSV atau 37 job dalam tahap schema ini.
4. Integrasikan planner hanya ke training_job_plans/PLANNED dan biarkan runner mengabaikannya sampai queue action eksplisit tersedia.

