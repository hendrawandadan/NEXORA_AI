-- nexora:foreign_keys_off
PRAGMA defer_foreign_keys = ON;

-- Rebuild parent table so every v2 row is retained while adding plan provenance.
CREATE TABLE training_jobs_new (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    job_key TEXT NOT NULL UNIQUE,
    scope TEXT NOT NULL CHECK(scope IN ('individual','global')),
    symbol TEXT,
    timeframe TEXT NOT NULL,
    horizon INTEGER NOT NULL CHECK(horizon > 0),
    status TEXT NOT NULL DEFAULT 'PLANNED' CHECK(status IN ('PLANNED','QUEUED','RUNNING','STARTED','TRAIN_DONE','VALIDATED','PROMOTED','FAILED','RETRY_PENDING')),
    config_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    legacy_status TEXT,
    legacy_action TEXT,
    legacy_reference TEXT,
    legacy_source TEXT,
    migration_source_hash TEXT CHECK(migration_source_hash IS NULL OR length(migration_source_hash)=64),
    queued_at TEXT,
    queued_by TEXT
);
INSERT INTO training_jobs_new(id,job_key,scope,symbol,timeframe,horizon,status,config_json,created_at,updated_at)
SELECT id,job_key,scope,symbol,timeframe,horizon,status,config_json,created_at,updated_at FROM training_jobs;
DROP TABLE training_jobs;
ALTER TABLE training_jobs_new RENAME TO training_jobs;
CREATE INDEX idx_jobs_scope_tf ON training_jobs(scope,timeframe);
CREATE UNIQUE INDEX uq_training_job_tuple ON training_jobs(scope,ifnull(symbol,''),timeframe,horizon);

CREATE TRIGGER training_jobs_status_transition
BEFORE UPDATE OF status ON training_jobs
WHEN OLD.status='PROMOTED' OR OLD.status <> NEW.status
BEGIN
    SELECT CASE
      WHEN OLD.status='PROMOTED' THEN RAISE(ABORT,'PROMOTED job is terminal')
      WHEN OLD.status='PLANNED' AND NOT (
        NEW.status='QUEUED' AND NEW.queued_at IS NOT NULL AND length(trim(COALESCE(NEW.queued_by,'')))>0 AND
        EXISTS (SELECT 1 FROM audit_logs WHERE entity_type='training_job' AND entity_id=CAST(OLD.id AS TEXT)
                AND action='explicit_queue' AND old_state='PLANNED' AND new_state='QUEUED'
                AND actor=NEW.queued_by AND created_at=NEW.queued_at)
      )
        THEN RAISE(ABORT,'PLANNED job requires explicit queue action')
      WHEN NEW.status='RUNNING' AND NOT EXISTS (SELECT 1 FROM training_runs WHERE job_id=NEW.id AND status='STARTED')
        THEN RAISE(ABORT,'RUNNING job requires a STARTED training run')
      WHEN OLD.status='QUEUED' AND NEW.status NOT IN ('RUNNING','FAILED') THEN RAISE(ABORT,'invalid job transition')
      WHEN OLD.status='RUNNING' AND NEW.status NOT IN ('TRAIN_DONE','FAILED') THEN RAISE(ABORT,'invalid job transition')
      WHEN OLD.status='STARTED' AND NEW.status NOT IN ('TRAIN_DONE','FAILED') THEN RAISE(ABORT,'invalid legacy STARTED job transition')
      WHEN OLD.status='TRAIN_DONE' AND NEW.status NOT IN ('VALIDATED','FAILED') THEN RAISE(ABORT,'invalid job transition')
      WHEN OLD.status='VALIDATED' AND NEW.status NOT IN ('PROMOTED','FAILED') THEN RAISE(ABORT,'invalid job transition')
      WHEN OLD.status='FAILED' AND NEW.status <> 'RETRY_PENDING' THEN RAISE(ABORT,'invalid job transition')
      WHEN OLD.status='RETRY_PENDING' AND NEW.status <> 'RUNNING' THEN RAISE(ABORT,'invalid job transition')
    END;
END;

CREATE TRIGGER training_jobs_no_direct_running_insert
BEFORE INSERT ON training_jobs
WHEN NEW.status='RUNNING'
BEGIN
    SELECT RAISE(ABORT,'RUNNING job requires a STARTED training run');
END;

CREATE TRIGGER training_runs_reject_planned_job
BEFORE INSERT ON training_runs
WHEN (SELECT status FROM training_jobs WHERE id=NEW.job_id)='PLANNED'
BEGIN
    SELECT RAISE(ABORT,'PLANNED job cannot have a training run');
END;

CREATE TRIGGER training_runs_status_transition
BEFORE UPDATE OF status ON training_runs
WHEN OLD.status='PROMOTED' OR OLD.status <> NEW.status
BEGIN
    SELECT CASE
      WHEN OLD.status='PROMOTED' THEN RAISE(ABORT,'PROMOTED run is terminal')
      WHEN OLD.status='QUEUED' AND NEW.status NOT IN ('STARTED','FAILED') THEN RAISE(ABORT,'invalid run transition')
      WHEN OLD.status='STARTED' AND NEW.status NOT IN ('TRAIN_DONE','FAILED') THEN RAISE(ABORT,'invalid run transition')
      WHEN OLD.status='TRAIN_DONE' AND NEW.status NOT IN ('VALIDATED','FAILED') THEN RAISE(ABORT,'invalid run transition')
      WHEN OLD.status='VALIDATED' AND NEW.status NOT IN ('PROMOTED','FAILED') THEN RAISE(ABORT,'invalid run transition')
      WHEN OLD.status='FAILED' AND NEW.status <> 'RETRY_PENDING' THEN RAISE(ABORT,'invalid run transition')
      WHEN OLD.status='RETRY_PENDING' AND NEW.status <> 'STARTED' THEN RAISE(ABORT,'invalid run transition')
    END;
END;

CREATE TRIGGER checkpoints_transition_guard
BEFORE INSERT ON checkpoints
BEGIN
    SELECT CASE
      WHEN (SELECT status FROM training_runs WHERE id=NEW.run_id)='PROMOTED'
        THEN RAISE(ABORT,'PROMOTED run is terminal')
      WHEN NEW.checkpoint_status <> (SELECT status FROM training_runs WHERE id=NEW.run_id)
       AND NOT (
         ((SELECT status FROM training_runs WHERE id=NEW.run_id)='QUEUED' AND NEW.checkpoint_status IN ('STARTED','FAILED')) OR
         ((SELECT status FROM training_runs WHERE id=NEW.run_id)='STARTED' AND NEW.checkpoint_status IN ('TRAIN_DONE','FAILED')) OR
         ((SELECT status FROM training_runs WHERE id=NEW.run_id)='TRAIN_DONE' AND NEW.checkpoint_status IN ('VALIDATED','FAILED')) OR
         ((SELECT status FROM training_runs WHERE id=NEW.run_id)='VALIDATED' AND NEW.checkpoint_status IN ('PROMOTED','FAILED')) OR
         ((SELECT status FROM training_runs WHERE id=NEW.run_id)='FAILED' AND NEW.checkpoint_status='RETRY_PENDING') OR
         ((SELECT status FROM training_runs WHERE id=NEW.run_id)='RETRY_PENDING' AND NEW.checkpoint_status='STARTED')
       ) THEN RAISE(ABORT,'invalid checkpoint transition')
    END;
END;
