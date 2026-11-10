-- NEXORA Autonomous Research Scheduler — isolated job-queue schema (v1).
--
-- DISCOVERY-ONLY orchestrator state. This database is SEPARATE from:
--   * database/nexora_state.db          (production — never touched here)
--   * database/nexora_research.db        (Knowledge Memory)
--   * database/nexora_external_intel.db  (external intelligence provenance)
--
-- Every write target the scheduler is allowed to touch is a *research* artefact. This
-- schema itself only records the *fact* that a discovery-only job ran; it never stores
-- model artefacts, training results, promotions, or live-trading state.
--
-- Append-friendly design: jobs are the durable queue; job_executions is an append-only
-- execution-history log; job_retries is an append-only retry-history log; audit_trail is
-- an append-only audit log. Status is a guarded state machine (see config.JOB_TRANSITIONS
-- and the trigger below).

PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS schema_migrations (
    version INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    checksum TEXT NOT NULL,
    applied_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);

-- ------------------------------------------------------------------ #
-- Persistent job queue. One row per scheduled unit of research work.
-- ------------------------------------------------------------------ #
CREATE TABLE IF NOT EXISTS scheduler_jobs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    job_key TEXT NOT NULL UNIQUE,               -- deterministic caller-supplied key
    idempotency_key TEXT NOT NULL,              -- dedupe key (see job_queue.enqueue)
    kind TEXT NOT NULL,                         -- RESEARCH_CYCLE / INFO_ACQUISITION / ...
    status TEXT NOT NULL DEFAULT 'QUEUED'
        CHECK(status IN ('QUEUED','RUNNING','COMPLETED','FAILED','RETRY_WAIT',
                         'BLOCKED','CANCELLED')),
    trigger_source TEXT NOT NULL DEFAULT 'MANUAL',  -- MANUAL / INTERVAL / EVENT
    payload_json TEXT NOT NULL DEFAULT '{}',    -- job inputs (instrument, evidence refs)
    spec_sha256 TEXT NOT NULL,                  -- content hash of (kind,payload)
    priority INTEGER NOT NULL DEFAULT 100,      -- lower = earlier
    attempts INTEGER NOT NULL DEFAULT 0,        -- number of execution attempts so far
    max_retries INTEGER NOT NULL DEFAULT 3,
    next_attempt_at TEXT,                       -- for RETRY_WAIT backoff scheduling
    last_error TEXT,
    blocked_reason TEXT,
    result_json TEXT,                           -- structured job result (summary only)
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    started_at TEXT,
    finished_at TEXT,
    UNIQUE(kind, idempotency_key)
);

CREATE INDEX IF NOT EXISTS idx_jobs_status ON scheduler_jobs(status);
CREATE INDEX IF NOT EXISTS idx_jobs_kind ON scheduler_jobs(kind);
CREATE INDEX IF NOT EXISTS idx_jobs_next_attempt ON scheduler_jobs(next_attempt_at);

-- Append-only execution history (one row per attempt).
CREATE TABLE IF NOT EXISTS job_executions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id INTEGER NOT NULL,
    attempt INTEGER NOT NULL,
    status TEXT NOT NULL,            -- RUNNING / COMPLETED / FAILED / BLOCKED / TIMEOUT
    started_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    finished_at TEXT,
    duration_s REAL,
    error TEXT,
    result_json TEXT,
    FOREIGN KEY(job_id) REFERENCES scheduler_jobs(id) ON DELETE RESTRICT
);
CREATE INDEX IF NOT EXISTS idx_exec_job ON job_executions(job_id);

-- Append-only retry history.
CREATE TABLE IF NOT EXISTS job_retries (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id INTEGER NOT NULL,
    attempt INTEGER NOT NULL,       -- the attempt number that FAILED
    backoff_s REAL NOT NULL,        -- delay applied before the next attempt
    scheduled_for TEXT NOT NULL,    -- next_attempt_at after backoff
    error TEXT,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    FOREIGN KEY(job_id) REFERENCES scheduler_jobs(id) ON DELETE RESTRICT
);
CREATE INDEX IF NOT EXISTS idx_retry_job ON job_retries(job_id);

-- Append-only audit trail (every status change + safety decision).
CREATE TABLE IF NOT EXISTS audit_trail (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    entity_type TEXT NOT NULL DEFAULT 'job',
    entity_id TEXT,
    action TEXT NOT NULL,
    old_state TEXT,
    new_state TEXT,
    actor TEXT NOT NULL DEFAULT 'scheduler',
    detail_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);
CREATE INDEX IF NOT EXISTS idx_audit_entity ON audit_trail(entity_type, entity_id);

-- Provider health snapshots (rate-limited acquisition observability).
CREATE TABLE IF NOT EXISTS provider_health (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    provider_id TEXT NOT NULL,
    status TEXT NOT NULL,           -- OK / RATE_LIMITED / ERROR / UNKNOWN
    detail_json TEXT NOT NULL DEFAULT '{}',
    observed_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);

-- ------------------------------------------------------------------ #
-- Guard: status transitions must be legal (config.JOB_TRANSITIONS mirrors this).
-- ------------------------------------------------------------------ #
CREATE TRIGGER scheduler_jobs_transition_guard
BEFORE UPDATE OF status ON scheduler_jobs
WHEN OLD.status <> NEW.status
BEGIN
    SELECT CASE
      WHEN OLD.status='COMPLETED' THEN RAISE(ABORT,'COMPLETED job is terminal')
      WHEN OLD.status='BLOCKED'   THEN RAISE(ABORT,'BLOCKED job is terminal')
      WHEN OLD.status='CANCELLED' THEN RAISE(ABORT,'CANCELLED job is terminal')
      WHEN OLD.status='QUEUED'
           AND NEW.status NOT IN ('RUNNING','BLOCKED','CANCELLED')
        THEN RAISE(ABORT,'invalid transition from QUEUED')
      WHEN OLD.status='RUNNING'
           AND NEW.status NOT IN ('COMPLETED','FAILED','BLOCKED','CANCELLED')
        THEN RAISE(ABORT,'invalid transition from RUNNING')
      WHEN OLD.status='FAILED'
           AND NEW.status NOT IN ('RETRY_WAIT','CANCELLED')
        THEN RAISE(ABORT,'invalid transition from FAILED')
      WHEN OLD.status='RETRY_WAIT'
           AND NEW.status NOT IN ('RUNNING','CANCELLED')
        THEN RAISE(ABORT,'invalid transition from RETRY_WAIT')
    END;
END;

-- Guard: forbidden job kinds must never be inserted (makes forbidden-kind tampering
-- impossible even if application checks are bypassed).
CREATE TRIGGER scheduler_jobs_forbid_non_research
BEFORE INSERT ON scheduler_jobs
WHEN NEW.kind IN ('TRAIN','TRAINING','HYPERPARAMETER_TUNE','TUNE','PROMOTE_MODEL',
                  'PROMOTION','ENABLE_LIVE_TRADING','LIVE_TRADING','REOPEN_LANE',
                  'AUTO_REOPEN','PRODUCTION_WRITE')
BEGIN
    SELECT RAISE(ABORT,'forbidden job kind: scheduler is DISCOVERY-ONLY');
END;
