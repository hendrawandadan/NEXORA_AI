-- NEXORA Research Memory — R1: structured LANE columns (additive, low-risk).
--
-- Problem (P2-A): lane was only carried inside go_criteria_json (hypothesis) or
-- not at all (experiments / evaluations / failures / knowledge). Lane could not be
-- queried and INFO_ACQUISITION vs PRICE_DERIVED could be mixed silently.
--
-- Fix: make lane a first-class, CHECK-constrained column and denormalise it down the
-- pipeline so every artefact records which lane produced it. This migration is
-- ADDITIVE and NON-DESTRUCTIVE:
--   * new columns have safe defaults (PRICE_DERIVED) or are nullable,
--   * existing rows are preserved (append-only store is untouched),
--   * a backfill copies lane out of go_criteria_json where it was previously stored.
--
-- Valid lane values (closed set): 'PRICE_DERIVED', 'INFO_ACQUISITION'.

-- (2) Hypotheses: lane is REQUIRED and constrained. Default preserves old behaviour
--     (everything that existed before R1 was price-derived). Backfill from go_criteria.
ALTER TABLE research_hypotheses
    ADD COLUMN lane TEXT NOT NULL DEFAULT 'PRICE_DERIVED'
    CHECK(lane IN ('PRICE_DERIVED', 'INFO_ACQUISITION'));

-- Backfill: if a stored hypothesis previously carried lane inside go_criteria_json,
-- promote it to the real column (only for the info-acquisition lane; inexpressible /
-- unknown values stay PRICE_DERIVED to remain fail-closed for the suspended lane).
UPDATE research_hypotheses
   SET lane = 'INFO_ACQUISITION'
 WHERE lane = 'PRICE_DERIVED'
   AND json_valid(go_criteria_json)
   AND json_extract(go_criteria_json, '$.lane') = 'INFO_ACQUISITION';

-- (3) Experiments: denormalised lane (inherited from the bound hypothesis).
ALTER TABLE research_experiments
    ADD COLUMN lane TEXT
    CHECK(lane IS NULL OR lane IN ('PRICE_DERIVED', 'INFO_ACQUISITION'));

-- (5) Evaluations: verdict must record the lane it judged.
ALTER TABLE research_evaluations
    ADD COLUMN lane TEXT
    CHECK(lane IS NULL OR lane IN ('PRICE_DERIVED', 'INFO_ACQUISITION'));

-- (6) Failures: failure-learning must record the lane it learned about.
ALTER TABLE research_failures
    ADD COLUMN lane TEXT
    CHECK(lane IS NULL OR lane IN ('PRICE_DERIVED', 'INFO_ACQUISITION'));

-- (7) Knowledge: lane-tagged so INFO vs PRICE knowledge can be separated by SQL.
ALTER TABLE research_knowledge
    ADD COLUMN lane TEXT
    CHECK(lane IS NULL OR lane IN ('PRICE_DERIVED', 'INFO_ACQUISITION'));

CREATE INDEX IF NOT EXISTS idx_hyp_lane ON research_hypotheses(lane);
CREATE INDEX IF NOT EXISTS idx_exp_lane ON research_experiments(lane);
CREATE INDEX IF NOT EXISTS idx_fail_lane ON research_failures(lane);
CREATE INDEX IF NOT EXISTS idx_knowledge_lane ON research_knowledge(lane);
