# Production SQLite Bootstrap Report

Tanggal: 2026-11-07

## Hasil

Database SQLite produksi pertama berhasil dibuat dan diverifikasi.

- Path aktual: `D:\NEXORA_AI_v2\database\nexora_state.db`
- SHA-256: `E314244ED46099ABD0025E982640B9BE7711F608AC9A75FF5B44E4D43286D6C6`
- Schema version: `2` (seluruh migration yang tersedia diterapkan)
- Integrity: `PRAGMA integrity_check = ok`
- Tables: 11
- Indexes: 18
- Journal: WAL
- Foreign keys: aktif
- Synchronous: FULL
- Busy timeout: 10.000 ms
- Path check: path absolut di root proyek, bukan Dropbox, dan drive lokal (bukan network share)

Perintah read-only yang tersedia:

```powershell
python -m nexora_state_db check
```

Perintah tersebut membuka database dengan URI `mode=ro`, mengaktifkan `query_only`, lalu memverifikasi versi/checksum migration, object schema, WAL, integrity, dan foreign-key integrity. Ia tidak menerapkan migration. Saat database WAL diperiksa, SQLite dapat membuat sidecar WAL/SHM untuk koordinasi baca; isi database tidak ditulis oleh perintah check.

## Perubahan implementasi

- Ditambahkan `nexora_state_db/config.py` dengan `PROJECT_ROOT` dihitung dari lokasi modul dan `PRODUCTION_DATABASE_PATH` absolut pada `database/nexora_state.db`.
- Ditambahkan `nexora_state_db/production_bootstrap.py`. Bootstrap membuat parent directory setelah validasi, membangun database baru pada file sementara di direktori yang sama, menerapkan migration, memeriksa schema/integrity, lalu mempublikasikannya dengan operasi create-if-absent. Jika target sudah ada, bootstrap hanya memeriksa secara read-only dan menolak schema/checksum/integrity yang tidak sesuai; ia tidak menginisialisasi ulang atau memigrasikan file lama.
- Validasi lokasi menolak komponen path Dropbox, drive remote Windows, direktori target yang bukan file, serta directory reparse point.
- Ditambahkan `python -m nexora_state_db bootstrap` dan `python -m nexora_state_db check`; check adalah perintah read-only.
- Ditambahkan `.gitignore` dengan pola database `.db`, `.sqlite`, `.sqlite3`, `.db-wal`, dan `.db-shm` yang diminta.
- Migration 002 kini membangun kembali indeks `idx_jobs_scope_tf` yang terhapus saat tabel `training_jobs` dibangun ulang.
- Helper `create_dev_database()` tetap tersedia untuk tes/development dan tidak dijadikan jalur bootstrap produksi.

## Tes yang dijalankan

Perintah:

```powershell
python -m pytest -q tests/test_sqlite_production_bootstrap.py tests/test_sqlite_foundation.py tests/test_sqlite_foundation_integration.py
```

Hasil aktual: **31 passed in 4.71s**.

| Tes | Hasil |
|---|---|
| `test_production_path_is_absolute_and_project_root_based` | PASS |
| `test_bootstrap_empty_database_has_full_schema_and_pragmas` | PASS |
| `test_second_bootstrap_is_idempotent_and_does_not_change_file` | PASS |
| `test_read_only_check_and_reopen` | PASS |
| `test_incompatible_existing_database_rejected_without_changes` | PASS |
| `test_failed_bootstrap_leaves_no_partial_database` | PASS |
| `test_database_in_dropbox_path_is_rejected` | PASS |
| `tests/test_sqlite_foundation.py` (22 tes) | PASS |
| `tests/test_sqlite_foundation_integration.py` (2 tes) | PASS |

Bootstrap kedua kali diuji pada database sementara: hash file tetap sama. Database kompatibel yang sudah ada hanya diperiksa; database yang tidak kompatibel ditolak tanpa perubahan hash. Kegagalan migration pada database sementara tidak meninggalkan file target atau file bootstrap sementara.

## Pemeriksaan produksi

Bootstrap dijalankan setelah tes lulus:

```text
database_path=D:\NEXORA_AI_v2\database\nexora_state.db
schema_version=2
integrity_check=ok
journal_mode=wal
foreign_keys=1
synchronous_full=1
busy_timeout_ms=10000
tables=11
indexes=18
```

Perintah `python -m nexora_state_db check` setelah inisialisasi memberikan hasil yang sama.

CSV yang dilarang berubah tetap memiliki hash sebelumnya:

- `reports/retraining/batch_execution_log.csv`: `D73F196D5A313D1AB3FC878EA354B944AECAF8D074E94BC5DDA42900E0BF2DD8`
- `reports/retraining/batch_retraining_plan.csv`: `1BBEA13995BDECBE9A37C2481EE0EEE74E520C8E241A4F8779258EBDA5F7F1F0`

Tidak ada CSV yang diimpor. Training tidak dijalankan dan model, dataset, backup, maupun runner produksi tidak diubah.

## Risiko tersisa

- Bootstrap memerlukan filesystem lokal yang mendukung hard link untuk publikasi atomik. Jika volume tidak mendukungnya, bootstrap gagal dan file target tidak dipublikasikan.
- Database yang sudah ada dengan schema lebih lama atau checksum berbeda sengaja ditolak; peningkatan versi harus dilakukan melalui rencana migrasi tersendiri dan backup.
- WAL memerlukan izin tulis pada direktori database untuk file sidecar ketika aplikasi membuka database. Simpan database pada volume lokal persisten dengan izin yang dibatasi untuk akun aplikasi.
- Database baru berisi schema kosong saja. CSV migration belum dilakukan dan tetap menjadi tahap terpisah setelah audit sumber dan persetujuan cutover.
