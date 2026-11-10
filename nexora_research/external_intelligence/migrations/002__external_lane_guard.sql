-- NEXORA External Intel — R1: lane guard for research proposals (additive, low-risk).
--
-- Problem (P2-A, M-1): ext_research_proposals.lane had no DB-level constraint; lane
-- laundering was prevented only by P1 code. Add a defence-in-depth trigger that rejects
-- any INSERT/UPDATE with an unknown lane. This is additive (no table rebuild) and does
-- not touch existing rows except to reject future invalid lanes.
--
-- A proposal row is EXCLUSIVELY the INFO_ACQUISITION channel; the value must be one of
-- the closed set. (PRICE_DERIVED is accepted by the set for forward-compat but the
-- research_bridge still refuses to route any non-INFO lane.)

CREATE TRIGGER IF NOT EXISTS trg_ext_proposals_lane_insert
BEFORE INSERT ON ext_research_proposals
FOR EACH ROW
WHEN NEW.lane NOT IN ('INFO_ACQUISITION', 'PRICE_DERIVED')
BEGIN
    SELECT RAISE(ABORT, 'invalid lane in ext_research_proposals (must be INFO_ACQUISITION/PRICE_DERIVED)');
END;

CREATE TRIGGER IF NOT EXISTS trg_ext_proposals_lane_update
BEFORE UPDATE OF lane ON ext_research_proposals
FOR EACH ROW
WHEN NEW.lane NOT IN ('INFO_ACQUISITION', 'PRICE_DERIVED')
BEGIN
    SELECT RAISE(ABORT, 'invalid lane in ext_research_proposals (must be INFO_ACQUISITION/PRICE_DERIVED)');
END;

CREATE INDEX IF NOT EXISTS idx_proposals_lane ON ext_research_proposals(lane, governance_status);
