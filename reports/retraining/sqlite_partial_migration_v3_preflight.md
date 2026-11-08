# SQLite Partial Migration v3 — Preflight Snapshot

Waktu snapshot: 2026-11-07, sebelum job import dijalankan. Sumber diperiksa read-only.

## Production database

- Path: D:\NEXORA_AI_v2\database\nexora_state.db
- SHA-256: E314244ED46099ABD0025E982640B9BE7711F608AC9A75FF5B44E4D43286D6C6 (baseline cocok)
- Migration versions: 1, 2 (schema v2)
- Tables: 11; indexes termasuk autoindexes: 18
- journal_mode WAL; foreign_keys ON; synchronous FULL (2)
- integrity_check: ok; foreign_key_check: 0 violation
- Row counts: datasets 0; training_jobs 0; training_job_datasets 0; training_runs 0; checkpoints 0; audit_logs 0; model_artifacts 0; legacy_imports 0; validation_results 0

## Legacy CSV

| File | Data rows | SHA-256 |
|---|---:|---|
| reports/retraining/batch_retraining_plan.csv | 47 (37 individual, 10 global) | 1bbea13995bdecbe9a37c2481ee0eee74e520c8e241a4f8779258ebda5f7f1f0 |
| reports/retraining/batch_execution_log.csv | 37 placeholders | d73f196d5a313d1ab3fc878ea354b944aecaf8d074e94bc5dda42900e0bf2dd8 |

37 individual tuple keys unik; seluruh 37 cocok satu-ke-satu dengan execution log. Semua plan MISSING/TRAIN; log PENDING/QUEUED dengan PREP reference, tetapi start_time/end_time dan training_config kosong. Placeholder tidak membuktikan eksekusi/run.

## Dataset individual

Delapan path yang dipakai tiap job telah di-rehash. Semua hash dan rows_valid_unique cocok dengan plan. Manifest menyatakan schema valid, interval PASS, nol invalid/duplicate timestamp dan nol OHLC quality errors.

| TF | Path | Rows | Rentang waktu | SHA-256 |
|---|---|---:|---|---|
| M15 | data/raw/EURUSD/EURUSD_M15_202001020000_202611062145.csv | 137995 | 2020-01-02 00:00:00 — 2026-11-06 21:45:00 | 7b72f6cd9ab14ffd8d8479e4647fb2688a4c228aa80ce8edcd3a8fe5c7399f7f |
| M2 | data/raw/EURUSD/EURUSD_M2_202001020000_202611062158.csv | 1008234 | 2020-01-02 00:00:00 — 2026-11-06 21:58:00 | 13859e31793517bdada9b9697a06ddbdc95e6d9b9f262672151738e1c1fc86c6 |
| M20 | data/raw/EURUSD/EURUSD_M20_202001020000_202611062140.csv | 104345 | 2020-01-02 00:00:00 — 2026-11-06 21:40:00 | 53c814ffc2606ee9beb39f1670bca1aa102401431b4022a4d4a80cf0adc88773 |
| M3 | data/raw/EURUSD/EURUSD_M3_202001020000_202611062157.csv | 674812 | 2020-01-02 00:00:00 — 2026-11-06 21:57:00 | d8f8d47e9c6f7eea5911a91c6cdbcd419aede035a6af3864e00d9151248d8659 |
| M30 | data/raw/EURUSD/EURUSD_M30_202001020000_202611062130.csv | 70694 | 2020-01-02 00:00:00 — 2026-11-06 21:30:00 | e6729c4596f872f503cc04c7611375419395ab9cc92f9d918121609cdb282945 |
| M4 | data/raw/EURUSD/EURUSD_M4_202001020000_202611062156.csv | 507344 | 2020-01-02 00:00:00 — 2026-11-06 21:56:00 | ad62a76d54b48a9f65e88919af0e11766cd0b330d0eed7b1f227a860e9ec7ee4 |
| M5 | data/raw/EURUSD/EURUSD_M5_202001020000_202611062155.csv | 406686 | 2020-01-02 00:00:00 — 2026-11-06 21:55:00 | 394968386845468ada2374374f92d9563836163e1465d60257d91ca4a7fc9fd5 |
| M6 | data/raw/EURUSD/EURUSD_M6_202001020000_202611062154.csv | 339724 | 2020-01-02 00:00:00 — 2026-11-06 21:54:00 | aef53eb85629740fbd506a0cea5aeeb39c109ed0ff407da73b895b97630f2f36 |

Dataset ID belum ada di production v2; delapan dataset records dibentuk hanya pada clone dari path/hash/metadata terverifikasi.

