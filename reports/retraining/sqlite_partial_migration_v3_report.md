# NEXORA AI v2 — Partial Migration Simulation v3 Report

Tanggal: 2026-11-07

## 1. Executive summary

**PASS — simulasi 37 job individual berhasil pada clone saja.** Ke-37 job dibuat dengan status PLANNED dan masing-masing memiliki relasi ke dataset yang sudah diverifikasi. Sepuluh job global tidak diimpor. Tidak ada training_runs, checkpoints, model_artifacts, atau validation_results baru.

Replay terhadap kedua CSV dengan source hash sama adalah no-op: snapshot seluruh tabel terkait sebelum dan sesudah replay identik. Rollback paksa dan constraint tests pada fixture terpisah lulus.

Database produksi tetap schema v2 dan hash-nya sama dengan baseline. **Runner integration belum siap** karena legacy training_config kosong untuk seluruh placeholder dan runner produksi tidak diubah/diintegrasikan dengan PLANNED. Tidak dilakukan queueing atau training.

## 2. Preflight verification

Snapshot preflight terpisah: reports/retraining/sqlite_partial_migration_v3_preflight.md.

Production database D:\NEXORA_AI_v2\database\nexora_state.db tersedia. Sebelum clone: schema v2 (migration 1 dan 2), 11 tabel, 18 indeks, WAL aktif, foreign_keys ON, synchronous FULL, integrity_check=ok, foreign_key_check=0. Database SHA-256 tetap E314244ED46099ABD0025E982640B9BE7711F608AC9A75FF5B44E4D43286D6C6.

CSV:
- reports/retraining/batch_retraining_plan.csv: 47 data rows; SHA-256 1BBEA13995BDECBE9A37C2481EE0EEE74E520C8E241A4F8779258EBDA5F7F1F0.
- reports/retraining/batch_execution_log.csv: 37 data rows; SHA-256 D73F196D5A313D1AB3FC878EA354B944AECAF8D074E94BC5DDA42900E0BF2DD8.

Production tables datasets/jobs/runs/checkpoints/audit_logs/artifacts/legacy_imports/validation_results kosong. Unique tuple plan total 47; 37 individual dan 10 global. 37 individual tuple keys unik dan semua cocok ke satu baris log. Per-row PREP references cocok ke tuple; run_status PENDING, checkpoint QUEUED, start/end dan training_config kosong.

## 3. Database clone verification

Clone dibuat melalui SQLite Backup API (bukan menyalin file .db saat WAL aktif). Target tidak ada sebelum dibuat dan tidak ditimpa.

- Clone: D:\NEXORA_AI_v2\database\simulation\partial_migration_v3.db
- Hash saat clone v2 sebelum migration: 92e2aa546cd75a0697688670b901371462bccc1feb0b2e3a6a7d3d4e015ea701
- Schema saat clone: v2, 11 tabel, 18 indeks
- SQLite schema objects sebelum migration identik dengan source v2
- Integrity: ok; FK violations: 0

## 4. Schema v3 migration result

Migration 003 diterapkan hanya ke clone; executed=[3]. Schema version clone menjadi 3; tabel tetap 11 dan indeks 18. Foreign key enforcement aktif pada connection manager, foreign_key_check=0 dan integrity_check=ok.

- File migration: nexora_state_db/migrations/003__planned_job_lifecycle.sql
- Stored migration checksum (canonical SQL text): 824eedf44ad7fa42d9a08a624ca3148958e2a668e79fdba9fd607368110f28aa
- Checksum SQL file raw bytes: A4B0E80F6EC19195995D08A14AAEC365C2DA1140BB660FDE821DC0F09F387605
- Clone hash setelah migration dan import: 419e7c5a92b97160042f50c4d80e92a56fd00708688c290ba7c1dc14ca7e8a06

Migration v3 tidak menghapus tabel. Rebuild training_jobs dan seluruh foreign-key paths telah diuji sebelumnya dengan child data; row counts training_runs, checkpoints, model_artifacts, training_job_datasets, dan audit_logs tetap utuh setelah upgrade v2→v3. Pada clone simulasi ini source tables awalnya kosong.

## 5. Dataset verification dan job reconciliation

Semua path di bawah di-rehash pada preflight dan kembali diperiksa setelah simulasi; file rows plan cocok dengan rows_valid_unique manifest. Manifest: schema_valid=true, interval PASS, invalid/duplicate timestamps=0, missing/nonpositive/invalid OHLC=0. Gap historis tetap perlu interpretasi kalender/sesi, sehingga pemeriksaan ini memverifikasi provenance dan kualitas struktural dasar, bukan kelengkapan seluruh pasar.

