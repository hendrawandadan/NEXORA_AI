-- NEXORA External Information Intelligence V1 -- repository schema (v1).
-- ISOLATED database (database/nexora_external_intel.db). NEVER production.
-- Principles:
--   * append-only: rows are inserted, never updated in place. A correction is a new
--     row (supersedes_id) preserving history.
--   * content-hashed: each row carries content_sha256 so tampering is detectable.
--   * provenance: source_provider + source_ref + retrieved_at + data_quality.
--   * unique constraints prevent silent duplicates.

PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS schema_migrations (
    version INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    checksum TEXT NOT NULL,
    applied_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);

-- Raw source records: the verbatim (hash-only) capture of a fetched payload.
CREATE TABLE IF NOT EXISTS ext_raw_records (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    provider_id TEXT NOT NULL,
    resource TEXT NOT NULL,
    fetched_status TEXT NOT NULL,
    http_status INTEGER,
    content_sha256 TEXT NOT NULL,
    byte_size INTEGER,
    retrieved_at_utc TEXT NOT NULL,
    is_synthetic INTEGER NOT NULL DEFAULT 0,
    message TEXT NOT NULL DEFAULT '',
    -- de-dup: identical provider/resource/payload captured once per retrieval window
    UNIQUE(content_sha256, provider_id, resource, retrieved_at_utc)
);
CREATE INDEX IF NOT EXISTS idx_raw_provider ON ext_raw_records(provider_id, retrieved_at_utc);

-- Normalised economic events (CPI, NFP, GDP, rate decisions, ...).
CREATE TABLE IF NOT EXISTS ext_economic_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    event_key TEXT NOT NULL,                 -- deterministic natural key
    event_type TEXT NOT NULL,                -- CPI / NFP / GDP / RATE_DECISION / ...
    country TEXT NOT NULL,
    currency TEXT NOT NULL,
    economic_domain TEXT NOT NULL DEFAULT '',-- inflation / employment / growth / policy
    importance TEXT NOT NULL DEFAULT 'UNKNOWN', -- HIGH/MEDIUM/LOW/UNKNOWN
    period TEXT NOT NULL DEFAULT '',
    scheduled_ts TEXT NOT NULL,              -- release timestamp (UTC ISO)
    actual REAL,
    forecast REAL,
    previous REAL,
    revised_previous REAL,
    has_actual INTEGER NOT NULL DEFAULT 0,
    has_forecast INTEGER NOT NULL DEFAULT 0,
    unit TEXT NOT NULL DEFAULT '',
    source_provider TEXT NOT NULL,
    source_ref TEXT NOT NULL DEFAULT '',
    retrieved_at_utc TEXT NOT NULL,
    data_quality TEXT NOT NULL DEFAULT 'UNVERIFIED',
    content_sha256 TEXT NOT NULL,
    supersedes_id INTEGER,
    is_synthetic INTEGER NOT NULL DEFAULT 0,
    UNIQUE(event_key, content_sha256),
    FOREIGN KEY(supersedes_id) REFERENCES ext_economic_events(id) ON DELETE SET NULL
);
CREATE INDEX IF NOT EXISTS idx_event_type_country ON ext_economic_events(event_type, country);
CREATE INDEX IF NOT EXISTS idx_event_ts ON ext_economic_events(scheduled_ts);

-- Central-bank documents (statements, minutes, speeches).
CREATE TABLE IF NOT EXISTS ext_central_bank_docs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    doc_key TEXT NOT NULL,
    institution TEXT NOT NULL,               -- FED / ECB / BOJ / BOE / SNB / RBA / BOC
    doc_type TEXT NOT NULL,                  -- STATEMENT / MINUTES / SPEECH / DECISION
    title TEXT NOT NULL DEFAULT '',
    published_ts TEXT NOT NULL,
    source_provider TEXT NOT NULL,
    source_ref TEXT NOT NULL,                -- URL / identifier
    body_sha256 TEXT NOT NULL,               -- hash of the (untrusted) body text
    tone TEXT NOT NULL DEFAULT 'UNKNOWN',    -- HAWKISH / DOVISH / NEUTRAL / UNKNOWN
    tone_confidence REAL NOT NULL DEFAULT 0.0,
    summary TEXT NOT NULL DEFAULT '',
    retrieved_at_utc TEXT NOT NULL,
    is_synthetic INTEGER NOT NULL DEFAULT 0,
    content_sha256 TEXT NOT NULL,
    UNIQUE(doc_key, content_sha256)
);
CREATE INDEX IF NOT EXISTS idx_cb_inst ON ext_central_bank_docs(institution, published_ts);

-- News records (classified).
CREATE TABLE IF NOT EXISTS ext_news_records (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    news_key TEXT NOT NULL,
    headline TEXT NOT NULL,
    category TEXT NOT NULL DEFAULT 'ECONOMIC',  -- ECONOMIC/GEOPOLITICAL/TRADE/SANCTIONS/...
    countries_json TEXT NOT NULL DEFAULT '[]',
    currencies_json TEXT NOT NULL DEFAULT '[]',
    impact TEXT NOT NULL DEFAULT 'UNKNOWN',    -- impact classification
    entities_json TEXT NOT NULL DEFAULT '[]',
    source_provider TEXT NOT NULL,
    source_ref TEXT NOT NULL DEFAULT '',
    published_ts TEXT NOT NULL,
    country TEXT NOT NULL DEFAULT '',
    currency TEXT NOT NULL DEFAULT '',
    reliability TEXT NOT NULL DEFAULT 'UNKNOWN',
    duplicate_of_id INTEGER,
    event_ts TEXT NOT NULL DEFAULT '',
    body_sha256 TEXT NOT NULL DEFAULT '',
    retrieved_at_utc TEXT NOT NULL,
    is_synthetic INTEGER NOT NULL DEFAULT 0,
    content_sha256 TEXT NOT NULL,
    UNIQUE(news_key, content_sha256),
    FOREIGN KEY(duplicate_of_id) REFERENCES ext_news_records(id) ON DELETE SET NULL
);
CREATE INDEX IF NOT EXISTS idx_news_cat ON ext_news_records(category, published_ts);
CREATE INDEX IF NOT EXISTS idx_news_dup ON ext_news_records(duplicate_of_id);

