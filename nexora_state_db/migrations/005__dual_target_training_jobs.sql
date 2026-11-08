-- Migration v5: dual-target training jobs (T1 statistical / T3 execution-aligned).
--
-- Adds a `target_type` column to `training_jobs` and relaxes the job tuple
-- uniqueness so that a T1 job and a T3 job can coexist for the same
-- (scope, symbol, timeframe, horizon). Legacy rows are backfilled to 'T1'
-- because the pre-v5 pipeline only ever produced the close->close target.
--
-- This is an in-place schema change (ADD COLUMN + index swap), NOT a table
-- rebuild: all existing triggers and foreign keys are preserved untouched, so
-- the synchronized lifecycle and the one-active-run guard keep working. Every
-- statement is transactional, so a failure rolls back the whole migration.
--
-- Rollback / recovery strategy (manual, documented): the change is additive and
-- backward compatible. To roll back a temporary/dev database you would:
--   1. DROP INDEX uq_training_job_tuple;          -- the new target-aware index
--   2. Recreate the v4 index:
--        CREATE UNIQUE INDEX uq_training_job_tuple
--          ON training_jobs(scope, ifnull(symbol,''), timeframe, horizon);
--      (this requires that no duplicate (scope,symbol,tf,h) rows across
--       different target_type exist; delete the extra rows first if so)
--   3. DELETE FROM schema_migrations WHERE version=5;
-- The target_type column itself may be left in place (it is harmless) or the
-- table rebuilt if a fully v4 shape is required. Production rollback is a human
-- sign-off operation and is NOT automated here.

-- 1. Add the target_type column. NOT NULL with a constant default backfills all
--    existing rows to 'T1' atomically. A CHECK restricts values to T1/T3 so an
--    invalid target type is rejected at the database boundary.
ALTER TABLE training_jobs ADD COLUMN target_type TEXT NOT NULL DEFAULT 'T1'
    CHECK(target_type IN ('T1','T3'));

-- 2. Backfill explicitly (idempotent, defensive): every pre-existing job is T1.
UPDATE training_jobs SET target_type='T1' WHERE target_type IS NULL OR target_type='';

-- 3. Replace the (scope,symbol,tf,horizon) unique index with a target-aware one.
--    The new unique tuple is UNIQUE(scope, ifnull(symbol,''), timeframe, horizon, target_type)
--    so T1 and T3 coexist while duplicate (any target) rows are still rejected.
DROP INDEX IF EXISTS uq_training_job_tuple;
CREATE UNIQUE INDEX uq_training_job_tuple
    ON training_jobs(scope, ifnull(symbol,''), timeframe, horizon, target_type);

-- 4. Preserve/extend the non-unique lookup index for target-aware queries.
DROP INDEX IF EXISTS idx_jobs_scope_tf_target;
CREATE INDEX idx_jobs_scope_tf_target
    ON training_jobs(scope, timeframe, target_type);