| Dataset ID clone | Symbol/TF | Jobs | Horizons | Rows | Path relatif | SHA-256 |
|---:|---|---:|---|---:|---|---|
| 3 | EURUSD M15 | 2 | 12,24 | 137995 | data/raw/EURUSD/EURUSD_M15_202001020000_202611062145.csv | 7b72f6cd9ab14ffd8d8479e4647fb2688a4c228aa80ce8edcd3a8fe5c7399f7f |
| 8 | EURUSD M2 | 5 | 2,4,8,12,24 | 1008234 | data/raw/EURUSD/EURUSD_M2_202001020000_202611062158.csv | 13859e31793517bdada9b9697a06ddbdc95e6d9b9f262672151738e1c1fc86c6 |
| 2 | EURUSD M20 | 5 | 2,4,8,12,24 | 104345 | data/raw/EURUSD/EURUSD_M20_202001020000_202611062140.csv | 53c814ffc2606ee9beb39f1670bca1aa102401431b4022a4d4a80cf0adc88773 |
| 7 | EURUSD M3 | 5 | 2,4,8,12,24 | 674812 | data/raw/EURUSD/EURUSD_M3_202001020000_202611062157.csv | d8f8d47e9c6f7eea5911a91c6cdbcd419aede035a6af3864e00d9151248d8659 |
| 1 | EURUSD M30 | 5 | 2,4,8,12,24 | 70694 | data/raw/EURUSD/EURUSD_M30_202001020000_202611062130.csv | e6729c4596f872f503cc04c7611375419395ab9cc92f9d918121609cdb282945 |
| 6 | EURUSD M4 | 5 | 2,4,8,12,24 | 507344 | data/raw/EURUSD/EURUSD_M4_202001020000_202611062156.csv | ad62a76d54b48a9f65e88919af0e11766cd0b330d0eed7b1f227a860e9ec7ee4 |
| 5 | EURUSD M5 | 5 | 2,4,8,12,24 | 406686 | data/raw/EURUSD/EURUSD_M5_202001020000_202611062155.csv | 394968386845468ada2374374f92d9563836163e1465d60257d91ca4a7fc9fd5 |
| 4 | EURUSD M6 | 5 | 2,4,8,12,24 | 339724 | data/raw/EURUSD/EURUSD_M6_202001020000_202611062154.csv | aef53eb85629740fbd506a0cea5aeeb39c109ed0ff407da73b895b97630f2f36 |

Job keys dibentuk deterministik dari tuple karena CSV tidak memiliki job_key legacy: legacy-plan-v3|individual|EURUSD|<timeframe>|H<horizon>. Ini mempertahankan tuple sebagai identitas teknis tanpa mengklaim ada ID job asli. Semua baris membawa legacy_status=MISSING, legacy_action=TRAIN, PREP reference, source path/row identity, serta plan CSV hash. Nilai log lengkap dan kedua source hashes disimpan di config_json sebagai metadata; training_configuration_state=NOT_SPECIFIED_IN_LEGACY_SOURCES.

| TF | Job keys / horizons | PREP references | Dataset ID |
|---|---|---|---:|
| M30 | H2,H4,H8,H12,H24 | PREP-001…PREP-005 | 1 |
| M20 | H2,H4,H8,H12,H24 | PREP-006…PREP-010 | 2 |
| M15 | H12,H24 | PREP-011…PREP-012 | 3 |
| M6 | H2,H4,H8,H12,H24 | PREP-013…PREP-017 | 4 |
| M5 | H2,H4,H8,H12,H24 | PREP-018…PREP-022 | 5 |
| M4 | H2,H4,H8,H12,H24 | PREP-023…PREP-027 | 6 |
| M3 | H2,H4,H8,H12,H24 | PREP-028…PREP-032 | 7 |
| M2 | H2,H4,H8,H12,H24 | PREP-033…PREP-037 | 8 |

37/37 tuple-to-log matches; 37/37 dataset checks passed; dataset IDs are clone-local records created from verified file path, row count, hash, and date metadata. No global row was loaded.

## 6. Import results and legacy audit

Import ran in one transaction against the clone. For each distinct timeframe a dataset record was created, then each job was inserted as PLANNED and linked to that dataset. Unique tuple constraint was retained and all 37 keys are unique.

legacy_imports contains two real completion records, each linked to an actual audit_logs event:
- Plan: source_rows=47, rows_imported=37, excluded_global=10, rejected=0, conflicts=0, status=IMPORTED; source SHA-256 1BBEA13995BDECBE9A37C2481EE0EEE74E520C8E241A4F8779258EBDA5F7F1F0.
- Execution log: source_rows=37, 37 rows retained as job provenance metadata (no runs created), rejected=0, conflicts=0, status=IMPORTED; source SHA-256 D73F196D5A313D1AB3FC878EA354B944AECAF8D074E94BC5DDA42900E0BF2DD8.