-- Cross-market observations (derived analyses stored for provenance/reproducibility).
CREATE TABLE IF NOT EXISTS ext_cross_market_observations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    analysis_key TEXT NOT NULL,
    pair_a TEXT NOT NULL,
    pair_b TEXT NOT NULL,
    method TEXT NOT NULL,                    -- correlation / rolling / lead_lag / regime
    window INTEGER,
    lag INTEGER,
    value REAL,
    n_obs INTEGER NOT NULL DEFAULT 0,
    regime TEXT NOT NULL DEFAULT '',
    caveat TEXT NOT NULL DEFAULT '',
    computed_at_utc TEXT NOT NULL,
    content_sha256 TEXT NOT NULL,
    UNIQUE(analysis_key, content_sha256)
);
CREATE INDEX IF NOT EXISTS idx_xm_pair ON ext_cross_market_observations(pair_a, pair_b, method);

-- Fundamental interpretations (event -> market implications, evidence-grounded).
CREATE TABLE IF NOT EXISTS ext_fundamental_findings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    finding_key TEXT NOT NULL,
    event_id INTEGER,
    subject TEXT NOT NULL,                   -- event/theme the interpretation is about
    interpretation TEXT NOT NULL,            -- human-readable, evidence-bounded
    direction TEXT NOT NULL DEFAULT 'UNCLEAR', -- HIGHER/LOWER/UNCLEAR
    surprise REAL,                           -- actual - forecast when both present
    surprise_present INTEGER NOT NULL DEFAULT 0,
    implications_json TEXT NOT NULL DEFAULT '{}',
    confidence TEXT NOT NULL DEFAULT 'LOW',  -- LOW/MEDIUM/HIGH
    evidence_json TEXT NOT NULL DEFAULT '[]',
    source_ids_json TEXT NOT NULL DEFAULT '[]',
    created_at_utc TEXT NOT NULL,
    is_synthetic INTEGER NOT NULL DEFAULT 0,
    content_sha256 TEXT NOT NULL,
    FOREIGN KEY(event_id) REFERENCES ext_economic_events(id) ON DELETE SET NULL,
    UNIQUE(finding_key, content_sha256)
);
CREATE INDEX IF NOT EXISTS idx_finding_subject ON ext_fundamental_findings(subject);

-- Event -> market response observations (leakage-aware).
CREATE TABLE IF NOT EXISTS ext_event_responses (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    response_key TEXT NOT NULL,
    event_id INTEGER,
    instrument TEXT NOT NULL,
    horizon TEXT NOT NULL,                   -- 1m/5m/.../1d
    horizon_minutes INTEGER NOT NULL,
    pre_price REAL,
    post_price REAL,
    return_pct REAL,
    direction TEXT NOT NULL DEFAULT 'FLAT',
    valid INTEGER NOT NULL DEFAULT 0,        -- 0 if insufficient data
    note TEXT NOT NULL DEFAULT '',
    computed_at_utc TEXT NOT NULL,
    content_sha256 TEXT NOT NULL,
    FOREIGN KEY(event_id) REFERENCES ext_economic_events(id) ON DELETE SET NULL,
    UNIQUE(response_key, content_sha256)
);
CREATE INDEX IF NOT EXISTS idx_response_event ON ext_event_responses(event_id, instrument);

-- Source registry snapshot (which providers were known / used).
CREATE TABLE IF NOT EXISTS ext_source_snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    provider_id TEXT NOT NULL,
    tier INTEGER NOT NULL,
    connector_available INTEGER NOT NULL DEFAULT 0,
    access_status TEXT NOT NULL DEFAULT '',
    captured_at_utc TEXT NOT NULL,
    content_sha256 TEXT NOT NULL,
    UNIQUE(provider_id, content_sha256)
);

-- New-information research proposals (routed to research bridge; NOT auto-registered).
CREATE TABLE IF NOT EXISTS ext_research_proposals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    proposal_key TEXT NOT NULL,
    instrument TEXT NOT NULL,
    lane TEXT NOT NULL DEFAULT 'INFO_ACQUISITION',
    claim TEXT NOT NULL,
    novelty_rationale TEXT NOT NULL DEFAULT '',
    data_requirements_json TEXT NOT NULL DEFAULT '[]',
    falsification_criteria TEXT NOT NULL DEFAULT '',
    evidence_json TEXT NOT NULL DEFAULT '{}',
    source_ids_json TEXT NOT NULL DEFAULT '[]',
    governance_status TEXT NOT NULL DEFAULT 'UNKNOWN',
    created_at_utc TEXT NOT NULL,
    content_sha256 TEXT NOT NULL,
    UNIQUE(proposal_key, content_sha256)
);

-- Audit trail: every repository write is journalled (append-only).
CREATE TABLE IF NOT EXISTS ext_audit_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    action TEXT NOT NULL,                    -- INSERT_<table>
    table_name TEXT NOT NULL,
    row_content_sha256 TEXT NOT NULL,
    created_at_utc TEXT NOT NULL
);
