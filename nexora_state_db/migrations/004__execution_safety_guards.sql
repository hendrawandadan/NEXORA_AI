-- Enforce a single queued/started attempt per job at the database boundary.
CREATE UNIQUE INDEX uq_one_active_run_per_job
ON training_runs(job_id)
WHERE status IN ('QUEUED','STARTED');

DROP TRIGGER IF EXISTS training_jobs_status_transition;
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
      ) THEN RAISE(ABORT,'PLANNED job requires explicit queue audit')
      WHEN OLD.status='RETRY_PENDING' AND NOT (
        NEW.status='QUEUED' AND NEW.queued_at IS NOT NULL AND length(trim(COALESCE(NEW.queued_by,'')))>0 AND
        EXISTS (SELECT 1 FROM audit_logs WHERE entity_type='training_job' AND entity_id=CAST(OLD.id AS TEXT)
                AND action='retry_queue' AND old_state='RETRY_PENDING' AND new_state='QUEUED'
                AND actor=NEW.queued_by AND created_at=NEW.queued_at)
      ) THEN RAISE(ABORT,'retry requires explicit retry_queue audit')
      WHEN NEW.status='RUNNING' AND NOT EXISTS (SELECT 1 FROM training_runs WHERE job_id=NEW.id AND status='STARTED')
        THEN RAISE(ABORT,'RUNNING job requires a STARTED training run')
      WHEN OLD.status='QUEUED' AND NEW.status NOT IN ('RUNNING','FAILED') THEN RAISE(ABORT,'invalid job transition')
      WHEN OLD.status='RUNNING' AND NEW.status NOT IN ('TRAIN_DONE','FAILED') THEN RAISE(ABORT,'invalid job transition')
      WHEN OLD.status='STARTED' AND NEW.status NOT IN ('TRAIN_DONE','FAILED') THEN RAISE(ABORT,'invalid legacy STARTED job transition')
      WHEN OLD.status='TRAIN_DONE' AND NEW.status NOT IN ('VALIDATED','FAILED') THEN RAISE(ABORT,'invalid job transition')
      WHEN OLD.status='VALIDATED' AND NEW.status NOT IN ('PROMOTED','FAILED') THEN RAISE(ABORT,'invalid job transition')
      WHEN OLD.status='FAILED' AND NEW.status <> 'RETRY_PENDING' THEN RAISE(ABORT,'invalid job transition')
    END;
END;

DROP TRIGGER IF EXISTS training_runs_reject_planned_job;
CREATE TRIGGER training_runs_insert_guard
BEFORE INSERT ON training_runs
WHEN NEW.status <> 'QUEUED' OR (SELECT status FROM training_jobs WHERE id=NEW.job_id) <> 'QUEUED'
BEGIN
    SELECT RAISE(ABORT,'training run can be queued only for a QUEUED job');
END;

CREATE TRIGGER training_runs_claim_guard
BEFORE UPDATE OF status ON training_runs
WHEN OLD.status='QUEUED' AND NEW.status='STARTED'
 AND (SELECT status FROM training_jobs WHERE id=OLD.job_id) <> 'QUEUED'
BEGIN
    SELECT RAISE(ABORT,'claim requires a QUEUED job');
END;

DROP TRIGGER IF EXISTS training_runs_status_transition;
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
      WHEN OLD.status='RETRY_PENDING' THEN RAISE(ABORT,'retry creates a new run; prior attempt is terminal')
    END;
END;

DROP TRIGGER IF EXISTS checkpoints_transition_guard;
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
         ((SELECT status FROM training_runs WHERE id=NEW.run_id)='FAILED' AND NEW.checkpoint_status='RETRY_PENDING')
       ) THEN RAISE(ABORT,'invalid checkpoint transition')
    END;
END;