The execution log's PREP values were saved to legacy_reference. They were not copied into training_runs. Blank training_config fields remain explicitly marked unavailable; no training parameters were invented. legacy_imports notes preserve source/import/rejected/conflict/global exclusion counts and schema/mode.

## 7. Idempotency test

The exact importer transaction was invoked twice against the clone with unchanged source hashes.

- First invocation: created the two source import records, 8 dataset rows, 37 PLANNED jobs, 37 dataset links, and 2 completion audit events.
- Replay: detected both sources already IMPORTED with matching hashes and performed no writes.
- Snapshot comparison of datasets, jobs, links, runs, checkpoints, artifacts, validations, audits, and legacy_imports: identical before/after replay.
- Jobs/status/links/runs/checkpoints counts did not change on replay.

**Result: PASS.** No duplicate jobs or links, no status mutation, no run/checkpoint creation, and no success audit written on replay.

## 8. Rollback and constraint tests

A separate schema v3 fixture database was used. The transaction inserted three jobs, a dataset, three links, a STARTED legacy_import row, and an audit event, then a forced exception was raised. After rollback, all nine affected table counts matched zero baseline; no partial job, dataset, link, import record, or audit remained. integrity_check=ok and FK violations=0.

Additional fixture checks:
- Duplicate tuple with a different job_key: rejected.
- Invalid dataset reference/FK: rejected.
- Invalid migration_source_hash metadata: rejected.
- Invalid job status: rejected.

**Result: PASS.**

## 9. Data reconciliation

| Kategori | Expected | Actual |
|---|---:|---:|
| Individual jobs | 37 | 37 |
| Global jobs imported | 0 | 0 |
| Jobs PLANNED | up to 37 | 37 |
| Dataset records (unique timeframes) | 8 | 8 |
| Job-dataset relations | 37 | 37 |
| Training runs | 0 | 0 |
| Checkpoints | 0 | 0 |
| New model artifacts | 0 | 0 |
| New validation results | 0 | 0 |
| Rejected individual jobs | 0 | 0 |
| Conflicts | 0 | 0 |
| Unverified individual datasets | 0 | 0 |

Clone final schema version=3; integrity_check=ok; foreign_keys enabled on application connection; foreign_key_check=0; unique job tuple count=37.

## 10. Production safety verification

| Asset | Baseline SHA-256 | Final SHA-256 | Result |
|---|---|---|---|
| Production database | E314244ED46099ABD0025E982640B9BE7711F608AC9A75FF5B44E4D43286D6C6 | E314244ED46099ABD0025E982640B9BE7711F608AC9A75FF5B44E4D43286D6C6 | IDENTICAL |
| batch_retraining_plan.csv | 1BBEA13995BDECBE9A37C2481EE0EEE74E520C8E241A4F8779258EBDA5F7F1F0 | 1BBEA13995BDECBE9A37C2481EE0EEE74E520C8E241A4F8779258EBDA5F7F1F0 | IDENTICAL |
| batch_execution_log.csv | D73F196D5A313D1AB3FC878EA354B944AECAF8D074E94BC5DDA42900E0BF2DD8 | D73F196D5A313D1AB3FC878EA354B944AECAF8D074E94BC5DDA42900E0BF2DD8 | IDENTICAL |

All eight raw dataset hashes after the simulation match their preflight hashes shown in section 5. No commands wrote model or backup paths; no model/backup files were changed by this workflow. All SQLite mutations were restricted to the new simulation clone and a temporary rollback fixture. No training function or batch runner was executed. Production remains schema v2.

## 11. Risks and unresolved issues

- Legacy training_config is blank for all 37 rows. The records are plans only; runner integration requires an approved actual training configuration.
- Current production runner/checkpoint manager were not changed and do not consume PLANNED. Do not queue these jobs or connect the runner until a separate integration and validation stage.
- PREP IDs remain metadata only and are not historical run IDs.
- Manifests show structural checks passing but note gaps; gap completeness is not established.
- Production schema remains v2, while clone is v3. No production migration was attempted.

## 12. Recommended next steps

1. Define and review training configuration fields/defaults before runner integration.
2. Review the simulated job/dataset mapping on the clone.
3. Plan runner integration separately; PLANNED must remain non-runnable until explicit queue action plus audit.
4. Do not apply schema v3 to production or process global jobs without a separate authorization and preflight.

