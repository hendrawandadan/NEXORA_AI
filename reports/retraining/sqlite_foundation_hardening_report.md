# SQLite Foundation Hardening Report

Date: 2026-11-07

## Scope

Hardened the SQLite foundation in `nexora_state_db/` and its focused unit/integration tests. No training was run. No CSV migration was run. No production database migration was run. Runner, checkpoint manager, `train_one`, models, backups, and datasets were not changed.

## Changes

- Replaced `sqlite3.executescript()` in the migration path with statement-by-statement execution inside the existing `BEGIN IMMEDIATE` transaction. Schema changes and the `schema_migrations` row now commit or roll back together.
- Added migration `002__sqlite_foundation_hardening.sql`. It adds job `RUNNING` status, rebuilds the job table while retaining its rows and foreign keys, enforces unique `(scope, symbol, timeframe, horizon)` tuples (with NULL symbols treated as one global tuple), adds dataset SHA-256 and time-range metadata, adds artifact lifecycle fields, and adds legacy import hash/audit/completion/status fields.
- Made `PROMOTED` strictly terminal, including rejection of `PROMOTED → PROMOTED` replay.
- Made run claiming one immediate transaction: conditional run update to `STARTED`, `STARTED` checkpoint insert, audit insert, and job update to `RUNNING`. Any failure rolls back the complete claim.
- Added SHA-256 validation for artifact and dataset metadata. Dataset creation accepts optional content hash and time bounds.
- Added targeted tests for migration rollback, checksum mismatch, idempotency, concurrent claim, claim and checkpoint audit rollback, terminal `PROMOTED`, reopen/integrity, global jobs linked to two datasets, schema metadata, artifact hash validation, and foreign keys.

## Test results

Command: `python -m pytest -q tests/test_sqlite_foundation.py tests/test_sqlite_foundation_integration.py`

Result: **24 passed in 3.35s**.

The tests use temporary databases. The focused integration test also exercised the new claim-to-promotion path.

## CSV preservation

`reports/retraining/batch_execution_log.csv` SHA-256 after the work:

`D73F196D5A313D1AB3FC878EA354B944AECAF8D074E94BC5DDA42900E0BF2DD8`

This matches the previously recorded production baseline. No CSV was edited.

## Remaining risks and limits

- Migration 002 was exercised against fresh temporary databases only. It was deliberately not applied to any existing or production database. Before applying it to a populated database, check for duplicate `(scope, symbol, timeframe, horizon)` tuples; the new unique index will reject such data and roll the migration back.
- Existing artifacts receive lifecycle status `STAGED` when the migration adds the column. If legacy rows represent already active artifacts, their lifecycle values need a reviewed backfill before relying on lifecycle status operationally.
- Dataset hash and time metadata are nullable to preserve compatibility with existing rows; the database enforces digest length when a hash is present, while repository APIs additionally enforce hexadecimal form and ordered time bounds.
- This hardening does not wire the SQLite foundation into the production runner or replace any CSV checkpoint path.
