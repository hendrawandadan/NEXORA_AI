-- NEXORA Autonomous Research — Knowledge Memory schema (v1).
-- Isolated research DB. Immutable-by-append: content is hashed; rows are never
-- updated in place -- a change means a NEW row (new version), preserving history.

PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS schema_migrations (
    version INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    checksum TEXT NOT NULL,
    applied_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);

-- (2) Hypothesis: pre-registered BEFORE any experiment. Content-hashed.
CREATE TABLE IF NOT EXISTS research_hypotheses (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    hypothesis_key TEXT NOT NULL UNIQUE,          -- caller-supplied deterministic key
    instrument TEXT NOT NULL,
    timeframe TEXT NOT NULL,
    horizon_bars INTEGER NOT NULL CHECK(horizon_bars > 0),
    market_condition TEXT NOT NULL DEFAULT '',    -- e.g. HIGH_VOL / session tag
    signal_source TEXT NOT NULL DEFAULT '',       -- which information drives it
    claim TEXT NOT NULL,                          -- falsifiable statement
    go_criteria_json TEXT NOT NULL DEFAULT '{}',  -- pre-registered GO/NO-GO thresholds
    content_sha256 TEXT NOT NULL,                 -- hash of canonical hypothesis body
    status TEXT NOT NULL DEFAULT 'PRE_REGISTERED'
        CHECK(status IN ('PROPOSED','PRE_REGISTERED','UNDER_TEST','EVALUATED','RETIRED')),
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    UNIQUE(content_sha256, status)
);

-- (3) Experiment: deterministic spec bound to a pre-registered hypothesis.
CREATE TABLE IF NOT EXISTS research_experiments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    experiment_key TEXT NOT NULL UNIQUE,
    hypothesis_id INTEGER NOT NULL,
    spec_json TEXT NOT NULL DEFAULT '{}',         -- dataset, split, target, metrics, cost scenarios
    spec_sha256 TEXT NOT NULL,                     -- hash of canonical spec
    status TEXT NOT NULL DEFAULT 'CREATED'
        CHECK(status IN ('CREATED','SKIPPED_INFEASIBLE','TRAINED','EVALUATED','FAILED')),
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    FOREIGN KEY(hypothesis_id) REFERENCES research_hypotheses(id) ON DELETE RESTRICT
);

-- (5) Evaluation: net-of-cost verdict with statistical uncertainty.
CREATE TABLE IF NOT EXISTS research_evaluations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    experiment_id INTEGER NOT NULL,
    verdict TEXT NOT NULL
        CHECK(verdict IN ('GO','NO_GO','INCONCLUSIVE')),
    net_expectancy_pips REAL,
    auc_net REAL,
    lower_ci REAL,
    upper_ci REAL,
    details_json TEXT NOT NULL DEFAULT '{}',
    result_sha256 TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    FOREIGN KEY(experiment_id) REFERENCES research_experiments(id) ON DELETE RESTRICT
);

-- (6) Failure: structured cause + evidence + required next-action. Appended on NO_GO.
CREATE TABLE IF NOT EXISTS research_failures (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    experiment_id INTEGER NOT NULL,
    failure_type TEXT NOT NULL
        CHECK(failure_type IN (
            'DATA_QUALITY','STRUCTURAL_INFEASIBILITY','NO_PREDICTIVE_POWER',
            'EDGE_BELOW_COST','OVERFIT','REGIME_FRAGILE','UNKNOWN')),
    evidence_json TEXT NOT NULL DEFAULT '{}',
    recommendation TEXT NOT NULL,                  -- required: failure must teach
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    FOREIGN KEY(experiment_id) REFERENCES research_experiments(id) ON DELETE RESTRICT
);

-- (7) Knowledge: immutable, versioned knowledge entries derived from results.
-- A change = a NEW row with higher version; the prior row is never modified.
CREATE TABLE IF NOT EXISTS research_knowledge (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    knowledge_key TEXT NOT NULL,
    version INTEGER NOT NULL CHECK(version > 0),
    kind TEXT NOT NULL
        CHECK(kind IN ('FINDING','CONSTRAINT','DEAD_END','STRATEGY_LEAD')),
    summary TEXT NOT NULL,
    detail_json TEXT NOT NULL DEFAULT '{}',
    source_experiment_id INTEGER,
    content_sha256 TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    FOREIGN KEY(source_experiment_id) REFERENCES research_experiments(id) ON DELETE SET NULL,
    UNIQUE(knowledge_key, version)
);

CREATE INDEX IF NOT EXISTS idx_hyp_status ON research_hypotheses(status);
CREATE INDEX IF NOT EXISTS idx_exp_hyp ON research_experiments(hypothesis_id);
CREATE INDEX IF NOT EXISTS idx_eval_exp ON research_evaluations(experiment_id);
CREATE INDEX IF NOT EXISTS idx_fail_exp ON research_failures(experiment_id);
CREATE INDEX IF NOT EXISTS idx_knowledge_key ON research_knowledge(knowledge_key, version);
