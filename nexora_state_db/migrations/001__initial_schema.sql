PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS schema_migrations (
    version INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    checksum TEXT NOT NULL,
    applied_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);

CREATE TABLE IF NOT EXISTS datasets (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol TEXT NOT NULL,
    timeframe TEXT NOT NULL,
    source_path TEXT NOT NULL,
    bars_count INTEGER NOT NULL CHECK(bars_count >= 0),
    status TEXT NOT NULL DEFAULT 'usable' CHECK(status IN ('usable','insufficient','invalid','archived')),
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    UNIQUE(symbol, timeframe, source_path)
);

CREATE TABLE IF NOT EXISTS training_jobs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    job_key TEXT NOT NULL UNIQUE,
    scope TEXT NOT NULL CHECK(scope IN ('individual','global')),
    symbol TEXT,
    timeframe TEXT NOT NULL,
    horizon INTEGER NOT NULL CHECK(horizon > 0),
    status TEXT NOT NULL DEFAULT 'QUEUED' CHECK(status IN ('QUEUED','STARTED','TRAIN_DONE','VALIDATED','PROMOTED','FAILED','RETRY_PENDING')),
    config_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);

CREATE TABLE IF NOT EXISTS training_job_datasets (
    job_id INTEGER NOT NULL,
    dataset_id INTEGER NOT NULL,
    role TEXT NOT NULL DEFAULT 'train',
    linked_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    PRIMARY KEY(job_id, dataset_id),
    FOREIGN KEY(job_id) REFERENCES training_jobs(id) ON DELETE CASCADE,
    FOREIGN KEY(dataset_id) REFERENCES datasets(id) ON DELETE RESTRICT
);

CREATE TABLE IF NOT EXISTS training_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id INTEGER NOT NULL,
    run_uid TEXT NOT NULL UNIQUE,
    run_index INTEGER NOT NULL CHECK(run_index >= 0),
    status TEXT NOT NULL CHECK(status IN ('QUEUED','STARTED','TRAIN_DONE','VALIDATED','PROMOTED','FAILED','RETRY_PENDING')),
    training_config_json TEXT NOT NULL DEFAULT '{}',
    started_at TEXT,
    ended_at TEXT,
    error_message TEXT,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    FOREIGN KEY(job_id) REFERENCES training_jobs(id) ON DELETE CASCADE,
    UNIQUE(job_id, run_index)
);

CREATE TABLE IF NOT EXISTS checkpoints (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id INTEGER NOT NULL,
    checkpoint_status TEXT NOT NULL CHECK(checkpoint_status IN ('QUEUED','STARTED','TRAIN_DONE','VALIDATED','PROMOTED','FAILED','RETRY_PENDING')),
    changed_by TEXT NOT NULL,
    note TEXT NOT NULL DEFAULT '',
    metadata_json TEXT NOT NULL DEFAULT '{}',
    changed_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    FOREIGN KEY(run_id) REFERENCES training_runs(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS model_artifacts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id INTEGER NOT NULL,
    artifact_type TEXT NOT NULL CHECK(artifact_type IN ('model','report','signals','metadata','manifest','other')),
    artifact_path TEXT NOT NULL,
    sha256 TEXT NOT NULL,
    size_bytes INTEGER NOT NULL CHECK(size_bytes >= 0),
    is_temporary INTEGER NOT NULL DEFAULT 1 CHECK(is_temporary IN (0,1)),
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    FOREIGN KEY(run_id) REFERENCES training_runs(id) ON DELETE CASCADE,
    UNIQUE(run_id, artifact_type, artifact_path)
);

CREATE TABLE IF NOT EXISTS validation_results (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id INTEGER NOT NULL,
    validation_type TEXT NOT NULL,
    passed INTEGER NOT NULL CHECK(passed IN (0,1)),
    details_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    FOREIGN KEY(run_id) REFERENCES training_runs(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS strategy_experiments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id INTEGER,
    experiment_key TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'created' CHECK(status IN ('created','running','done','failed')),
    config_json TEXT NOT NULL DEFAULT '{}',
    result_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    FOREIGN KEY(run_id) REFERENCES training_runs(id) ON DELETE SET NULL,
    UNIQUE(experiment_key)
);

CREATE TABLE IF NOT EXISTS audit_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    entity_type TEXT NOT NULL,
    entity_id TEXT NOT NULL,
    action TEXT NOT NULL,
    old_state TEXT,
    new_state TEXT,
    payload_json TEXT NOT NULL DEFAULT '{}',
    actor TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);

CREATE TABLE IF NOT EXISTS legacy_imports (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_name TEXT NOT NULL,
    source_path TEXT NOT NULL,
    imported_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    rows_imported INTEGER NOT NULL DEFAULT 0 CHECK(rows_imported >= 0),
    notes TEXT NOT NULL DEFAULT '',
    UNIQUE(source_name, source_path)
);

CREATE INDEX IF NOT EXISTS idx_datasets_symbol_tf ON datasets(symbol, timeframe);
CREATE INDEX IF NOT EXISTS idx_jobs_scope_tf ON training_jobs(scope, timeframe);
CREATE INDEX IF NOT EXISTS idx_runs_job_status ON training_runs(job_id, status);
CREATE INDEX IF NOT EXISTS idx_checkpoints_run_changed ON checkpoints(run_id, changed_at);
CREATE INDEX IF NOT EXISTS idx_artifacts_run_type ON model_artifacts(run_id, artifact_type);
CREATE INDEX IF NOT EXISTS idx_validation_run ON validation_results(run_id);
CREATE INDEX IF NOT EXISTS idx_audit_entity ON audit_logs(entity_type, entity_id, created_at);
