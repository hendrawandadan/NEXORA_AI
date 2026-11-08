# SQLite Foundation Architecture (Tahap 1)

## Ruang Lingkup

Fondasi ini menyiapkan database state training berbasis SQLite untuk menggantikan CSV read-modify-write pada fase berikutnya. CSV tetap dipertahankan sebagai arsip/export.

## Komponen

- `nexora_state_db/connection.py`
  - `SQLiteConnectionManager`
  - PRAGMA: `journal_mode=WAL`, `synchronous=FULL`, `foreign_keys=ON`, `busy_timeout=10000`
  - `transaction_immediate(...)` untuk serialisasi state-change.
- `nexora_state_db/migrations.py`
  - `MigrationManager` + checksum migration
  - migration idempotent + versioned.
- `nexora_state_db/migrations/001__initial_schema.sql`
  - seluruh tabel inti + constraints + index.
- `nexora_state_db/interfaces.py`
  - kontrak repository (future-compatible backend, termasuk potensi MySQL).
- `nexora_state_db/repositories.py`
  - implementasi SQLite untuk jobs, runs, checkpoints, artifacts, audit logs.
- `nexora_state_db/bootstrap.py`
  - bootstrap DB development/test terpisah.

## Aturan Checkpoint

Status didukung:

- `QUEUED`, `STARTED`, `TRAIN_DONE`, `VALIDATED`, `PROMOTED`, `FAILED`, `RETRY_PENDING`

Validasi transisi dilakukan di repository checkpoint.

Aturan terminal:

- `PROMOTED` tidak dapat diturunkan/diulang ke state lain.

Setiap perubahan state run menulis catatan ke `audit_logs` dalam transaksi yang sama.

## Prinsip Transaksi

- Operasi claim run (`claim_next_queued_run`) menggunakan `BEGIN IMMEDIATE`.
- Operasi state transition checkpoint menggunakan `BEGIN IMMEDIATE`.
- Transaksi DB tidak didesain untuk ditahan selama proses training model (training nanti berjalan di luar transaksi DB dan hanya sinkronisasi state sebelum/sesudah).

## Catatan Kompatibilitas

- Query menggunakan parameterized SQL.
- Layer repository dipisah dari business logic training.
- Interface repository sudah disediakan agar backend lain (misalnya MySQL) dapat ditambahkan tanpa mengubah kontrak layanan tingkat atas.
