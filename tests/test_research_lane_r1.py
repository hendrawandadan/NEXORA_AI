"""R1 — structured LANE columns end-to-end (nexora_research.store + external guard).

Verifies the P2-A remediation:
  * lane is a first-class, CHECK-constrained column on every research artefact,
  * lane is inherited down hypothesis -> experiment -> evaluation/failure -> knowledge,
  * INFO_ACQUISITION and PRICE_DERIVED knowledge/hypotheses are separable by SQL,
  * invalid lanes are rejected (fail-closed) at both API and DB level,
  * the external proposal table rejects an invalid lane via its trigger.

Read-only w.r.t. production; uses isolated temp DBs only.
"""

import sqlite3
import tempfile
import shutil
from pathlib import Path

import pytest

from nexora_research.store import ResearchMemoryStore, LANES, _normalise_lane
from nexora_research.external_intelligence.config import EXTERNAL_INTEL_MIGRATIONS_DIR
from nexora_state_db.connection import SQLiteConnectionManager
from nexora_state_db.migrations import MigrationManager


@pytest.fixture()
def store(tmp_path):
    return ResearchMemoryStore(db_path=tmp_path / "research_r1.db")


def _reg(store, key, lane="PRICE_DERIVED", **kw):
    base = dict(hypothesis_key=key, instrument="EURUSD", timeframe="H4",
                horizon_bars=12, claim="claim", lane=lane)
    base.update(kw)
    return store.register_hypothesis(**base)


# --------------------------- lane normalisation ---------------------------
def test_normalise_lane_accepts_known_and_rejects_unknown():
    assert _normalise_lane("price_derived") == "PRICE_DERIVED"
    assert _normalise_lane(" info_acquisition ") == "INFO_ACQUISITION"
    with pytest.raises(ValueError):
        _normalise_lane("BOGUS")
    # The low-level normaliser is strictly fail-closed: None is not a valid lane.
    with pytest.raises(ValueError):
        _normalise_lane(None)


# --------------------------- persistence & inheritance ---------------------------
def test_lane_persisted_and_inherited_end_to_end(store):
    h = _reg(store, "H-info", lane="INFO_ACQUISITION")
    assert h["lane"] == "INFO_ACQUISITION"
    got = store.get_hypothesis(h["id"])
    assert got["lane"] == "INFO_ACQUISITION"

    e = store.create_experiment(experiment_key="E1", hypothesis_id=h["id"], spec={})
    assert e["lane"] == "INFO_ACQUISITION"
    assert store.get_experiment(e["id"])["lane"] == "INFO_ACQUISITION"

    ev = store.record_evaluation(experiment_id=e["id"], verdict="GO", result={})
    assert ev["lane"] == "INFO_ACQUISITION"

    f = store.record_failure(experiment_id=e["id"], failure_type="OVERFIT",
                             recommendation="retest")
    assert f["lane"] == "INFO_ACQUISITION"

    # knowledge inherits lane from the source experiment automatically.
    k = store.record_knowledge(knowledge_key="K1", kind="DEAD_END", summary="x",
                               source_experiment_id=e["id"])
    assert k["lane"] == "INFO_ACQUISITION"


def test_default_lane_is_price_derived(store):
    h = store.register_hypothesis(hypothesis_key="p", instrument="XAUUSD",
                                  timeframe="H1", horizon_bars=2, claim="c")
    assert h["lane"] == "PRICE_DERIVED"


# --------------------------- INFO vs PRICE separation ---------------------------
def test_lanes_are_sql_separable(store):
    _reg(store, "p1", lane="PRICE_DERIVED")
    _reg(store, "i1", lane="INFO_ACQUISITION")
    _reg(store, "i2", lane="INFO_ACQUISITION")
    price = store.list_hypotheses(lane="PRICE_DERIVED")
    info = store.list_hypotheses(lane="INFO_ACQUISITION")
    assert len(price) == 1 and len(info) == 2
    assert all(row["lane"] == "INFO_ACQUISITION" for row in info)


def test_knowledge_lane_column_distinguishes_info_and_price(store):
    # PRICE_DERIVED knowledge
    hp = _reg(store, "hp", lane="PRICE_DERIVED")
    ep = store.create_experiment(experiment_key="ep", hypothesis_id=hp["id"], spec={})
    store.record_knowledge(knowledge_key="kp", kind="DEAD_END", summary="price dead",
                           source_experiment_id=ep["id"])
    # INFO_ACQUISITION knowledge
    hi = _reg(store, "hi", lane="INFO_ACQUISITION")
    ei = store.create_experiment(experiment_key="ei", hypothesis_id=hi["id"], spec={})
    store.record_knowledge(knowledge_key="ki", kind="STRATEGY_LEAD", summary="info lead",
                           source_experiment_id=ei["id"])
    with store.manager.open() as conn:
        info = conn.execute("SELECT COUNT(*) FROM research_knowledge WHERE lane=?",
                            ("INFO_ACQUISITION",)).fetchone()[0]
        price = conn.execute("SELECT COUNT(*) FROM research_knowledge WHERE lane=?",
                             ("PRICE_DERIVED",)).fetchone()[0]
    assert info == 1 and price == 1


# --------------------------- fail-closed rejection ---------------------------
def test_invalid_lane_rejected_at_api(store):
    with pytest.raises(ValueError):
        _reg(store, "bad", lane="WHATEVER")


