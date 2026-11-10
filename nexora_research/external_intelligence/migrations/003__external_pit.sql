-- NEXORA External Intel — R2: POINT-IN-TIME (PIT) columns (additive, non-destructive).
--
-- Problem (P2-B): external data stored only ONE fact time (scheduled/published) plus ONE
-- ingestion time (retrieved_at_utc). There was no separate release/availability time
-- (publish embargo) nor a vintage/revision marker, so historical "as-of" reconstruction
-- -- and therefore look-ahead safety -- could not be verified from the data alone.
--
-- Fix: add explicit PIT columns. Everything is ADDITIVE (new nullable columns with
-- safe defaults + a derived backfill). Producers MUST fill availability only when the
-- SOURCE provides it; otherwise available_at_utc stays NULL and pit_verified=0 (we never
-- fabricate an availability time). This migration does not delete or rewrite fact values.
--
-- Semantics introduced:
--   published_at_utc     : when the SOURCE published/first released the datum.
--   available_at_utc     : when the datum became KNOWABLE to the market (>= published,
--                          accounts for embargo / release delay). The PIT basis.
--   ingested_at_utc      : when OUR system retrieved it (== retrieved_at_utc at insert).
--   vintage / revision_as_of_utc : revision identity / as-of for revised series.
--   pit_verified         : 1 ONLY when available_at_utc is backed by the source's own
--                          timestamp; otherwise 0 (data is NOT proven PIT-safe).

-- --- Economic events ---
ALTER TABLE ext_economic_events ADD COLUMN published_at_utc TEXT;
ALTER TABLE ext_economic_events ADD COLUMN available_at_utc TEXT;
ALTER TABLE ext_economic_events ADD COLUMN ingested_at_utc TEXT;
ALTER TABLE ext_economic_events ADD COLUMN vintage TEXT;
ALTER TABLE ext_economic_events ADD COLUMN revision_as_of_utc TEXT;
ALTER TABLE ext_economic_events
    ADD COLUMN pit_verified INTEGER NOT NULL DEFAULT 0
    CHECK(pit_verified IN (0, 1));

-- Backfill ingestion from the existing retrieval timestamp (lossless: same value).
UPDATE ext_economic_events SET ingested_at_utc = retrieved_at_utc
 WHERE ingested_at_utc IS NULL;

CREATE INDEX IF NOT EXISTS idx_event_available
    ON ext_economic_events(available_at_utc);
CREATE INDEX IF NOT EXISTS idx_event_pit
    ON ext_economic_events(pit_verified);

-- --- Central-bank documents ---
ALTER TABLE ext_central_bank_docs ADD COLUMN available_at_utc TEXT;
ALTER TABLE ext_central_bank_docs ADD COLUMN first_observed_at_utc TEXT;
ALTER TABLE ext_central_bank_docs
    ADD COLUMN pit_verified INTEGER NOT NULL DEFAULT 0
    CHECK(pit_verified IN (0, 1));
UPDATE ext_central_bank_docs SET first_observed_at_utc = retrieved_at_utc
 WHERE first_observed_at_utc IS NULL;
CREATE INDEX IF NOT EXISTS idx_cb_available
    ON ext_central_bank_docs(available_at_utc);

-- --- News ---
ALTER TABLE ext_news_records ADD COLUMN available_at_utc TEXT;
ALTER TABLE ext_news_records ADD COLUMN first_observed_at_utc TEXT;
ALTER TABLE ext_news_records
    ADD COLUMN pit_verified INTEGER NOT NULL DEFAULT 0
    CHECK(pit_verified IN (0, 1));
UPDATE ext_news_records SET first_observed_at_utc = retrieved_at_utc
 WHERE first_observed_at_utc IS NULL;
CREATE INDEX IF NOT EXISTS idx_news_available
    ON ext_news_records(available_at_utc);

-- --- Event responses: record the price bar actually used and the PIT basis ---
ALTER TABLE ext_event_responses ADD COLUMN as_of_utc TEXT;
ALTER TABLE ext_event_responses ADD COLUMN event_available_at_utc TEXT;
