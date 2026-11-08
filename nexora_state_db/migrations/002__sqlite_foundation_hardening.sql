PRAGMA defer_foreign_keys = ON;

-- Rebuild the job table to include the operational RUNNING state while
-- preserving existing rows and child foreign-key relationships.
CREATE TABLE training_jobs_new (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    job_key TEXT NOT NULL UNIQUE,
    scope TEXT NOT NULL CHECK(scope IN ('individual','global')),
    symbol TEXT,
    timeframe TEXT NOT NULL,
    horizon INTEGER NOT NULL CHECK(horizon > 0),
    status TEXT NOT NULL DEFAULT 'QUEUED' CHECK(status IN ('QUEUED','RUNNING','STARTED','TRAIN_DONE','VALIDATED','PROMOTED','FAILED','RETRY_PENDING')),
    config_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);
INSERT INTO training_jobs_new(id,job_key,scope,symbol,timeframe,horizon,status,config_json,created_at,updated_at)
SELECT id,job_key,scope,symbol,timeframe,horizon,status,config_json,created_at,updated_at FROM training_jobs;
DROP TABLE training_jobs;
ALTER TABLE training_jobs_new RENAME TO training_jobs;
CREATE INDEX IF NOT EXISTS idx_jobs_scope_tf ON training_jobs(scope, timeframe);

ALTER TABLE datasets ADD COLUMN content_sha256 TEXT CHECK(content_sha256 IS NULL OR length(content_sha256)=64);
ALTER TABLE datasets ADD COLUMN time_start TEXT;
ALTER TABLE datasets ADD COLUMN time_end TEXT;
CREATE INDEX IF NOT EXISTS idx_datasets_hash ON datasets(content_sha256);

CREATE UNIQUE INDEX IF NOT EXISTS uq_training_job_tuple
ON training_jobs(scope, ifnull(symbol,''), timeframe, horizon);

ALTER TABLE model_artifacts ADD COLUMN lifecycle_status TEXT NOT NULL DEFAULT 'STAGED'
    CHECK(lifecycle_status IN ('STAGED','ACTIVE','RETIRED','DELETED'));
ALTER TABLE model_artifacts ADD COLUMN activated_at TEXT;
ALTER TABLE model_artifacts ADD COLUMN retired_at TEXT;
CREATE INDEX IF NOT EXISTS idx_artifacts_lifecycle ON model_artifacts(lifecycle_status,run_id);

ALTER TABLE legacy_imports ADD COLUMN source_sha256 TEXT CHECK(source_sha256 IS NULL OR length(source_sha256)=64);
ALTER TABLE legacy_imports ADD COLUMN audit_id INTEGER REFERENCES audit_logs(id) ON DELETE SET NULL;
ALTER TABLE legacy_imports ADD COLUMN completed_at TEXT;
ALTER TABLE legacy_imports ADD COLUMN status TEXT NOT NULL DEFAULT 'IMPORTED'
    CHECK(status IN ('STARTED','IMPORTED','FAILED'));