def test_explicit_knowledge_lane_validated(store):
    with pytest.raises(ValueError):
        store.record_knowledge(knowledge_key="k", kind="FINDING", summary="s",
                               lane="NOPE")


def test_db_check_constraint_rejects_invalid_lane(tmp_path):
    # The DB-level CHECK is a defence-in-depth backstop independent of the API.
    s = ResearchMemoryStore(db_path=tmp_path / "chk.db")
    with s.manager.open() as conn:
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                """INSERT INTO research_hypotheses
                   (hypothesis_key,instrument,timeframe,horizon_bars,claim,
                    go_criteria_json,content_sha256,status,lane)
                   VALUES('x','EURUSD','H4',2,'c','{}','h','PRE_REGISTERED','BOGUS')""")


# --------------------------- external proposals lane guard ---------------------------
def _external_db(tmp_path):
    db = tmp_path / "ext_r1.db"
    MigrationManager(SQLiteConnectionManager(db_path=db),
                     EXTERNAL_INTEL_MIGRATIONS_DIR).migrate()
    return db


def test_external_proposal_trigger_rejects_invalid_lane(tmp_path):
    db = _external_db(tmp_path)
    with sqlite3.connect(db) as conn:
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                """INSERT INTO ext_research_proposals
                   (proposal_key,instrument,lane,claim,novelty_rationale,
                    data_requirements_json,falsification_criteria,evidence_json,
                    source_ids_json,governance_status,created_at_utc,content_sha256)
                   VALUES('p','EURUSD','BOGUS','c','n','[]','f','{}','[]',
                          'ALLOWED','2026-01-01T00:00:00Z','h')""")


def test_external_proposal_trigger_allows_info_lane(tmp_path):
    db = _external_db(tmp_path)
    with sqlite3.connect(db) as conn:
        conn.execute(
            """INSERT INTO ext_research_proposals
               (proposal_key,instrument,lane,claim,novelty_rationale,
                data_requirements_json,falsification_criteria,evidence_json,
                source_ids_json,governance_status,created_at_utc,content_sha256)
               VALUES('p2','EURUSD','INFO_ACQUISITION','c','n','[]','f','{}','[]',
                      'ALLOWED','2026-01-01T00:00:00Z','h2')""")
        conn.commit()
        n = conn.execute("SELECT COUNT(*) FROM ext_research_proposals "
                         "WHERE lane='INFO_ACQUISITION'").fetchone()[0]
    assert n == 1


# --------------------------- migration upgrade preserves data ---------------------------
def test_migration_upgrades_existing_db_preserving_rows(tmp_path):
    """Simulate a v1 DB with a row, then migrate to v2; the row survives with a lane."""
    from nexora_research.config import RESEARCH_MIGRATIONS_DIR
    db = tmp_path / "v1.db"
    mgr = SQLiteConnectionManager(db_path=db)
    # Apply only v1 by pointing at a temp dir containing just the v1 script.
    v1dir = tmp_path / "mig_v1"
    v1dir.mkdir()
    shutil.copy(RESEARCH_MIGRATIONS_DIR / "001__research_memory_schema.sql", v1dir)
    MigrationManager(mgr, v1dir).migrate()
    # Insert a pre-R1 row (no lane column exists yet).
    with mgr.open() as conn:
        conn.execute(
            """INSERT INTO research_hypotheses
               (hypothesis_key,instrument,timeframe,horizon_bars,claim,
                go_criteria_json,content_sha256,status)
               VALUES('legacy','EURUSD','H4',2,'c','{}','h','PRE_REGISTERED')""")
        conn.commit()
    # Now apply the full migration set (adds lane + backfill).
    MigrationManager(mgr, RESEARCH_MIGRATIONS_DIR).migrate()
    with mgr.open() as conn:
        row = conn.execute("SELECT hypothesis_key, lane FROM research_hypotheses "
                           "WHERE hypothesis_key='legacy'").fetchone()
    assert row["hypothesis_key"] == "legacy"
    assert row["lane"] == "PRICE_DERIVED"  # safe default for pre-R1 data


def test_backfill_promotes_info_lane_from_go_criteria(tmp_path):
    """A pre-R1 hypothesis that stored lane=INFO_ACQUISITION in go_criteria is promoted."""
    from nexora_research.config import RESEARCH_MIGRATIONS_DIR
    db = tmp_path / "v1b.db"
    mgr = SQLiteConnectionManager(db_path=db)
    v1dir = tmp_path / "mig_v1b"
    v1dir.mkdir()
    shutil.copy(RESEARCH_MIGRATIONS_DIR / "001__research_memory_schema.sql", v1dir)
    MigrationManager(mgr, v1dir).migrate()
    with mgr.open() as conn:
        conn.execute(
            """INSERT INTO research_hypotheses
               (hypothesis_key,instrument,timeframe,horizon_bars,claim,
                go_criteria_json,content_sha256,status)
               VALUES('legacy_info','EURUSD','external',1,'c',
                      '{"lane":"INFO_ACQUISITION"}','h','PRE_REGISTERED')""")
        conn.commit()
    MigrationManager(mgr, RESEARCH_MIGRATIONS_DIR).migrate()
    with mgr.open() as conn:
        lane = conn.execute("SELECT lane FROM research_hypotheses "
                            "WHERE hypothesis_key='legacy_info'").fetchone()["lane"]
    assert lane == "INFO_ACQUISITION"


def test_lanes_constant_is_closed_set():
    assert set(LANES) == {"PRICE_DERIVED", "INFO_ACQUISITION"}
